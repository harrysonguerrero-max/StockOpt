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
"""

from app.core.optimization import DECISION_BUY, DECISION_REVIEW

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
        return "alta"
    if confidence >= CONFIDENCE_LOW:
        return "media"
    return "baja"


def build_assumptions(record: dict) -> list:
    """Enumera los supuestos bajo los que se emitio la recomendacion.

    Entrada:
        record: diccionario con los campos de una recomendacion.

    Salida:
        Lista de cadenas, cada una con un supuesto explicito.

    Funcionalidad:
        Hace visible lo que el sistema dio por sentado: el patron de demanda
        detectado, la confianza de la proyeccion, el plazo de entrega asumido y
        el margen de vida util. Son los mismos puntos que el spec exige
        comunicar y los que despues debera cubrir la version con modelo de
        lenguaje.
    """
    assumptions = [
        f"Demanda proyectada de {record['demand_monthly']:.1f} unidades al mes, "
        f"con patron {record['pattern'].lower()}",
        f"Confianza {confidence_label(record['confidence'])} "
        f"({record['confidence']:.2f}) en la proyeccion",
    ]

    if record.get("lead_time_days"):
        assumptions.append(
            f"Plazo de entrega asumido de {record['lead_time_days']:.1f} dias"
        )

    assumptions.append(
        f"Vida util de {record['shelf_life_days']} dias: admite hasta "
        f"{record['max_allowed_qty']} unidades sin riesgo de obsolescencia"
    )

    alternatives = record.get("alternatives") or []
    if len(alternatives) > 1:
        rejected = [item for item in alternatives if not item["chosen"]]
        chosen = next((item for item in alternatives if item["chosen"]), None)
        if chosen and rejected:
            nearest = rejected[0]
            gap = nearest["total_cost_usd"] - chosen["total_cost_usd"]
            assumptions.append(
                f"Se evaluaron {len(alternatives)} proveedores que surten esta "
                f"ciudad. El siguiente en costo es {nearest['supplier_name']}, "
                f"{gap:.2f} USD mas caro"
            )
        else:
            cheapest = alternatives[0]
            assumptions.append(
                f"Se evaluaron {len(alternatives)} proveedores que surten esta "
                f"ciudad. Si hubiera que reponer, el mas conveniente seria "
                f"{cheapest['supplier_name']} a {cheapest['unit_price_usd']:.2f} "
                f"USD por unidad"
            )
    elif record["alternatives_evaluated"]:
        assumptions.append(
            f"Unico proveedor disponible para esta pieza en esta ciudad"
        )
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
        obliga a decidir a una persona. Una no compra dice por que no hace falta
        actuar. Esta es la funcion que reemplazara el modelo de lenguaje.
    """
    decision = record["decision"]
    sku = record["sku_id"]
    city = record["city_name"]

    if decision == DECISION_BUY:
        headline = (
            f"Comprar {record['recommended_qty']} unidades a "
            f"{record['supplier_name']} por {record['total_cost_usd']:.2f} USD"
        )
        body = (
            f"En {city} quedan {record['on_hand_qty']} unidades de {sku} y el "
            f"minimo operativo es {record['inventory_min']}. Con la demanda "
            f"proyectada, esas existencias no cubren los {record['lead_time_days']:.1f} "
            f"dias que tarda la reposicion, asi que se recomienda reponer ahora. "
            f"Entre las {record['alternatives_evaluated']} opciones que surten "
            f"{city}, {record['supplier_name']} resulta la mas economica "
            f"considerando precio unitario y flete."
        )
    elif decision == DECISION_REVIEW:
        missing = max(0, record["inventory_min"] - record["on_hand_qty"])
        headline = (
            f"No se recomienda comprar {record['recommended_qty']} unidades: "
            f"es el lote minimo de {record['supplier_name']}"
        )
        body = (
            f"En {city} quedan {record['on_hand_qty']} unidades de {sku} y el "
            f"minimo operativo es {record['inventory_min']}, asi que "
            f"{'falta ' + str(missing) + ' unidad' + ('es' if missing != 1 else '') if missing else 'no falta nada'} "
            f"para cubrirlo. El problema es que {record['supplier_name']} no vende "
            f"menos de {record['recommended_qty']} unidades, y en bodega solo caben "
            f"{record['inventory_max']}. Aceptar ese lote cuesta "
            f"{record['total_cost_usd']:.2f} USD y deja "
            f"{record['coverage_months']} meses de inventario. La cifra que ves no "
            f"es una recomendacion del sistema sino la condicion del proveedor: "
            f"decide si prefieres el exceso de existencias o quedarte sin la pieza."
        )
    else:
        headline = "Sin accion requerida"
        body = (
            f"En {city} hay {record['on_hand_qty']} unidades de {sku} frente a un "
            f"minimo de {record['inventory_min']}. {record['reason']}."
        )

    return {
        "headline": headline,
        "body": body,
        "assumptions": build_assumptions(record),
    }
