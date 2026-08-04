"""Redaccion de la justificacion de compra con un modelo de lenguaje.

Funcionalidad:
    Convierte una recomendacion estructurada en una explicacion escrita para el
    comprador, usando Gemini a traves de BaseAgent del SDK de MLOps. El SDK se
    encarga del trazado en MLflow, del conteo de tokens y de la latencia.

    El agente no decide nada. Recibe la decision ya tomada por el optimizador y
    solo la redacta, con la instruccion explicita de no alterar ninguna cifra.
    Esa separacion es deliberada: si el modelo pudiera cambiar la cantidad o el
    proveedor, la recomendacion dejaria de ser auditable.

    La redaccion se pide una fila a la vez, cuando el comprador abre esa fila.
    Antes se generaban las cuarenta al construir la pantalla, lo que suponia
    cuarenta llamadas HTTP en serie por cada carga y por cada aprobacion, y la
    pantalla tardaba minutos en responder. Ahora la tabla se pinta al instante
    con la version deterministica y el modelo solo interviene en la fila que
    alguien esta mirando.

    Tres salvaguardas evitan que una falla del proveedor bloquee la interfaz: el
    agente se instancia una sola vez y se reutiliza, cada llamada tiene tiempo
    limite, y ante cualquier error se devuelve la redaccion deterministica.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from mlops_sdk import BaseAgent

from app.core.explanation import build_assumptions, build_explanation
from app.core.optimization import DECISION_HOLD

MODEL_NAME = "gemini-2.5-flash"
API_KEY_VARIABLE = "GEMINI_API_KEY"

REQUEST_TIMEOUT_SECONDS = 12

CACHE_LIMIT = 200

SYSTEM_PROMPT = """Eres analista de abastecimiento industrial. Redactas para un
comprador de planta que decide si aprueba una orden de compra de refacciones.

Reglas que no puedes romper:
- No cambies ninguna cifra. Las cantidades, precios, plazos y niveles de
  inventario que recibes son el resultado de un optimizador auditado.
- No propongas una decision distinta a la que recibes.
- Si la confianza de la proyeccion es baja, dilo de forma explicita.
- Escribe en espanol neutro, en dos o tres frases, sin vinetas ni encabezados.
- Habla de piezas, bodegas y proveedores, no de modelos ni de algoritmos.
"""

USER_TEMPLATE = """Redacta la justificacion de esta recomendacion.

Pieza: {sku_id} - {description}
Criticidad: {criticality}
Planta: {city_name}
Existencias actuales: {on_hand_qty} unidades
Inventario minimo: {inventory_min} unidades
Inventario maximo: {inventory_max} unidades
Demanda proyectada: {demand_monthly} unidades al mes
Confianza de la proyeccion: {confidence}
Decision del optimizador: {decision}
Cantidad recomendada: {recommended_qty} unidades
Proveedor elegido: {supplier_name}
Costo total: {total_cost_usd} USD
Plazo de entrega: {lead_time_days} dias
Proveedores evaluados: {alternatives_evaluated}
Motivo tecnico: {reason}
"""

PAYLOAD_FIELDS = (
    "sku_id", "description", "criticality", "city_name", "on_hand_qty",
    "inventory_min", "inventory_max", "demand_monthly", "confidence",
    "decision", "recommended_qty", "supplier_name", "total_cost_usd",
    "lead_time_days", "alternatives_evaluated", "reason",
)

_agent = None
_cache = {}
_executor = ThreadPoolExecutor(max_workers=2)


def api_key_available() -> bool:
    """Indica si hay credencial configurada para el modelo.

    Entrada:
        Ninguna.

    Salida:
        True si la variable de entorno con la clave esta definida.

    Funcionalidad:
        Permite decidir entre la redaccion con modelo y la deterministica sin
        provocar un error de autenticacion.
    """
    return bool(os.environ.get(API_KEY_VARIABLE))


class ExplanationAgent(BaseAgent):
    """Agente que redacta la justificacion de una recomendacion de compra.

    Funcionalidad:
        Llama a Gemini con la recomendacion ya resuelta y devuelve el texto junto
        con el consumo de tokens. Al heredar de BaseAgent, cada ejecucion queda
        trazada en MLflow con su latencia y su costo.
    """

    project = "stockopt-explicacion"
    llm_provider = "gemini"
    prompt_name = "stockopt_justificacion_compra"
    prompt_alias = "latest"

    def run(self, user_input: str, **kwargs) -> dict:
        """Genera la justificacion de una recomendacion.

        Entrada:
            user_input: bloque de datos de la recomendacion ya formateado.
            kwargs: parametros adicionales aceptados por el SDK.

        Salida:
            Diccionario con answer, tokens_input, tokens_output y tokens_total.

        Funcionalidad:
            Envia la instruccion de sistema y los datos de la recomendacion al
            modelo. Si el prompt esta publicado en el registro del SDK se usa
            ese; en caso contrario recurre al incluido en el codigo, para que el
            agente funcione tambien sin registro previo.
        """
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=os.environ[API_KEY_VARIABLE])
        instruction = getattr(self, "_current_prompt", None) or SYSTEM_PROMPT

        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=user_input,
            config=types.GenerateContentConfig(
                system_instruction=str(instruction),
                temperature=0.2,
                max_output_tokens=320,
            ),
        )

        usage = getattr(response, "usage_metadata", None)
        tokens_input = getattr(usage, "prompt_token_count", 0) or 0
        tokens_output = getattr(usage, "candidates_token_count", 0) or 0

        return {
            "answer": (response.text or "").strip(),
            "tokens_input": tokens_input,
            "tokens_output": tokens_output,
            "tokens_total": tokens_input + tokens_output,
        }


def _get_agent():
    """Devuelve el agente, creandolo la primera vez.

    Entrada:
        Ninguna.

    Salida:
        Instancia unica de ExplanationAgent, o None si no se pudo construir.

    Funcionalidad:
        Instanciar el agente carga el prompt desde el registro del SDK, lo que
        implica una llamada de red. Crear uno por fila multiplicaba esa espera
        por cuarenta y era la causa principal de que la pantalla se quedara
        cargando. Se construye una sola vez por proceso.
    """
    global _agent
    if _agent is None:
        try:
            _agent = ExplanationAgent()
        except Exception:
            return None
    return _agent


def _cache_key(record: dict) -> tuple:
    """Construye la llave de cache de una recomendacion.

    Entrada:
        record: diccionario con los campos de una recomendacion.

    Salida:
        Tupla que identifica la recomendacion y su contenido decisorio.

    Funcionalidad:
        Incluye la decision, la cantidad y el proveedor ademas de la pieza y la
        ciudad, de modo que el texto guardado se descarte cuando la recomendacion
        cambie de verdad y no en cada regeneracion del dataset.
    """
    return (
        record.get("sku_id"), record.get("city_id"), record.get("decision"),
        record.get("recommended_qty"), record.get("supplier_id"),
    )


def explain_with_model(record: dict, use_model: bool = True) -> dict:
    """Redacta la justificacion de una recomendacion.

    Entrada:
        record: diccionario con los campos de una recomendacion.
        use_model: si es falso devuelve directamente la version deterministica.

    Salida:
        Diccionario con headline, body, assumptions y source, que indica si el
        texto lo escribio el modelo o la plantilla.

    Funcionalidad:
        Devuelve la redaccion deterministica cuando no hay clave, cuando se pide
        expresamente o cuando el modelo falla o excede el tiempo limite. El
        titular y los supuestos siempre los calcula el sistema: el modelo solo
        reescribe el cuerpo, de modo que ninguna cifra dependa de el.
    """
    deterministic = build_explanation(record)
    if not use_model or not api_key_available():
        return {**deterministic, "source": "plantilla"}

    key = _cache_key(record)
    if key in _cache:
        return _cache[key]

    agent = _get_agent()
    if agent is None:
        return {**deterministic, "source": "plantilla"}

    try:
        payload = {field: record.get(field, "") for field in PAYLOAD_FIELDS}
        payload["decision"] = payload["decision"] or DECISION_HOLD
        future = _executor.submit(agent.execute, USER_TEMPLATE.format(**payload))
        result = future.result(timeout=REQUEST_TIMEOUT_SECONDS)
        text = (result or {}).get("answer", "").strip()
    except FutureTimeout:
        return {**deterministic, "source": "plantilla"}
    except Exception:
        return {**deterministic, "source": "plantilla"}

    if not text:
        return {**deterministic, "source": "plantilla"}

    explanation = {
        "headline": deterministic["headline"],
        "body": text,
        "assumptions": build_assumptions(record),
        "source": "gemini",
        "trace_id": (result or {}).get("_trace_id"),
    }

    if len(_cache) >= CACHE_LIMIT:
        _cache.clear()
    _cache[key] = explanation
    return explanation
