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
"""

import math

import pandas as pd
import pulp

from app.core.inventory import DAYS_PER_MONTH

MAX_COVERAGE_MONTHS = 3
TARGET_COVERAGE_MONTHS = 1.5

SHELF_LIFE_SAFETY_RATIO = 0.80

SCENARIO_BUDGET_USD = 2500.0

STOCKOUT_COST_PER_DAY_USD = {"A": 400.0, "B": 80.0, "C": 10.0}

PLANNING_PERIOD_DAYS = 30

SOLVER_TIME_LIMIT_SECONDS = 60

DECISION_BUY = "COMPRAR"
DECISION_HOLD = "NO_COMPRAR"
DECISION_REVIEW = "REVISAR"
DECISION_DEFERRED = "APLAZADO"

REASON_ABOVE_MINIMUM = "Inventario por encima del minimo: no requiere reposicion"
REASON_SHELF_LIFE_BLOCK = "Vida util no permite consumir ni la cantidad minima de orden"
REASON_NO_SUPPLIER = "Ninguna oferta cumple las restricciones para esta ciudad"
REASON_INFEASIBLE = "El modelo no encontro solucion factible"
REASON_LOW_CONFIDENCE = "Confianza baja en la proyeccion: requiere validacion humana"
REASON_OVER_BUDGET = "No cabe en el presupuesto de la corrida"
REASON_NOT_WORTH_IT = "Reponer cuesta mas que el quiebre que evita"


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
    "sku_id", "city_id", "description", "criticality",
    "on_hand_qty", "inventory_min", "inventory_max",
    "demand_monthly", "forecast_source", "shelf_life_days",
    "target_qty", "max_allowed_qty", "coverage_months",
    "decision", "recommended_qty", "supplier_id", "supplier_name",
    "unit_price_usd", "freight_cost_usd", "lead_time_days",
    "total_cost_usd", "alternatives_evaluated", "confidence",
    "stockout_cost_usd", "net_benefit_usd", "needs_review", "reason",
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


def stockout_days_avoided(on_hand: int, monthly_demand: float,
                          lead_time_days: float) -> float:
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


def stockout_cost(on_hand: int, monthly_demand: float, lead_time_days: float,
                  criticality: str, issue_rate: float = 1.0) -> float:
    """Valora en dolares el quiebre que evita reponer ahora.

    Entrada:
        on_hand: unidades disponibles hoy.
        monthly_demand: demanda mensual proyectada.
        lead_time_days: plazo de reposicion en dias.
        criticality: criticidad A, B o C de la pieza.
        issue_rate: proporcion de dias en que la pieza se pide realmente.

    Salida:
        Costo esperado del quiebre en USD, o cero si no hay exposicion.

    Funcionalidad:
        Pone en la misma unidad las dos mitades de la decision. Hasta aqui el
        sistema minimizaba el costo de comprar sin saber nunca lo que cuesta no
        tener la pieza, asi que una pieza critica competia contra el flete en
        igualdad de condiciones. Con esto, la criticidad deja de mover solo el
        inventario minimo y entra en la funcion objetivo.

        No todos los dias sin existencias cuestan lo mismo. Un dia sin la pieza
        solo interrumpe algo si ese dia alguien la pide, y en refacciones eso
        ocurre en una minoria de los dias. Multiplicar por esa frecuencia es lo
        que separa el costo esperado del peor caso: sin ella la valoracion
        triplica el riesgo y produce cifras que nadie puede defender.

        El costo por dia es un parametro de negocio, no una estimacion del
        sistema: hay que validarlo con mantenimiento antes de darle poder sobre
        las compras, porque su magnitud decide por si sola cuanto pesa la
        criticidad frente al precio.

        Sigue siendo una cota superior. Supone que cada dia en que la pieza se
        pide y no esta, se pierde el dia entero, sin contar que en la practica se
        canibaliza de otra maquina o se expedita la orden.
    """
    per_day = STOCKOUT_COST_PER_DAY_USD.get(criticality, 0.0)
    frequency = min(1.0, max(0.0, issue_rate))
    return round(stockout_days_avoided(on_hand, monthly_demand, lead_time_days)
                 * frequency * per_day, 2)


def allocate_budget(candidates: list, budget) -> set:
    """Elige que compras entran en el presupuesto de la corrida.

    Entrada:
        candidates: lista de diccionarios con key, cost y benefit de cada compra
            que el optimizador recomienda.
        budget: tope de gasto en USD, o None para no aplicar limite.

    Salida:
        Conjunto de claves de las compras que se aprueban.

    Funcionalidad:
        Resuelve una mochila: maximiza el beneficio neto total, es decir el
        quiebre que se evita menos lo que cuesta evitarlo, sin pasar del
        presupuesto. No es lo mismo que ir aprobando de mayor beneficio a menor
        hasta agotar el dinero, porque una compra muy rentable y cara puede
        desplazar a varias algo menos rentables y baratas que juntas rinden mas.

        Es la primera restriccion del sistema que acopla las piezas entre si.
        Mientras cada pieza se resolvia por separado, el modelo entero no decidia
        nada que no resolviera ordenar las ofertas por precio; aqui si, porque la
        eleccion de que comprar depende de todo lo demas que compite por el mismo
        dinero.
    """
    if budget is None:
        return {candidate["key"] for candidate in candidates}

    affordable = [c for c in candidates if c["cost"] <= budget]
    if sum(c["cost"] for c in candidates) <= budget:
        return {candidate["key"] for candidate in candidates}

    problem = pulp.LpProblem("presupuesto", pulp.LpMaximize)
    switches = {
        candidate["key"]: problem.add_variable(f"buy_{index}", cat="Binary")
        for index, candidate in enumerate(affordable)
    }

    problem += pulp.lpSum([
        candidate["benefit"] * switches[candidate["key"]] for candidate in affordable
    ])
    problem += pulp.lpSum([
        candidate["cost"] * switches[candidate["key"]] for candidate in affordable
    ]) <= budget

    problem.solve(_solver())
    if pulp.LpStatus[problem.status] != "Optimal":
        return set()

    return {key for key, switch in switches.items() if round(switch.value() or 0) == 1}


def apply_budget(recommendations: pd.DataFrame, budget) -> pd.DataFrame:
    """Aplaza las compras que no caben en el presupuesto.

    Entrada:
        recommendations: tabla de decisiones ya resueltas por pieza.
        budget: tope de gasto en USD, o None para no aplicar limite.

    Salida:
        La misma tabla con las compras no financiadas marcadas como aplazadas.

    Funcionalidad:
        Solo compiten por el dinero las filas en COMPRAR. Las que quedan en
        revision no son gasto aprobado sino una decision pendiente de una
        persona, y descontarlas del presupuesto reservaria dinero para compras
        que quiza nunca se hagan.

        Las filas aplazadas conservan la cantidad, el proveedor y el costo. La
        recomendacion tecnica sigue siendo valida; lo que falta es el dinero, y
        el comprador necesita ver cuanto pediria para poder defender una
        ampliacion del presupuesto, junto con el quiebre que ese dinero evitaria.
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
        }
        for record in buying.to_dict(orient="records")
    ]
    approved = allocate_budget(candidates, budget)

    result = recommendations.copy()
    deferred = result.apply(
        lambda row: row["decision"] == DECISION_BUY
        and (row["sku_id"], row["city_id"]) not in approved,
        axis=1,
    )
    result.loc[deferred, "reason"] = result.loc[deferred].apply(
        lambda row: (
            f"{REASON_OVER_BUDGET}. Se necesitan {row['total_cost_usd']:.2f} USD y el "
            f"presupuesto de la corrida es {budget:.2f} USD, que rinde mas en otras "
            f"piezas. Aplazarla expone a un quiebre valorado en "
            f"{row['stockout_cost_usd']:.2f} USD"
        ),
        axis=1,
    )
    result.loc[deferred, "decision"] = DECISION_DEFERRED
    result.loc[deferred, "needs_review"] = 1
    return result


def consumable_within_shelf_life(monthly_demand: float, shelf_life_days: int,
                                 on_hand: int) -> int:
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
    return max(0, int(math.floor(daily_demand * usable_days)) - on_hand)


def target_inventory(monthly_demand: float, inventory_min: int) -> int:
    """Calcula el nivel hasta el que conviene reponer.

    Entrada:
        monthly_demand: demanda mensual proyectada por el modelo.
        inventory_min: inventario minimo de la pieza.

    Salida:
        Unidades objetivo tras la compra.

    Funcionalidad:
        Reponer justo hasta el minimo deja la pieza al borde del quiebre y obliga
        a comprar otra vez al mes siguiente, con su flete y su gestion. El
        objetivo suma al minimo la demanda proyectada de un periodo de
        cobertura, de modo que **la proyeccion determina cuanto se compra** y el
        lote minimo del proveedor solo actua como piso.
    """
    horizon = monthly_demand * TARGET_COVERAGE_MONTHS
    return max(inventory_min, int(math.ceil(inventory_min + horizon)))


def maximum_inventory(monthly_demand: float, inventory_min: int) -> int:
    """Calcula el techo de inventario de una pieza.

    Entrada:
        monthly_demand: demanda mensual proyectada.
        inventory_min: inventario minimo calculado para la pieza.

    Salida:
        Unidades maximas que se permite tener en bodega.

    Funcionalidad:
        Fija el techo como una cobertura objetivo en meses de demanda proyectada
        en lugar de un numero por pieza, de modo que escale solo cuando la
        demanda cambia. Nunca queda por debajo del minimo, ya que un maximo
        menor que el minimo dejaria el problema sin solucion.
    """
    coverage = monthly_demand * MAX_COVERAGE_MONTHS
    return max(inventory_min, int(math.ceil(coverage)))


def candidate_offers(sku: str, city: str, offers: pd.DataFrame,
                     coverage: pd.DataFrame, suppliers: pd.DataFrame) -> pd.DataFrame:
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
    active = suppliers[suppliers["active"]]
    result = (
        offers[offers["sku_id"] == sku]
        .merge(coverage[coverage["city_id"] == city], on="supplier_id")
        .merge(active[["supplier_id", "name", "lead_time_avg_days"]], on="supplier_id")
    )
    if result.empty:
        return result
    result["lead_time_days"] = result["lead_time_avg_days"] + result["lead_time_extra_days"]
    return result


def offer_costs(sku: str, city: str, quantity: int, offers: pd.DataFrame,
                coverage: pd.DataFrame, suppliers: pd.DataFrame,
                chosen_supplier=None) -> list:
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
        rows.append({
            "supplier_id": offer["supplier_id"],
            "supplier_name": offer["name"],
            "unit_price_usd": round(float(offer["unit_price_usd"]), 2),
            "moq": int(offer["moq"]),
            "freight_cost_usd": round(float(offer["freight_cost_usd"]), 2),
            "lead_time_days": round(float(offer["lead_time_days"]), 1),
            "units": units,
            "total_cost_usd": round(units * float(offer["unit_price_usd"])
                                    + float(offer["freight_cost_usd"]), 2),
            "chosen": offer["supplier_id"] == chosen_supplier,
        })

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

    problem += pulp.lpSum([
        offer["unit_price_usd"] * quantities[offer["offer_id"]]
        + offer["freight_cost_usd"] * switches[offer["offer_id"]]
        for _, offer in offers.iterrows()
    ])

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
        quantity = int(round(quantities[offer_id].value() or 0))
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


def build_recommendations(inventory: pd.DataFrame, forecast: pd.DataFrame,
                          parts: pd.DataFrame, offers: pd.DataFrame,
                          coverage: pd.DataFrame, suppliers: pd.DataFrame,
                          budget=SCENARIO_BUDGET_USD) -> pd.DataFrame:
    """Genera la recomendacion de compra para todo el catalogo.

    Entrada:
        inventory: existencias actuales por pieza y ciudad.
        forecast: proyeccion de demanda con inventario minimo y confianza.
        parts: maestro de piezas.
        offers: catalogo de ofertas proveedor-pieza.
        coverage: cobertura geografica de los proveedores.
        suppliers: catalogo de proveedores.
        budget: tope de gasto de la corrida en USD. None desactiva el limite.

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

        Al final se reparte el presupuesto de la corrida entre las compras que
        procedian. Es el unico paso que mira todas las piezas a la vez: hasta
        aqui cada decision era independiente de las demas.
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

        inventory_max = maximum_inventory(monthly_demand, inventory_min)
        shelf_limit = consumable_within_shelf_life(monthly_demand, shelf_life, on_hand)
        max_allowed = min(inventory_max - on_hand, shelf_limit)
        applicable = candidate_offers(sku, city, offers, coverage, suppliers)
        target = min(target_inventory(monthly_demand, inventory_min), inventory_max)
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
                f"{REASON_SHELF_LIFE_BLOCK}. Con vida util de {shelf_life} dias "
                f"solo se consumirian {shelf_limit} unidades, y el minimo de orden "
                f"es {smallest_moq}"
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
                    f"El minimo de orden de {chosen['name']} es {int(chosen['moq'])} "
                    f"unidades y el maximo permitido es {max_allowed}. Comprar el "
                    f"minimo cuesta {total_cost:.2f} USD y deja inventario para "
                    f"{months:.1f} meses: requiere decision del comprador"
                )
            else:
                reason = REASON_INFEASIBLE
        else:
            solution = solve_single_purchase(max(desired, need),
                                             max(max_allowed, desired, need), applicable)
            if solution["quantity"] > 0:
                decision = DECISION_BUY
                quantity = solution["quantity"]
                chosen = solution["offer"]
                total_cost = solution["total_cost"]
                months = quantity / monthly_demand if monthly_demand > 0 else 0
                coverage_months = round(months, 1)
                reason = (
                    f"Quedan {on_hand} unidades y el minimo es {inventory_min}. "
                    f"Con una demanda proyectada de {monthly_demand:.1f} al mes se "
                    f"repone hasta {target} unidades, equivalente a {months:.1f} "
                    f"meses de consumo. Se eligio {chosen['name']} por menor costo "
                    f"total entre {len(applicable)} opciones que surten {city}"
                )
            else:
                reason = REASON_INFEASIBLE

        exposure = stockout_cost(on_hand, monthly_demand,
                                 float(record["lead_time_days"]),
                                 part["criticality"],
                                 float(record.get("issue_rate", 1.0) or 1.0))
        net_benefit = round(exposure - total_cost, 2)

        if decision == DECISION_BUY and net_benefit <= 0:
            decision = DECISION_HOLD
            reason = (
                f"{REASON_NOT_WORTH_IT}. Reponer cuesta {total_cost:.2f} USD y el "
                f"quiebre que evita se valora en {exposure:.2f} USD para una pieza "
                f"de criticidad {part['criticality']}"
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

        rows.append({
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
        })

    return apply_budget(pd.DataFrame(rows, columns=COLUMNS), budget)
