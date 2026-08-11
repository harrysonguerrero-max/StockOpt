"""Endpoints de la interfaz de compras.

Funcionalidad:
    Expone la cola de recomendaciones, sus filtros y las acciones de aprobacion
    que ejecuta el comprador. La logica vive en la capa de servicios; aqui solo
    se validan las entradas y se traducen los errores a codigos HTTP.
"""

import csv
import io
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from app.core import training
from app.services import approvals as workflow
from app.services.approvals import audit_trail, update_state
from app.services.llm_agent import explain_with_model
from app.services.recommendations import (
    build_queue,
    build_summary,
    dataset_is_available,
    demand_series,
    filter_options,
    find_recommendation,
)

router = APIRouter()

EXPORT_COLUMNS = [
    "sku_id", "city_id", "description", "criticality", "decision", "state",
    "on_hand_qty", "inventory_min", "inventory_max", "recommended_qty",
    "supplier_id", "supplier_name", "unit_price_usd", "total_cost_usd",
    "lead_time_days", "confidence", "needs_review", "reason",
]


class StateChange(BaseModel):
    """Cuerpo de una peticion de cambio de estado.

    Funcionalidad:
        Recoge la decision del comprador sobre una recomendacion, junto con el
        motivo cuando rechaza y los datos de la orden cuando confirma.
    """

    sku_id: str
    city_id: str
    new_state: str
    updated_by: str = "comprador"
    rejection_reason: Optional[str] = None
    comment: Optional[str] = None
    purchase_order: Optional[str] = None
    expected_delivery: Optional[str] = None


@router.get("/health")
def health_check():
    """Comprueba que el servicio responde.

    Entrada:
        Ninguna.

    Salida:
        Diccionario con el estado del servicio y si el dataset esta disponible.

    Funcionalidad:
        Sirve para verificar el arranque y saber si hace falta correr el
        pipeline antes de usar la interfaz.
    """
    return {"status": "ok", "dataset_ready": dataset_is_available()}


@router.get("/recommendations")
def read_recommendations(refresh: bool = False):
    """Devuelve la cola completa de recomendaciones.

    Entrada:
        refresh: vuelve a leer los archivos del pipeline si es verdadero.

    Salida:
        Diccionario con el resumen, los filtros disponibles y la lista de items.

    Funcionalidad:
        Es la unica llamada que necesita la pantalla principal para pintarse.
    """
    if not dataset_is_available():
        raise HTTPException(
            status_code=503,
            detail="El dataset no esta generado. Corre el pipeline de app/data.",
        )
    queue = build_queue(refresh=refresh)
    return {
        "summary": build_summary(queue),
        "filters": filter_options(queue),
        "items": queue,
    }


@router.post("/recommendations/state")
def change_state(change: StateChange):
    """Aplica un cambio de estado sobre una recomendacion.

    Entrada:
        change: cuerpo con la pieza, la ciudad, el estado destino y el detalle.

    Salida:
        Diccionario con el estado anterior, el nuevo y la marca de tiempo.

    Funcionalidad:
        Delega la validacion de la transicion en la capa de servicios y traduce
        un movimiento invalido en un error 400 con el motivo explicito.
    """
    try:
        return update_state(
            sku_id=change.sku_id,
            city_id=change.city_id,
            new_state=change.new_state,
            updated_by=change.updated_by,
            rejection_reason=change.rejection_reason,
            comment=change.comment,
            purchase_order=change.purchase_order,
            expected_delivery=change.expected_delivery,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/recommendations/{sku_id}/{city_id}/explanation")
def read_explanation(sku_id: str, city_id: str):
    """Redacta la justificacion de una recomendacion con el modelo de lenguaje.

    Entrada:
        sku_id: identificador de la pieza.
        city_id: identificador de la ciudad.

    Salida:
        Diccionario con headline, body, assumptions y source, que indica si el
        texto lo escribio el modelo o la plantilla.

    Funcionalidad:
        Se invoca solo cuando el comprador abre una fila. Separar esta llamada
        del listado evita que cargar la pantalla dispare una peticion al modelo
        por cada una de las cuarenta filas, que era lo que dejaba la interfaz
        colgada. Si el modelo no responde a tiempo devuelve la version
        deterministica, de modo que la fila nunca se quede sin explicacion.
    """
    record = find_recommendation(sku_id, city_id)
    if record is None:
        raise HTTPException(
            status_code=404, detail=f"No existe la recomendacion {sku_id} / {city_id}"
        )
    return explain_with_model(record)


@router.get("/recommendations/{sku_id}/{city_id}/history")
def read_history(sku_id: str, city_id: str, months: int = 48):
    """Devuelve el consumo pasado y la proyeccion de una pieza en una ciudad.

    Entrada:
        sku_id: identificador de la pieza.
        city_id: identificador de la ciudad.
        months: cuantos meses de historia devolver.

    Salida:
        Diccionario con la serie mensual marcada por origen, la proyeccion con
        sus cuartiles y los parametros de la politica de inventario.

    Funcionalidad:
        Sostiene el primer paso de la narrativa de un caso. Sin la serie, la
        demanda mensual es un numero que hay que creer; con ella el comprador ve
        de donde sale y si el patron que declara el sistema se corresponde con
        lo que la planta consumio.
    """
    series = demand_series(sku_id, city_id, months=months)
    if series is None:
        raise HTTPException(
            status_code=404, detail=f"No hay historico de {sku_id} / {city_id}"
        )
    return series


@router.get("/recommendations/audit")
def read_audit(sku_id: Optional[str] = None, city_id: Optional[str] = None):
    """Devuelve el historial de decisiones.

    Entrada:
        sku_id: filtra por pieza si se indica.
        city_id: filtra por ciudad si se indica.

    Salida:
        Lista de movimientos con quien y cuando realizo cada cambio.

    Funcionalidad:
        Da soporte a la trazabilidad que exige la revision de negocio.
    """
    return {"entries": audit_trail(sku_id=sku_id, city_id=city_id)}


@router.get("/recommendations/export")
def export_recommendations():
    """Exporta la cola en formato CSV.

    Entrada:
        Ninguna.

    Salida:
        Respuesta de descarga con el archivo recomendaciones.csv.

    Funcionalidad:
        Permite llevar la tabla a una hoja de calculo o adjuntarla en un correo
        al proveedor sin salir de la interfaz.
    """
    if not dataset_is_available():
        raise HTTPException(status_code=503, detail="El dataset no esta generado.")

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=EXPORT_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for item in build_queue():
        writer.writerow(item)
    buffer.seek(0)

    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=recomendaciones.csv"},
    )


@router.get("/workflow/states")
def read_workflow():
    """Describe el flujo de estados de una compra.

    Entrada:
        Ninguna.

    Salida:
        Diccionario con los estados, las transiciones permitidas y los motivos
        de rechazo disponibles.

    Funcionalidad:
        Deja que la interfaz construya los controles sin duplicar las reglas del
        flujo en el frontend.
    """
    return {
        "states": workflow.WORKFLOW_STATES,
        "transitions": workflow.ALLOWED_TRANSITIONS,
        "rejection_reasons": workflow.REJECTION_REASONS,
    }


@router.get("/training/metrics")
def read_training_metrics():
    """Devuelve las metricas del ultimo entrenamiento.

    Entrada:
        Ninguna.

    Salida:
        Diccionario con las metricas, las referencias, la importancia de las
        variables y los nombres de las graficas disponibles.

    Funcionalidad:
        Permite que la interfaz muestre como se comporta el modelo sin tener que
        leer los archivos de artefactos por su cuenta.
    """
    import json

    path = training.ARTIFACT_DIR / training.METRICS_FILE
    if not path.exists():
        raise HTTPException(
            status_code=503,
            detail="Aun no se ha entrenado el modelo. Corre: python -m app.services.train_model",
        )
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/training/charts/{name}")
def read_training_chart(name: str):
    """Entrega una grafica del entrenamiento.

    Entrada:
        name: nombre logico de la grafica.

    Salida:
        La imagen solicitada.

    Funcionalidad:
        Solo sirve nombres declarados en la configuracion, de modo que la ruta
        no pueda usarse para leer archivos arbitrarios del disco.
    """
    filename = training.CHART_FILES.get(name)
    if not filename:
        raise HTTPException(status_code=404, detail=f"Grafica desconocida: {name}")
    path = training.ARTIFACT_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=503, detail="La grafica aun no se ha generado.")
    return FileResponse(path, media_type="image/png")
