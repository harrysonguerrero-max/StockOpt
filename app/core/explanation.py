"""Redaccion de la justificacion de cada recomendacion.

Funcionalidad:
    Convierte una recomendacion estructurada en un texto que un comprador puede
    leer sin conocer el modelo por dentro: que se recomienda, con que evidencia,
    bajo que supuestos y con cuanta confianza.

    Este modulo es el punto donde mas adelante entrara un modelo de lenguaje.
    La etapa de explicacion con LLM esta pospuesta, de modo que por ahora el
    texto se compone de forma determinista a partir de los mismos campos que
    recibiria el modelo. La firma de `build_explanation` es la que consumira el
    LLM: recibe el registro completo de la recomendacion y devuelve el bloque de
    texto ya armado, asi que sustituir la implementacion no obliga a tocar ni la
    API ni la interfaz.

    Redactarlo primero de forma deterministica tiene una ventaja adicional: deja
    fijado que evidencia debe aparecer si o si en la explicacion, que es
    exactamente el contrato que despues hay que exigirle al modelo.

    El texto sale en ingles porque es lo que se ve en pantalla. Los codigos de
    decision siguen en español porque viajan en los CSV y en la base de estados,
    y traducirlos ahi obligaria a migrar dato ya guardado.
"""

from app.core.optimization import (
    DECISION_BUY,
    DECISION_DEFERRED,
    DECISION_ESCALATE,
    DECISION_REVIEW,
)

CONFIDENCE_HIGH = 0.75
CONFIDENCE_LOW = 0.50


def confidence_label(confidence: float) -> str:
    """Traduce el score de confianza a una etiqueta legible.

    Entrada:
        confidence: score entre 0 y 1.

    Salida:
        Cadena con el nivel de confianza en lenguaje corriente.

    Funcionalidad:
        Evita mostrar un numero suelto al comprador, que no tiene por que
        interpretar la escala.
    """
    if confidence >= CONFIDENCE_HIGH:
        return "high"
    if confidence >= CONFIDENCE_LOW:
        return "medium"
    return "low"


def build_assumptions(record: dict) -> list:
    """Enumera los supuestos bajo los que se emitio la recomendacion.

    Entrada:
        record: diccionario con los campos de una recomendacion.

    Salida:
        Lista de cadenas, cada una con un supuesto explicito.

    Funcionalidad:
        Hace visible lo que el sistema dio por sentado: el patron de demanda
        detectado, la confianza de la proyeccion, el plazo de entrega asumido,
        de donde sale la cantidad que se pide y el margen de vida util. Son los
        mismos puntos que el spec exige comunicar y los que despues debera
        cubrir la version con modelo de lenguaje.
    """
    assumptions = [
        (
            f"Forecast demand of {record['demand_monthly']:.1f} units per month, "
            f"{record['pattern'].lower()} pattern"
        ),
        (
            f"{confidence_label(record['confidence']).capitalize()} confidence "
            f"({record['confidence']:.2f}) in the forecast"
        ),
    ]

    if record.get("lead_time_days"):
        assumptions.append(f"Assumed lead time of {record['lead_time_days']:.1f} days")

    if record.get("eoq_units"):
        assumptions.append(
            f"Economic order quantity of {int(record['eoq_units'])} units, balancing "
            f"{record['order_cost_usd']:.2f} USD of freight per order against "
            f"{record['holding_cost_usd']:.2f} USD of holding cost per unit and year"
        )

    assumptions.append(
        f"Shelf life of {record['shelf_life_days']} days: allows up to "
        f"{record['max_allowed_qty']} units with no obsolescence risk"
    )

    alternatives = record.get("alternatives") or []
    if len(alternatives) > 1:
        rejected = [item for item in alternatives if not item["chosen"]]
        chosen = next((item for item in alternatives if item["chosen"]), None)
        if chosen and rejected:
            nearest = rejected[0]
            gap = nearest["total_cost_usd"] - chosen["total_cost_usd"]
            assumptions.append(
                f"{len(alternatives)} suppliers serving this city were evaluated. The "
                f"next cheapest is {nearest['supplier_name']}, {gap:.2f} USD more "
                f"expensive"
            )
        else:
            cheapest = alternatives[0]
            assumptions.append(
                f"{len(alternatives)} suppliers serving this city were evaluated. If a "
                f"replenishment were needed, the best option would be "
                f"{cheapest['supplier_name']} at {cheapest['unit_price_usd']:.2f} USD "
                f"per unit"
            )
    elif record["alternatives_evaluated"]:
        assumptions.append("Only one supplier available for this part in this city")
    return assumptions


def build_explanation(record: dict) -> dict:
    """Redacta la justificacion completa de una recomendacion.

    Entrada:
        record: diccionario con los campos de una recomendacion, tal como los
            entrega el optimizador enriquecidos con el patron de demanda.

    Salida:
        Diccionario con tres claves: headline, un resumen de una linea; body,
        el parrafo de justificacion; y assumptions, la lista de supuestos.

    Funcionalidad:
        Compone el texto segun la decision. Una compra explica el faltante, el
        proveedor elegido y el costo. Un caso en revision expone la tension que
        obliga a decidir a una persona. Una escalada dice cuanto dinero adicional
        hace falta para no arriesgar un paro de linea. Una no compra dice por que
        no hace falta actuar. Esta es la funcion que reemplazara el modelo de
        lenguaje.
    """
    decision = record["decision"]
    sku = record["sku_id"]
    city = record["city_name"]

    if decision == DECISION_BUY:
        headline = (
            f"Buy {record['recommended_qty']} units from "
            f"{record['supplier_name']} for {record['total_cost_usd']:.2f} USD"
        )
        body = (
            f"{city} holds {record['on_hand_qty']} units of {sku} against an operating "
            f"minimum of {record['inventory_min']}. At the forecast demand, that stock "
            f"does not cover the {record['lead_time_days']:.1f} days a replenishment "
            f"takes, so it is worth ordering now. Among the "
            f"{record['alternatives_evaluated']} offers that serve {city}, "
            f"{record['supplier_name']} is the cheapest once unit price and freight are "
            f"added together."
        )
        if record.get("stockout_cost_usd"):
            body += (
                f" The order prevents a stockout valued at "
                f"{record['stockout_cost_usd']:.2f} USD on a criticality "
                f"{record['criticality']} part, so it returns "
                f"{record['net_benefit_usd']:.2f} USD net."
            )
    elif decision == DECISION_ESCALATE:
        missing = max(0, record["inventory_min"] - record["on_hand_qty"])
        headline = (
            f"Management decision: {record['total_cost_usd']:.2f} USD are needed to "
            f"keep a criticality {record['criticality']} part in stock"
        )
        body = (
            f"{city} holds {record['on_hand_qty']} units of {sku} against a minimum of "
            f"{record['inventory_min']}, so {missing} are missing. This part stops a "
            f"line when it runs out, so the model funds it before anything "
            f"discretionary. It does not fit even after stretching the budget by the "
            f"authorised overrun. The replenishment itself is settled: "
            f"{record['recommended_qty']} units from {record['supplier_name']} for "
            f"{record['total_cost_usd']:.2f} USD, against a stockout valued at "
            f"{record['stockout_cost_usd']:.2f} USD. Approving the extra budget is a "
            f"management call, not one the optimiser can make on its own."
        )
    elif decision == DECISION_DEFERRED:
        missing = max(0, record["inventory_min"] - record["on_hand_qty"])
        headline = (
            f"Replenishment deferred: {record['total_cost_usd']:.2f} USD do not fit in "
            f"the discretionary budget"
        )
        body = (
            f"{city} holds {record['on_hand_qty']} units of {sku} against a minimum of "
            f"{record['inventory_min']}, so {missing} are missing. The replenishment is "
            f"technically correct: {record['recommended_qty']} units from "
            f"{record['supplier_name']} for {record['total_cost_usd']:.2f} USD. What is "
            f"missing is money. Production continuity is funded first, and what is left "
            f"goes further on other parts. Leaving it out exposes a stockout valued at "
            f"{record['stockout_cost_usd']:.2f} USD, so funding it would return "
            f"{record['net_benefit_usd']:.2f} USD net. That is the figure to take into "
            f"a budget request."
        )
    elif decision == DECISION_REVIEW:
        missing = max(0, record["inventory_min"] - record["on_hand_qty"])
        shortfall = (
            f"{missing} units are missing"
            if missing > 1
            else "1 unit is missing"
            if missing == 1
            else "nothing is missing"
        )
        headline = (
            f"Buying {record['recommended_qty']} units is not recommended: it is the "
            f"minimum order quantity at {record['supplier_name']}"
        )
        body = (
            f"{city} holds {record['on_hand_qty']} units of {sku} against an operating "
            f"minimum of {record['inventory_min']}, so {shortfall} to cover it. The "
            f"problem is that {record['supplier_name']} does not sell fewer than "
            f"{record['recommended_qty']} units, and the replenishment level for this "
            f"part is {record['inventory_max']}. Taking that lot costs "
            f"{record['total_cost_usd']:.2f} USD and leaves "
            f"{record['coverage_months']} months of stock. The figure you see is not a "
            f"recommendation from the system but the supplier's condition: decide "
            f"whether you prefer the excess stock or the risk of running out."
        )
    else:
        headline = "No action required"
        body = (
            f"{city} holds {record['on_hand_qty']} units of {sku} against a minimum of "
            f"{record['inventory_min']}. {record['reason']}."
        )

    return {
        "headline": headline,
        "body": body,
        "assumptions": build_assumptions(record),
    }
