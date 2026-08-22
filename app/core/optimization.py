"""Optimizacion de abastecimiento por programacion lineal entera mixta.

Funcionalidad:
    Decide, para cada pieza y ciudad, cuanto comprar y a que proveedor, con el
    menor costo total posible y respetando las restricciones operativas: llegar
    al inventario minimo, no pasar del maximo, cumplir la cantidad minima de
    orden de cada proveedor, no exceder su capacidad y no comprar mas de lo que
    se alcanza a consumir antes de que la pieza venza.

    Cada combinacion de pieza y ciudad se resuelve como un problema
    independiente. Son decisiones separadas mientras no exista un presupuesto
    global, y resolverlas por separado mantiene el modelo pequeño y la
    explicacion de cada recomendacion trazable a sus propias restricciones.

    Dos decisiones de politica gobiernan el modulo entero.

    La primera es cuanto reponer. El nivel objetivo no es una cobertura en meses
    fijada por constante sino la cantidad economica de pedido de Wilson: la que
    equilibra el flete que se paga por pedir contra el costo de mantener en
    bodega lo que se pidio de mas. De ahi sale tanto el nivel hasta el que se
    repone como el techo de inventario, que en una politica (s, S) son el mismo
    numero.

    La segunda es que se financia cuando el dinero no alcanza. El presupuesto ya
    no manda sobre todo: las piezas cuyo quiebre para una linea se reponen
    siempre, y el presupuesto se vuelve elastico hasta un excedente autorizado
    para conseguirlo. Solo lo que no compromete la continuidad de produccion
    compite por lo que sobre.
"""

import math

import pandas as pd
import pulp

from app.core.inventory import DAYS_PER_MONTH

MONTHS_PER_YEAR = 12

HOLDING_COST_RATE_ANNUAL = 0.25

EOQ_MAX_COVERAGE_MONTHS = 6.0

SHELF_LIFE_SAFETY_RATIO = 0.80

SCENARIO_BUDGET_USD = 40000.0

BUDGET_OVERRUN_MAX_USD = 4000.0

SERVICE_FLOOR_BY_CRITICALITY = {"A": 1.00, "B": 0.80, "C": 0.50}

STOCKOUT_COST_PER_EVENT_USD = {"A": 45000.0, "B": 4000.0, "C": 250.0}

PLANNING_PERIOD_DAYS = 30

SOLVER_TIME_LIMIT_SECONDS = 60

DECISION_BUY = "COMPRAR"
DECISION_HOLD = "NO_COMPRAR"
DECISION_REVIEW = "REVISAR"
DECISION_DEFERRED = "APLAZADO"
DECISION_ESCALATE = "ESCALAR"

DECISION_LABELS = {
    DECISION_BUY: "BUY",
    DECISION_HOLD: "NO ACTION",
    DECISION_REVIEW: "REVIEW",
    DECISION_DEFERRED: "DEFERRED",
    DECISION_ESCALATE: "ESCALATE",
}

REASON_ABOVE_MINIMUM = "Stock is above the operating minimum: no replenishment needed"
REASON_SHELF_LIFE_BLOCK = "Shelf life does not allow consuming even the minimum order quantity"
REASON_NO_SUPPLIER = "No offer meets the constraints for this city"
REASON_INFEASIBLE = "The model found no feasible solution"
REASON_LOW_CONFIDENCE = "Low confidence in the forecast: needs human validation"
REASON_OVER_BUDGET = "Does not fit in the discretionary budget of this run"
REASON_NOT_WORTH_IT = "Replenishing costs more than the stockout it prevents"
REASON_ESCALATE = "Critical part that does not fit even with the authorised budget overrun"


_cached_solver = None


def _solver_answers(candidate) -> bool:
    """Comprueba que un solver resuelve de verdad un modelo trivial.

    Entrada:
        candidate: instancia de solver de PuLP a probar.

    Salida:
        True si resuelve la sonda y devuelve el optimo.

    Funcionalidad:
        Existe porque declararse disponible no basta. PuLP considera disponible
        a COIN_CMD con que exista un ejecutable llamado cbc en la ruta, sin
        comprobar que arranque. En un entorno donde ese ejecutable es un
        lanzador roto, el solver pasa el filtro y luego falla al resolver la
        primera pieza, que es un error mucho mas dificil de diagnosticar que
        este.
    """
    probe = pulp.LpProblem("sonda", pulp.LpMinimize)
    variable = probe.add_variable("x", 0, 1, cat="Integer")
    probe += variable
    probe += variable >= 1
    try:
        probe.solve(candidate)
    except Exception:
        return False
    return pulp.LpStatus[probe.status] == "Optimal"


def _solver():
    """Devuelve el solver entero configurado.

    Entrada:
        Ninguna.

    Salida:
        Instancia de solver de PuLP lista para resolver el modelo.

    Funcionalidad:
        Prefiere COIN_CMD, que es la interfaz vigente hacia CBC, y recurre al
        CBC que trae PuLP cuando el primero no responde. CBC es suficiente para
        este problema: son cuarenta modelos de a lo sumo tres ofertas cada uno y
        se resuelven en milisegundos, sin necesidad de un solver comercial.

        La eleccion se prueba una sola vez por proceso y se conserva, para no
        pagar una sonda por cada una de las cuarenta piezas.
    """
    global _cached_solver
    if _cached_solver is not None:
        return _cached_solver

    for build in (pulp.COIN_CMD, pulp.PULP_CBC_CMD):
        candidate = build(msg=0, timeLimit=SOLVER_TIME_LIMIT_SECONDS)
        if _solver_answers(candidate):
            _cached_solver = candidate
            return _cached_solver

    raise RuntimeError(
        "Ningun solver entero responde. Instala CBC o revisa que el ejecutable "
        "cbc de la ruta arranque."
    )


COLUMNS = [
    "sku_id",
    "city_id",
    "description",
    "criticality",
    "on_hand_qty",
    "inventory_min",
    "inventory_max",
    "demand_monthly",
    "forecast_source",
    "shelf_life_days",
    "order_cost_usd",
    "holding_cost_usd",
    "eoq_units",
    "target_qty",
    "max_allowed_qty",
    "coverage_months",
    "decision",
    "recommended_qty",
    "supplier_id",
    "supplier_name",
    "unit_price_usd",
    "freight_cost_usd",
    "lead_time_days",
    "total_cost_usd",
    "alternatives_evaluated",
    "confidence",
    "stockout_cost_usd",
    "net_benefit_usd",
    "needs_review",
    "reason",
]


def days_of_cover(on_hand: int, monthly_demand: float) -> float:
    """Calcula cuantos dias aguantan las existencias actuales.

    Entrada:
        on_hand: unidades disponibles hoy.
        monthly_demand: demanda mensual proyectada.

    Salida:
        Dias que tardaria en agotarse la pieza al ritmo de consumo previsto.

    Funcionalidad:
        Es la traduccion de un nivel de inventario al unico termino en el que se
        puede comparar con un plazo de entrega: tiempo. Sin demanda prevista la
        pieza no se agota, y se devuelve un horizonte suficientemente largo como
        para que ninguna regla posterior la considere en riesgo.
    """
    if monthly_demand <= 0:
        return float(PLANNING_PERIOD_DAYS * 12)
    return on_hand / (monthly_demand / DAYS_PER_MONTH)


def stockout_days_avoided(on_hand: int, monthly_demand: float, lead_time_days: float) -> float:
    """Estima cuantos dias de quiebre evita reponer ahora.

    Entrada:
        on_hand: unidades disponibles hoy.
        monthly_demand: demanda mensual proyectada.
        lead_time_days: plazo de reposicion en dias.

    Salida:
        Dias de quiebre que se ahorran comprando en esta corrida en lugar de
        esperar a la siguiente.

    Funcionalidad:
        Compara dos futuros. Si se pide hoy, la pieza queda expuesta solo el
        tramo en que la cobertura actual no alcanza a cubrir el plazo de
        entrega. Si se aplaza a la siguiente corrida, esa exposicion crece en un
        periodo de planificacion completo. La diferencia es lo que compra la
        decision de hoy.

        Es un calculo deterministico: supone que la demanda ocurre al ritmo
        proyectado. Ignora por tanto que una serie volatil puede agotarse antes,
        de modo que subestima el riesgo justo en las piezas menos predecibles.
        Corregirlo exige trabajar con la distribucion de la demanda y no con su
        valor esperado.
    """
    cover = days_of_cover(on_hand, monthly_demand)
    exposed_now = max(0.0, lead_time_days - cover)
    exposed_later = max(0.0, PLANNING_PERIOD_DAYS + lead_time_days - cover)
    return round(exposed_later - exposed_now, 2)


def stockout_cost(
    on_hand: int,
    monthly_demand: float,
    lead_time_days: float,
    criticality: str,
    issue_rate: float = 1.0,
) -> float:
    """Valora en dolares el quiebre que evita reponer ahora.

    Entrada:
        on_hand: unidades disponibles hoy.
        monthly_demand: demanda mensual proyectada.
        lead_time_days: plazo de reposicion en dias.
        criticality: criticidad A, B o C de la pieza.
        issue_rate: proporcion de dias en que la pieza se pide realmente. Se
            conserva por compatibilidad de firma pero ya no interviene.

    Salida:
        Costo esperado del quiebre en USD, o cero si no hay exposicion.

    Funcionalidad:
        Pone en la misma unidad las dos mitades de la decision. Hasta aqui el
        sistema minimizaba el costo de comprar sin saber nunca lo que cuesta no
        tener la pieza, asi que una pieza critica competia contra el flete en
        igualdad de condiciones. Con esto, la criticidad deja de mover solo el
        inventario minimo y entra en la funcion objetivo.

        Un quiebre no cuesta por dia sino por evento. Cuando falta una refaccion
        critica no se pierde un dia de margen: se para una linea y no vuelve a
        arrancar hasta que la pieza llega. Por eso la valoracion es el producto
        de dos cosas: la probabilidad de que alguien pida la pieza mientras no
        esta, y lo que cuesta esa parada.

        La probabilidad sale de un proceso de Poisson con la misma tasa que
        produjo la proyeccion. Es lo que corrige el error de la version
        anterior, que multiplicaba los dias expuestos por una tasa de salida
        medida aparte. Sonaba razonable y descontaba dos veces la misma rareza:
        los dias expuestos ya se calculan sobre la cobertura, que se deriva de la
        demanda proyectada, de modo que una pieza que se mueve poco ya tiene
        mucha cobertura y poca exposicion. Volver a multiplicar por la frecuencia
        con que se pide hundia la valoracion de todo el catalogo intermitente
        hasta cero y ninguna reposicion salia rentable.

        Derivar la probabilidad de la misma tasa de la proyeccion tiene ademas la
        ventaja de ser coherente con la etapa anterior: si la proyeccion dice
        que la pieza consume `d` unidades al dia, la probabilidad de que haga
        falta en `t` dias es `1 - exp(-d*t)` y no un parametro independiente que
        pueda contradecirla.

        El costo del evento es un parametro de negocio y no una estimacion del
        sistema: hay que validarlo con mantenimiento antes de darle poder sobre
        las compras, porque su magnitud decide por si sola cuanto pesa la
        criticidad frente al precio.

        Sigue siendo una cota superior. Supone que la parada se pierde entera,
        sin contar que en la practica se canibaliza la pieza de otra maquina o se
        expedita la orden pagando de mas.
    """
    per_event = STOCKOUT_COST_PER_EVENT_USD.get(criticality, 0.0)
    exposed = stockout_days_avoided(on_hand, monthly_demand, lead_time_days)
    if exposed <= 0 or per_event <= 0 or monthly_demand <= 0:
        return 0.0

    daily_rate = monthly_demand / DAYS_PER_MONTH
    probability = 1.0 - math.exp(-daily_rate * exposed)
    return round(probability * per_event, 2)


def _service_requirement(pool: list, affordable: list, criticality: str, floors: dict) -> int:
    """Calcula cuantas compras de una clase de criticidad hay que financiar.

    Entrada:
        pool: candidatos discrecionales de la corrida.
        affordable: los que caben por si solos en lo que queda de presupuesto.
        criticality: clase de criticidad que se esta evaluando.
        floors: fraccion minima de cada clase que debe financiarse.

    Salida:
        Numero de compras de esa clase que la restriccion exige aprobar.

    Funcionalidad:
        La fraccion se aplica sobre todas las reposiciones necesarias de la
        clase, no sobre las que caben, porque el nivel de servicio se declara
        sobre la necesidad real. Pero el resultado se recorta a las que caben:
        exigir mas de las que el presupuesto puede pagar hace el modelo
        infactible sin informar de nada.
    """
    share = floors.get(criticality, 0.0)
    if share <= 0:
        return 0
    needed = len([c for c in pool if c.get("criticality") == criticality])
    available = len([c for c in affordable if c.get("criticality") == criticality])
    return min(available, math.ceil(share * needed))


def _solve_knapsack(pool: list, affordable: list, capacity: float, floors: dict, enforced: list):
    """Resuelve la mochila discrecional con los pisos de servicio indicados.

    Entrada:
        pool: candidatos discrecionales de la corrida.
        affordable: los que caben por si solos en la capacidad disponible.
        capacity: dinero disponible en USD.
        floors: fraccion minima de cada clase que debe financiarse.
        enforced: clases de criticidad cuyo piso se impone en esta pasada.

    Salida:
        Conjunto de claves aprobadas, o None si el modelo resulta infactible.

    Funcionalidad:
        Es la mochila 0/1 de siempre —maximizar beneficio neto sin pasar del
        dinero— mas una restriccion de cardinalidad por clase de criticidad.

        Devolver None en lugar de un conjunto vacio es lo que permite distinguir
        entre no poder pagar nada y no poder cumplir un piso de servicio, que son
        dos situaciones que exigen respuestas distintas.
    """
    problem = pulp.LpProblem("presupuesto", pulp.LpMaximize)
    switches = {
        candidate["key"]: problem.add_variable(f"buy_{index}", cat="Binary")
        for index, candidate in enumerate(affordable)
    }

    problem += pulp.lpSum(
        [candidate["benefit"] * switches[candidate["key"]] for candidate in affordable]
    )
    problem += (
        pulp.lpSum([candidate["cost"] * switches[candidate["key"]] for candidate in affordable])
        <= capacity
    )

    for criticality in enforced:
        required = _service_requirement(pool, affordable, criticality, floors)
        if required <= 0:
            continue
        members = [c for c in affordable if c.get("criticality") == criticality]
        problem += pulp.lpSum([switches[c["key"]] for c in members]) >= required

    problem.solve(_solver())
    if pulp.LpStatus[problem.status] != "Optimal":
        return None

    return {key for key, switch in switches.items() if round(switch.value() or 0) == 1}


def allocate_discretionary(pool: list, capacity: float, floors: dict) -> set:
    """Reparte entre las compras discrecionales el dinero que quedo libre.

    Entrada:
        pool: candidatos que no comprometen la continuidad de produccion.
        capacity: dinero disponible en USD tras cubrir lo critico.
        floors: fraccion minima de cada clase de criticidad que debe financiarse.

    Salida:
        Conjunto de claves de las compras aprobadas.

    Funcionalidad:
        Resuelve una mochila: maximiza el beneficio neto total, es decir el
        quiebre que se evita menos lo que cuesta evitarlo, sin pasar del dinero
        disponible. No es lo mismo que ir aprobando de mayor beneficio a menor
        hasta agotarlo, porque una compra muy rentable y cara puede desplazar a
        varias algo menos rentables y baratas que juntas rinden mas.

        Sobre esa mochila se imponen los pisos de servicio por criticidad, que
        existen por coherencia con la etapa anterior: si al calcular el
        inventario minimo se declaro un 90 % de nivel de servicio para las piezas
        B, el presupuesto no deberia contradecirlo aplazando la mayoria de ellas.

        Cuando el dinero no da ni para los pisos, se sueltan de menos exigente a
        mas exigente en lugar de devolver infactible. Aplazar una pieza C antes
        que una B es la misma jerarquia que declara el resto del sistema, y el
        nivel de servicio realmente alcanzado queda visible en el informe.
    """
    if capacity <= 0 or not pool:
        return set()

    affordable = [c for c in pool if c["cost"] <= capacity]
    if not affordable:
        return set()
    if sum(c["cost"] for c in pool) <= capacity:
        return {candidate["key"] for candidate in pool}

    classes = sorted(
        {c.get("criticality") for c in pool if floors.get(c.get("criticality"), 0.0) > 0},
        key=lambda name: floors[name],
    )

    for dropped in range(len(classes) + 1):
        solution = _solve_knapsack(pool, affordable, capacity, floors, classes[dropped:])
        if solution is not None:
            return solution
    return set()


def allocate_budget(
    candidates: list, budget, overrun_max: float = BUDGET_OVERRUN_MAX_USD, floors: dict = None
) -> dict:
    """Elige que compras se financian priorizando la continuidad de produccion.

    Entrada:
        candidates: lista de diccionarios con key, cost, benefit, criticality y
            stockout_cost de cada compra que el optimizador recomienda.
        budget: tope de gasto en USD, o None para no aplicar limite.
        overrun_max: excedente maximo autorizado para cubrir lo critico.
        floors: fraccion minima de cada clase de criticidad que debe
            financiarse. Por defecto la politica del modulo.

    Salida:
        Diccionario con el conjunto de claves aprobadas y el de las que hay que
        escalar a gerencia.

    Funcionalidad:
        Invierte el orden de mando del modelo anterior. Antes el presupuesto
        mandaba sobre todo y una pieza podia quedar aplazada aunque su quiebre
        parara una linea, simplemente porque otras rendian mas por dolar. Eso es
        un mal negocio que la mochila no veia, porque trataba todas las piezas
        con la misma moneda.

        Ahora las reposiciones de criticidad A no compiten: se financian primero
        y el presupuesto se estira hasta un excedente autorizado para
        conseguirlo. Solo el dinero que sobra despues se reparte entre las demas,
        y el excedente queda reportado en vez de escondido, que es justo el
        punto: gastar de mas para no parar una linea es una decision legitima
        siempre que se vea.

        Cuando ni con el excedente alcanza, el modelo no relaja la regla por su
        cuenta ni falla en silencio. Cubre las criticas que mas quiebre evitan y
        devuelve el resto para escalar, porque ampliar el presupuesto es una
        decision de gerencia y no del optimizador.
    """
    floors = SERVICE_FLOOR_BY_CRITICALITY if floors is None else floors

    if budget is None:
        return {"approved": {candidate["key"] for candidate in candidates}, "escalated": set()}

    mandatory = [c for c in candidates if floors.get(c.get("criticality"), 0.0) >= 1.0]
    mandatory_keys = {c["key"] for c in mandatory}
    flexible = [c for c in candidates if c["key"] not in mandatory_keys]

    ceiling = budget + max(0.0, overrun_max)
    committed = sum(c["cost"] for c in mandatory)

    if committed <= ceiling:
        approved, escalated, spent = set(mandatory_keys), set(), committed
    else:
        approved, escalated, spent = set(), set(), 0.0
        for candidate in sorted(
            mandatory, key=lambda c: (-float(c.get("stockout_cost", 0.0)), c["cost"])
        ):
            if spent + candidate["cost"] <= ceiling:
                approved.add(candidate["key"])
                spent += candidate["cost"]
            else:
                escalated.add(candidate["key"])

    remaining = max(0.0, budget - spent)
    return {
        "approved": approved | allocate_discretionary(flexible, remaining, floors),
        "escalated": escalated,
    }


def apply_budget(
    recommendations: pd.DataFrame, budget, overrun_max: float = BUDGET_OVERRUN_MAX_USD
) -> pd.DataFrame:
    """Reparte el dinero de la corrida y marca lo que no alcanzo a financiarse.

    Entrada:
        recommendations: tabla de decisiones ya resueltas por pieza.
        budget: tope de gasto en USD, o None para no aplicar limite.
        overrun_max: excedente maximo autorizado para cubrir lo critico.

    Salida:
        La misma tabla con las compras no financiadas marcadas como aplazadas y
        con las criticas que no caben marcadas para escalar.

    Funcionalidad:
        Solo compiten por el dinero las filas en COMPRAR. Las que quedan en
        revision no son gasto aprobado sino una decision pendiente de una
        persona, y descontarlas del presupuesto reservaria dinero para compras
        que quiza nunca se hagan.

        Las filas aplazadas conservan la cantidad, el proveedor y el costo. La
        recomendacion tecnica sigue siendo valida; lo que falta es el dinero, y
        el comprador necesita ver cuanto pediria para poder defender una
        ampliacion del presupuesto, junto con el quiebre que ese dinero evitaria.

        Escalar es distinto de aplazar y por eso lleva estado propio. Una pieza
        aplazada es una compra que rendia menos que otras; una escalada es una
        pieza cuyo quiebre para una linea y que ni con el excedente autorizado
        cabe. La primera la resuelve un comprador la corrida siguiente, la
        segunda exige que alguien amplie el presupuesto ahora.
    """
    if budget is None or recommendations.empty:
        return recommendations

    buying = recommendations[recommendations["decision"] == DECISION_BUY]
    if buying.empty:
        return recommendations

    candidates = [
        {
            "key": (record["sku_id"], record["city_id"]),
            "cost": float(record["total_cost_usd"]),
            "benefit": float(record["net_benefit_usd"]),
            "criticality": record["criticality"],
            "stockout_cost": float(record["stockout_cost_usd"] or 0.0),
        }
        for record in buying.to_dict(orient="records")
    ]
    allocation = allocate_budget(candidates, budget, overrun_max)
    approved, escalated = allocation["approved"], allocation["escalated"]

    result = recommendations.copy()
    keys = result.apply(lambda row: (row["sku_id"], row["city_id"]), axis=1)
    purchases = result["decision"] == DECISION_BUY

    to_escalate = purchases & keys.isin(escalated)
    to_defer = purchases & ~keys.isin(approved) & ~to_escalate

    result.loc[to_escalate, "reason"] = result.loc[to_escalate].apply(
        lambda row: (
            f"{REASON_ESCALATE}. Replenishing it needs {row['total_cost_usd']:.2f} USD "
            f"beyond the {budget:.2f} USD budget and its {overrun_max:.2f} USD authorised "
            f"overrun. Leaving it uncovered exposes a stockout valued at "
            f"{row['stockout_cost_usd']:.2f} USD on a criticality "
            f"{row['criticality']} part"
        ),
        axis=1,
    )
    result.loc[to_escalate, "decision"] = DECISION_ESCALATE
    result.loc[to_escalate, "needs_review"] = 1

    result.loc[to_defer, "reason"] = result.loc[to_defer].apply(
        lambda row: (
            f"{REASON_OVER_BUDGET}. It needs {row['total_cost_usd']:.2f} USD and the "
            f"{budget:.2f} USD of the run go further on other parts once production "
            f"continuity is covered. Deferring it exposes a stockout valued at "
            f"{row['stockout_cost_usd']:.2f} USD"
        ),
        axis=1,
    )
    result.loc[to_defer, "decision"] = DECISION_DEFERRED
    result.loc[to_defer, "needs_review"] = 1
    return result


def budget_allocation_summary(
    recommendations: pd.DataFrame,
    budget=SCENARIO_BUDGET_USD,
    overrun_max: float = BUDGET_OVERRUN_MAX_USD,
    floors: dict = None,
) -> dict:
    """Resume como quedo repartido el dinero y que nivel de servicio se alcanzo.

    Entrada:
        recommendations: tabla de decisiones ya repartidas.
        budget: presupuesto nominal de la corrida en USD.
        overrun_max: excedente maximo autorizado.
        floors: fraccion minima de cada clase que se queria financiar.

    Salida:
        Diccionario con el gasto, el excedente consumido, lo aplazado, lo
        escalado y el nivel de servicio conseguido por clase de criticidad
        frente al que se declaro.

    Funcionalidad:
        Todo se deriva de la tabla ya resuelta y no de la corrida del solver, de
        modo que el informe no pueda contradecir a la decision que el comprador
        tiene delante.

        El nivel de servicio alcanzado se mide sobre las reposiciones que
        procedian, es decir las que el optimizador resolvio como compra antes de
        repartir el dinero: comprar, aplazar y escalar. Las filas en revision
        quedan fuera porque no son gasto aprobado sino una decision pendiente.

        Publicarlo junto al piso declarado es lo que hace auditable la politica.
        Si el presupuesto obligo a bajar del 80 % en las piezas B, la pantalla lo
        dice en lugar de dejar creer que la politica se cumplio.
    """
    floors = SERVICE_FLOOR_BY_CRITICALITY if floors is None else floors
    resolved = (DECISION_BUY, DECISION_DEFERRED, DECISION_ESCALATE)

    if recommendations.empty:
        rows = pd.DataFrame(columns=["criticality", "decision", "total_cost_usd"])
    else:
        rows = recommendations[recommendations["decision"].isin(resolved)]

    totals = {
        decision: (
            round(float(rows[rows["decision"] == decision]["total_cost_usd"].sum()), 2),
            int((rows["decision"] == decision).sum()),
        )
        for decision in resolved
    }

    invested, bought = totals[DECISION_BUY]
    deferred_usd, deferred = totals[DECISION_DEFERRED]
    escalated_usd, escalated = totals[DECISION_ESCALATE]

    service = []
    for criticality, floor in sorted(floors.items(), key=lambda item: -item[1]):
        block = rows[rows["criticality"] == criticality]
        needed = len(block)
        funded = int((block["decision"] == DECISION_BUY).sum())
        service.append(
            {
                "criticality": criticality,
                "needed": needed,
                "funded": funded,
                "achieved": round(funded / needed, 3) if needed else None,
                "floor": floor,
                "met": needed == 0 or funded >= math.ceil(floor * needed),
            }
        )

    return {
        "budget_usd": budget,
        "overrun_max_usd": overrun_max,
        "overrun_usd": round(max(0.0, invested - budget), 2) if budget is not None else 0.0,
        "invested_usd": invested,
        "purchases": bought,
        "deferred_usd": deferred_usd,
        "deferred": deferred,
        "escalated_usd": escalated_usd,
        "escalated": escalated,
        "service": service,
        "continuity_protected": escalated == 0,
    }


def consumable_within_shelf_life(monthly_demand: float, shelf_life_days: int, on_hand: int) -> int:
    """Calcula cuanto se alcanza a consumir antes de que la pieza venza.

    Entrada:
        monthly_demand: demanda mensual proyectada.
        shelf_life_days: vida util de la pieza en dias.
        on_hand: existencias actuales.

    Salida:
        Unidades maximas que tiene sentido comprar sin arriesgar obsolescencia.

    Funcionalidad:
        Traduce la vida util a unidades consumibles y descuenta lo que ya hay en
        bodega, porque las existencias actuales se consumen primero. Se aplica un
        margen de seguridad para no apurar la fecha limite.
    """
    daily_demand = monthly_demand / DAYS_PER_MONTH
    usable_days = shelf_life_days * SHELF_LIFE_SAFETY_RATIO
    return max(0, math.floor(daily_demand * usable_days) - on_hand)


def holding_cost_per_unit_year(unit_cost_usd: float) -> float:
    """Calcula lo que cuesta tener una unidad parada en bodega durante un año.

    Entrada:
        unit_cost_usd: valor unitario de la pieza en el maestro.

    Salida:
        Costo de posesion en USD por unidad y año.

    Funcionalidad:
        Se aplica una tasa anual sobre el valor de la pieza, que es como se mide
        el costo de posesion en la practica: no es alquiler de estanteria sino
        capital inmovilizado, seguro, manejo y el riesgo de que la pieza quede
        obsoleta antes de usarse. La tasa es un parametro de negocio, no una
        estimacion del sistema, y su magnitud decide cuanto se pide de una vez.
    """
    return max(0.0, float(unit_cost_usd)) * HOLDING_COST_RATE_ANNUAL


def economic_order_quantity(
    monthly_demand: float, unit_cost_usd: float, order_cost_usd: float
) -> float:
    """Calcula la cantidad economica de pedido de una pieza.

    Entrada:
        monthly_demand: demanda mensual proyectada.
        unit_cost_usd: valor unitario de la pieza.
        order_cost_usd: costo fijo de traer un pedido, es decir el flete.

    Salida:
        Cantidad optima por pedido en unidades, sin redondear.

    Funcionalidad:
        Es la formula de Wilson, `Q = sqrt(2*K*D/h)`, que sale de igualar las dos
        mitades del costo anual que el tamaño de pedido mueve en direcciones
        opuestas: pedir mucho de una vez reparte el flete entre mas unidades pero
        deja mas capital parado en bodega, y pedir poco hace lo contrario.

        Sustituye a la cobertura en meses fijada por constante que el sistema
        usaba antes. La diferencia no es de precision sino de defensa: una
        cobertura de mes y medio no responde a por que mes y medio, mientras que
        esta cantidad se deriva del flete y del costo unitario que ya estan en
        los datos.

        Devuelve cero cuando falta cualquiera de los tres insumos. Sin demanda no
        hay nada que reponer, y sin flete o sin valor unitario la formula no
        tiene el equilibrio que la justifica, asi que es mas honesto no pedir
        nada extra que inventar un tamaño de lote.
    """
    annual_demand = max(0.0, float(monthly_demand)) * MONTHS_PER_YEAR
    holding = holding_cost_per_unit_year(unit_cost_usd)
    order_cost = max(0.0, float(order_cost_usd))

    if annual_demand <= 0 or holding <= 0 or order_cost <= 0:
        return 0.0
    return math.sqrt(2.0 * order_cost * annual_demand / holding)


def replenishment_level(
    monthly_demand: float, inventory_min: int, unit_cost_usd: float, order_cost_usd: float
) -> dict:
    """Calcula hasta que nivel conviene reponer y con que cifras se justifica.

    Entrada:
        monthly_demand: demanda mensual proyectada.
        inventory_min: inventario minimo, que es el punto de reorden.
        unit_cost_usd: valor unitario de la pieza.
        order_cost_usd: costo fijo de traer un pedido a esa ciudad.

    Salida:
        Diccionario con el nivel objetivo y con cada termino que lo compone: la
        demanda anual, el costo de posesion, el costo de pedir, la cantidad
        economica antes y despues del tope, y el propio tope.

    Funcionalidad:
        Es la politica `(s, S)` clasica: se repone cuando el inventario cae al
        punto de reorden `s` y se pide hasta `S = s + Q`. Como nunca se compra
        por encima de `S`, ese nivel es a la vez el objetivo de reposicion y el
        techo de inventario de la pieza. Dejan de ser dos constantes distintas
        porque en esta politica son el mismo numero.

        El tope de cobertura acota la cantidad economica. Una pieza barata con
        flete caro puede pedir lotes de mas de un año de consumo, que es optimo
        en costo y pesimo en obsolescencia porque la formula de Wilson no sabe
        que las piezas caducan. Recortarlo cuesta poco: la curva de costo total
        es plana alrededor del optimo, y equivocarse en el doble del lote optimo
        encarece el total solo un 25 %.

        Devuelve el detalle completo y no solo el nivel porque la interfaz tiene
        que poder mostrar de donde sale cada cifra: un numero sin sus terminos no
        se puede auditar.
    """
    annual_demand = max(0.0, float(monthly_demand)) * MONTHS_PER_YEAR
    holding = holding_cost_per_unit_year(unit_cost_usd)
    raw = economic_order_quantity(monthly_demand, unit_cost_usd, order_cost_usd)
    cap = math.floor(max(0.0, float(monthly_demand)) * EOQ_MAX_COVERAGE_MONTHS)

    quantity = min(math.ceil(raw), cap) if raw > 0 and cap > 0 else 0

    return {
        "annual_demand": round(annual_demand, 2),
        "holding_cost_usd": round(holding, 4),
        "order_cost_usd": round(max(0.0, float(order_cost_usd)), 2),
        "eoq_raw": round(raw, 2),
        "eoq_units": int(quantity),
        "coverage_cap_units": int(cap),
        "level": int(max(inventory_min, inventory_min + quantity)),
    }


def planning_order_cost(offers: pd.DataFrame) -> float:
    """Estima el costo fijo de traer un pedido antes de elegir proveedor.

    Entrada:
        offers: ofertas aplicables a la pieza en esa ciudad, con su flete ya
            ajustado al destino.

    Salida:
        Flete de planificacion en USD por pedido.

    Funcionalidad:
        La cantidad economica necesita el costo de pedir, pero el proveedor no se
        conoce hasta que se resuelve el modelo entero, y el modelo entero
        necesita la cantidad. Se rompe el circulo con el flete medio de las
        ofertas que podrian surtir el caso.

        La aproximacion es barata precisamente por la forma de la formula: el
        flete entra bajo una raiz cuadrada, asi que confundirse en el doble mueve
        la cantidad solo un 41 %, y el costo total todavia menos porque la curva
        es plana cerca del optimo.
    """
    if offers.empty or "freight_cost_usd" not in offers:
        return 0.0
    return float(offers["freight_cost_usd"].mean())


_offer_index_cache = {}


def _offer_index(offers: pd.DataFrame, coverage: pd.DataFrame, suppliers: pd.DataFrame) -> tuple:
    """Cruza una sola vez el catalogo de ofertas con la cobertura geografica.

    Entrada:
        offers: catalogo de ofertas proveedor-pieza.
        coverage: cobertura geografica de los proveedores.
        suppliers: catalogo de proveedores.

    Salida:
        Tupla (indice, vacio) donde el indice mapea cada par pieza-ciudad a sus
        ofertas aplicables y vacio es un DataFrame con las mismas columnas y sin
        filas, para devolver cuando el par no existe.

    Funcionalidad:
        Existe por una razon de escala que aparecio al cambiar de fuente. El
        cruce se hacia dentro de la consulta de cada pieza, de modo que con
        cuarenta series eran cuarenta uniones sobre una tabla de cincuenta filas
        y no se notaba. Con mas de mil doscientas series sobre dos mil ofertas se
        volvio el cuello de botella de la pantalla: armar la cola pasaba de
        milisegundos a mas de siete segundos, que es tiempo que el comprador ve.

        Hacer el cruce completo una vez y despues buscar por clave da el mismo
        resultado y convierte mil doscientas uniones en una. El resultado se
        conserva mientras las mismas tablas sigan en memoria; como la capa de
        servicios ya las cachea, en la practica se calcula una vez por proceso y
        se rehace solo cuando alguien recarga el dataset.
    """
    key = (id(offers), id(coverage), id(suppliers), len(offers), len(coverage), len(suppliers))
    cached = _offer_index_cache.get(key)
    if cached is not None:
        return cached

    active = suppliers[suppliers["active"]]
    joined = offers.merge(coverage, on="supplier_id").merge(
        active[["supplier_id", "name", "lead_time_avg_days"]], on="supplier_id"
    )
    if not joined.empty:
        joined["lead_time_days"] = joined["lead_time_avg_days"] + joined["lead_time_extra_days"]

    index = {pair: block for pair, block in joined.groupby(["sku_id", "city_id"])}
    entry = (index, joined.iloc[0:0])

    _offer_index_cache.clear()
    _offer_index_cache[key] = entry
    return entry


def candidate_offers(
    sku: str, city: str, offers: pd.DataFrame, coverage: pd.DataFrame, suppliers: pd.DataFrame
) -> pd.DataFrame:
    """Reune las ofertas disponibles para una pieza en una ciudad.

    Entrada:
        sku: identificador de la pieza.
        city: identificador de la ciudad.
        offers: catalogo de ofertas proveedor-pieza.
        coverage: cobertura geografica de los proveedores.
        suppliers: catalogo de proveedores.

    Salida:
        DataFrame de ofertas aplicables, con el flete y el plazo de entrega ya
        ajustados a la ciudad de destino.

    Funcionalidad:
        Cruza que el proveedor venda la pieza con que atienda esa ciudad. El
        plazo de entrega suma los dias adicionales cuando la ciudad no es su
        sede, y solo se consideran proveedores activos.
    """
    index, empty = _offer_index(offers, coverage, suppliers)
    return index.get((sku, city), empty)


def offer_costs(
    sku: str,
    city: str,
    quantity: int,
    offers: pd.DataFrame,
    coverage: pd.DataFrame,
    suppliers: pd.DataFrame,
    chosen_supplier=None,
) -> list:
    """Cotiza cada oferta aplicable a una pieza en una ciudad.

    Entrada:
        sku: identificador de la pieza.
        city: identificador de la ciudad.
        quantity: unidades a cotizar. Si es cero se cotiza el lote minimo de
            cada proveedor.
        offers: catalogo de ofertas proveedor-pieza.
        coverage: cobertura geografica de los proveedores.
        suppliers: catalogo de proveedores.
        chosen_supplier: proveedor que finalmente se selecciono, si lo hubo.

    Salida:
        Lista de diccionarios ordenada de menor a mayor costo total, cada uno con
        el proveedor, su precio, su lote minimo, su flete, su plazo, las unidades
        cotizadas, el costo resultante y si fue el elegido.

    Funcionalidad:
        Hace comparable lo que ofrecio cada proveedor. Todos se cotizan sobre la
        misma cantidad, salvo que su lote minimo obligue a mas, que es la unica
        comparacion honesta: un proveedor mas barato por unidad puede salir mas
        caro si obliga a llevarse el triple.

        La usan tanto el detalle de una fila en la cola como el resumen de lo que
        aporta el optimizador, de modo que ambos den la misma cifra.
    """
    applicable = candidate_offers(sku, city, offers, coverage, suppliers)
    if applicable.empty:
        return []

    rows = []
    for _, offer in applicable.iterrows():
        units = max(int(quantity), int(offer["moq"])) if quantity else int(offer["moq"])
        rows.append(
            {
                "supplier_id": offer["supplier_id"],
                "supplier_name": offer["name"],
                "unit_price_usd": round(float(offer["unit_price_usd"]), 2),
                "moq": int(offer["moq"]),
                "freight_cost_usd": round(float(offer["freight_cost_usd"]), 2),
                "lead_time_days": round(float(offer["lead_time_days"]), 1),
                "units": units,
                "total_cost_usd": round(
                    units * float(offer["unit_price_usd"]) + float(offer["freight_cost_usd"]), 2
                ),
                "chosen": offer["supplier_id"] == chosen_supplier,
            }
        )

    return sorted(rows, key=lambda item: item["total_cost_usd"])


def solve_single_purchase(need: int, ceiling: int, offers: pd.DataFrame) -> dict:
    """Resuelve la compra optima de una pieza en una ciudad.

    Entrada:
        need: unidades que faltan para alcanzar el inventario minimo.
        ceiling: unidades maximas que se permite comprar.
        offers: ofertas aplicables, con precio, minimo de orden, capacidad y
            flete ya ajustados a la ciudad.

    Salida:
        Diccionario con la cantidad, el proveedor elegido, el costo total y el
        estado de la resolucion.

    Funcionalidad:
        Plantea un modelo entero mixto que minimiza el costo de compra mas el
        flete. Una variable binaria por oferta activa o desactiva al proveedor,
        lo que permite imponer su cantidad minima de orden solo cuando se le
        compra. El modelo obliga a cubrir la necesidad sin pasar del techo, y
        elige un unico proveedor por pieza y ciudad para que la orden sea
        operativamente simple de ejecutar.
    """
    problem = pulp.LpProblem("abastecimiento", pulp.LpMinimize)
    quantities = {}
    switches = {}

    for _, offer in offers.iterrows():
        offer_id = offer["offer_id"]
        upper = int(min(ceiling, offer["capacity_per_month"]))
        quantities[offer_id] = problem.add_variable(f"qty_{offer_id}", 0, upper, cat="Integer")
        switches[offer_id] = problem.add_variable(f"use_{offer_id}", cat="Binary")

    problem += pulp.lpSum(
        [
            offer["unit_price_usd"] * quantities[offer["offer_id"]]
            + offer["freight_cost_usd"] * switches[offer["offer_id"]]
            for _, offer in offers.iterrows()
        ]
    )

    problem += pulp.lpSum(quantities.values()) >= need
    problem += pulp.lpSum(quantities.values()) <= ceiling
    problem += pulp.lpSum(switches.values()) <= 1

    for _, offer in offers.iterrows():
        offer_id = offer["offer_id"]
        upper = int(min(ceiling, offer["capacity_per_month"]))
        problem += quantities[offer_id] >= offer["moq"] * switches[offer_id]
        problem += quantities[offer_id] <= upper * switches[offer_id]

    problem.solve(_solver())
    status = pulp.LpStatus[problem.status]

    if status != "Optimal":
        return {"status": status, "quantity": 0, "offer": None, "total_cost": 0.0}

    for _, offer in offers.iterrows():
        offer_id = offer["offer_id"]
        quantity = round(quantities[offer_id].value() or 0)
        if quantity > 0:
            return {
                "status": status,
                "quantity": quantity,
                "offer": offer,
                "total_cost": round(
                    quantity * offer["unit_price_usd"] + offer["freight_cost_usd"], 2
                ),
            }
    return {"status": status, "quantity": 0, "offer": None, "total_cost": 0.0}


def build_recommendations(
    inventory: pd.DataFrame,
    forecast: pd.DataFrame,
    parts: pd.DataFrame,
    offers: pd.DataFrame,
    coverage: pd.DataFrame,
    suppliers: pd.DataFrame,
    budget=SCENARIO_BUDGET_USD,
    overrun_max: float = BUDGET_OVERRUN_MAX_USD,
) -> pd.DataFrame:
    """Genera la recomendacion de compra para todo el catalogo.

    Entrada:
        inventory: existencias actuales por pieza y ciudad.
        forecast: proyeccion de demanda con inventario minimo y confianza.
        parts: maestro de piezas.
        offers: catalogo de ofertas proveedor-pieza.
        coverage: cobertura geografica de los proveedores.
        suppliers: catalogo de proveedores.
        budget: tope de gasto de la corrida en USD. None desactiva el limite.
        overrun_max: excedente maximo autorizado para cubrir lo critico.

    Salida:
        DataFrame con una fila por pieza y ciudad y las columnas declaradas en
        COLUMNS, incluyendo la decision, el proveedor elegido y el motivo.

    Funcionalidad:
        Para cada combinacion evalua primero las reglas que pueden descartar la
        compra sin necesidad de optimizar: inventario suficiente, ausencia de
        proveedor o vida util insuficiente. Solo cuando la compra procede se
        plantea el modelo.

        Existe un tercer desenlace ademas de comprar o no comprar. Cuando la
        cantidad minima de orden del proveedor supera el maximo que la pieza
        admite en bodega, la compra no es imposible pero tampoco es automatica:
        se resuelve igualmente para saber cuanto costaria y cuantos meses de
        inventario dejaria, y se devuelve marcada para que decida el comprador.
        Es una tension habitual en repuestos baratos que se venden por lote.

        Cada fila lleva el motivo de la decision y la marca de revision humana,
        de modo que un comprador pueda auditarla sin conocer el modelo por
        dentro.

        La cantidad que se pide sale de la formula de Wilson y no de una
        cobertura en meses fijada por constante, de modo que el flete y el valor
        de la pieza —que ya estan en los datos— decidan cuanto se trae de una
        vez. Como la politica es de reposicion hasta un nivel, ese nivel es
        tambien el techo de inventario de la pieza.

        Al final se reparte el dinero de la corrida entre las compras que
        procedian. Es el unico paso que mira todas las piezas a la vez: hasta
        aqui cada decision era independiente de las demas. Y no reparte por
        rentabilidad a secas: lo que para una linea se financia primero, y solo
        despues compite el resto por lo que queda.
    """
    parts_by_sku = parts.set_index("sku_id")
    merged = inventory.merge(forecast, on=["sku_id", "city_id"], suffixes=("", "_fc"))

    rows = []
    for _, record in merged.iterrows():
        sku, city = record["sku_id"], record["city_id"]
        part = parts_by_sku.loc[sku]
        on_hand = int(record["on_hand_qty"])
        inventory_min = int(record["inventory_min"])
        monthly_demand = float(record["forecast_q50"])
        shelf_life = int(part["shelf_life_days"])
        confidence = float(record["confidence_final"])

        applicable = candidate_offers(sku, city, offers, coverage, suppliers)
        order_cost = planning_order_cost(applicable)
        lot = replenishment_level(
            monthly_demand, inventory_min, float(part["unit_cost_usd"]), order_cost
        )

        inventory_max = lot["level"]
        target = lot["level"]
        shelf_limit = consumable_within_shelf_life(monthly_demand, shelf_life, on_hand)
        max_allowed = min(inventory_max - on_hand, shelf_limit)
        need = max(0, inventory_min - on_hand)
        desired = max(0, min(target - on_hand, max_allowed))

        decision = DECISION_HOLD
        quantity = 0
        chosen = None
        total_cost = 0.0
        coverage_months = 0.0

        smallest_moq = 0 if applicable.empty else int(applicable["moq"].min())

        if need == 0:
            reason = REASON_ABOVE_MINIMUM
        elif applicable.empty:
            reason = REASON_NO_SUPPLIER
        elif shelf_limit < smallest_moq:
            reason = (
                f"{REASON_SHELF_LIFE_BLOCK}. With a shelf life of {shelf_life} days only "
                f"{shelf_limit} units would be consumed, and the smallest minimum order "
                f"quantity is {smallest_moq}"
            )
        elif smallest_moq > max_allowed:
            solution = solve_single_purchase(need, smallest_moq, applicable)
            if solution["quantity"] > 0:
                chosen = solution["offer"]
                quantity = solution["quantity"]
                total_cost = solution["total_cost"]
                decision = DECISION_REVIEW
                months = quantity / monthly_demand if monthly_demand > 0 else 0
                coverage_months = round(months, 1)
                reason = (
                    f"The minimum order quantity at {chosen['name']} is "
                    f"{int(chosen['moq'])} units and the allowed maximum is {max_allowed}. "
                    f"Buying the minimum costs {total_cost:.2f} USD and leaves "
                    f"{months:.1f} months of stock: the buyer has to decide"
                )
            else:
                reason = REASON_INFEASIBLE
        else:
            solution = solve_single_purchase(
                max(desired, need), max(max_allowed, desired, need), applicable
            )
            if solution["quantity"] > 0:
                decision = DECISION_BUY
                quantity = solution["quantity"]
                chosen = solution["offer"]
                total_cost = solution["total_cost"]
                months = quantity / monthly_demand if monthly_demand > 0 else 0
                coverage_months = round(months, 1)
                reason = (
                    f"{on_hand} units left against a minimum of {inventory_min}. With a "
                    f"forecast demand of {monthly_demand:.1f} per month, the economic "
                    f"order quantity of {lot['eoq_units']} units brings stock up to "
                    f"{target}, about {months:.1f} months of consumption. "
                    f"{chosen['name']} was chosen on lowest total cost among "
                    f"{len(applicable)} offers that serve {city}"
                )
            else:
                reason = REASON_INFEASIBLE

        exposure = stockout_cost(
            on_hand,
            monthly_demand,
            float(record["lead_time_days"]),
            part["criticality"],
            float(record.get("issue_rate", 1.0) or 1.0),
        )
        net_benefit = round(exposure - total_cost, 2)

        if decision == DECISION_BUY and net_benefit <= 0:
            decision = DECISION_HOLD
            reason = (
                f"{REASON_NOT_WORTH_IT}. Replenishing costs {total_cost:.2f} USD and the "
                f"stockout it prevents is valued at {exposure:.2f} USD on a criticality "
                f"{part['criticality']} part"
            )
            quantity = 0
            chosen = None
            total_cost = 0.0
            coverage_months = 0.0
            net_benefit = round(exposure, 2)

        needs_review = int(record["needs_review"])
        if decision == DECISION_REVIEW:
            needs_review = 1
        if decision == DECISION_BUY and confidence < 0.5:
            needs_review = 1
            reason = f"{reason}. {REASON_LOW_CONFIDENCE}"

        rows.append(
            {
                "sku_id": sku,
                "city_id": city,
                "description": part["description"],
                "criticality": part["criticality"],
                "on_hand_qty": on_hand,
                "inventory_min": inventory_min,
                "inventory_max": inventory_max,
                "demand_monthly": round(monthly_demand, 2),
                "forecast_source": record.get("forecast_source", "estadistico"),
                "shelf_life_days": shelf_life,
                "order_cost_usd": lot["order_cost_usd"],
                "holding_cost_usd": lot["holding_cost_usd"],
                "eoq_units": lot["eoq_units"],
                "target_qty": target,
                "max_allowed_qty": max(0, max_allowed),
                "coverage_months": coverage_months,
                "decision": decision,
                "recommended_qty": quantity,
                "supplier_id": None if chosen is None else chosen["supplier_id"],
                "supplier_name": None if chosen is None else chosen["name"],
                "unit_price_usd": None if chosen is None else chosen["unit_price_usd"],
                "freight_cost_usd": None if chosen is None else chosen["freight_cost_usd"],
                "lead_time_days": None if chosen is None else round(chosen["lead_time_days"], 1),
                "total_cost_usd": total_cost,
                "alternatives_evaluated": len(applicable),
                "confidence": confidence,
                "stockout_cost_usd": exposure,
                "net_benefit_usd": net_benefit,
                "needs_review": needs_review,
                "reason": reason,
            }
        )

    return apply_budget(pd.DataFrame(rows, columns=COLUMNS), budget, overrun_max)
