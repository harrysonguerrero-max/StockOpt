"""Redaccion de la justificacion de compra con un modelo de lenguaje.

Funcionalidad:
    Convierte una recomendacion estructurada en una explicacion escrita para el
    comprador, usando Gemini a traves de BaseAgent del SDK de MLOps. El SDK se
    encarga del trazado en MLflow, del conteo de tokens y de la latencia sin que
    haya que instrumentar la llamada a mano.

    El agente no decide nada. Recibe la decision ya tomada por el optimizador y
    solo la redacta, con la instruccion explicita de no alterar ninguna cifra.
    Esa separacion es deliberada: si el modelo pudiera cambiar la cantidad o el
    proveedor, la recomendacion dejaria de ser auditable.

    Si no hay clave de API configurada, la funcion publica cae a la redaccion
    determinista de core.explanation, de modo que la interfaz siempre tiene
    un texto que mostrar.
"""

import os

from mlops_sdk import BaseAgent

from app.core.explanation import build_assumptions, build_explanation
from app.core.optimization import DECISION_HOLD

MODEL_NAME = "gemini-2.0-flash"
API_KEY_VARIABLE = "GEMINI_API_KEY"

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


def api_key_available() -> bool:
    """Indica si hay credencial configurada para el modelo.

    Entrada:
        Ninguna.

    Salida:
        True si la variable de entorno con la clave esta definida.

    Funcionalidad:
        Permite decidir entre la redaccion con modelo y la determinista sin
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


def explain_with_model(record: dict) -> dict:
    """Redacta la justificacion de una recomendacion con el modelo de lenguaje.

    Entrada:
        record: diccionario con los campos de una recomendacion.

    Salida:
        Diccionario con headline, body, assumptions y la clave source, que
        indica si el texto lo escribio el modelo o la plantilla determinista.

    Funcionalidad:
        Intenta la redaccion con Gemini y cae a la version determinista si no
        hay credencial o si la llamada falla. Los supuestos y el titular se
        conservan tal cual los calcula el sistema: el modelo solo reescribe el
        cuerpo, de modo que ninguna cifra dependa de el.
    """
    deterministic = build_explanation(record)
    if not api_key_available():
        return {**deterministic, "source": "plantilla"}

    try:
        agent = ExplanationAgent()
        payload = {key: record.get(key, "") for key in (
            "sku_id", "description", "criticality", "city_name", "on_hand_qty",
            "inventory_min", "inventory_max", "demand_monthly", "confidence",
            "decision", "recommended_qty", "supplier_name", "total_cost_usd",
            "lead_time_days", "alternatives_evaluated", "reason",
        )}
        payload["decision"] = payload["decision"] or DECISION_HOLD
        result = agent.execute(USER_TEMPLATE.format(**payload))
        text = (result or {}).get("answer", "").strip()
        if not text:
            return {**deterministic, "source": "plantilla"}
        return {
            "headline": deterministic["headline"],
            "body": text,
            "assumptions": build_assumptions(record),
            "source": "gemini",
            "trace_id": (result or {}).get("_trace_id"),
        }
    except Exception:
        return {**deterministic, "source": "plantilla"}
