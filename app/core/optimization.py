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

SCENARIO_BUDGET_USD = None

SOLVER_TIME_LIMIT_SECONDS = 60

DECISION_BUY = "COMPRAR"
DECISION_HOLD = "NO_COMPRAR"
DECISION_REVIEW = "REVISAR"

REASON_ABOVE_MINIMUM = "Inventario por encima del minimo: no requiere reposicion"
REASON_SHELF_LIFE_BLOCK = "Vida util no permite consumir ni la cantidad minima de orden"
REASON_NO_SUPPLIER = "Ninguna oferta cumple las restricciones para esta ciudad"
REASON_INFEASIBLE = "El modelo no encontro solucion factible"
REASON_LOW_CONFIDENCE = "Confianza baja en la proyeccion: requiere validacion humana"


def _solver():
    """Devuelve el solver entero configurado.

    Entrada:
        Ninguna.

    Salida:
        Instancia de solver de PuLP lista para resolver el modelo.

    Funcionalidad:
        Prefiere COIN_CMD, que es la interfaz vigente hacia CBC, y recurre al
        comando historico cuando la instalacion no lo expone. CBC es suficiente
        para este problema: son 40 modelos de a lo sumo tres ofertas cada uno y
        se resuelven en milisegundos, sin necesidad de un solver comercial.
    """
    if "COIN_CMD" in pulp.listSolvers(onlyAvailable=True):
        return pulp.COIN_CMD(msg=0, timeLimit=SOLVER_TIME_LIMIT_SECONDS)
    return pulp.PULP_CBC_CMD(msg=0, timeLimit=SOLVER_TIME_LIMIT_SECONDS)


COLUMNS = [
    "sku_id", "city_id", "description", "criticality",
    "on_hand_qty", "inventory_min", "inventory_max",
    "demand_monthly", "forecast_source", "shelf_life_days",
    "target_qty", "max_allowed_qty", "coverage_months",
    "decision", "recommended_qty", "supplier_id", "supplier_name",
    "unit_price_usd", "freight_cost_usd", "lead_time_days",
    "total_cost_usd", "alternatives_evaluated", "confidence", "needs_review",
    "reason",
]


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
        bodega, porque el stock existente se consume primero. Se aplica un
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
                          coverage: pd.DataFrame, suppliers: pd.DataFrame) -> pd.DataFrame:
    """Genera la recomendacion de compra para todo el catalogo.

    Entrada:
        inventory: existencias actuales por pieza y ciudad.
        forecast: proyeccion de demanda con inventario minimo y confianza.
        parts: maestro de piezas.
        offers: catalogo de ofertas proveedor-pieza.
        coverage: cobertura geografica de los proveedores.
        suppliers: catalogo de proveedores.

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
            "needs_review": needs_review,
            "reason": reason,
        })

    return pd.DataFrame(rows, columns=COLUMNS)
