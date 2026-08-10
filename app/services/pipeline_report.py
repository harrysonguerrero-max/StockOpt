"""Informe del recorrido del pipeline.

Funcionalidad:
    Reune lo que dejo cada etapa en disco, lo resume y publica el resultado como
    un documento y un juego de graficas que la interfaz sirve tal cual.

    No ejecuta ninguna etapa ni recalcula nada: lee los archivos que ya
    existen. Por eso el informe se genera en segundos y nunca puede contradecir
    a las recomendaciones que el comprador tiene delante, que es el riesgo de
    volver a calcular por separado lo mismo.

    La lectura de las tablas se apoya en el explorador de datos, que ya las
    cachea, en lugar de mantener una segunda copia en memoria.
"""

import json

from app.core import pipeline, training
from app.core.dataset import OUT_DIR
from app.services.charts import build_pipeline_charts
from app.services.data_views import json_safe_record, load_table

QUALITY_DIR = OUT_DIR / "quality"
QUALITY_FILE = "data_quality_report.json"

DATASET_TABLES = {
    "parts_master": "parts_master.csv",
    "cities": "cities.csv",
    "inventory_current": "inventory_current.csv",
    "demand_history": "demand_history.csv",
    "suppliers": "suppliers.csv",
    "supplier_offers": "supplier_offers.csv",
    "supplier_coverage": "supplier_coverage.csv",
}

PATTERNS_TABLE = "demand_patterns.csv"
FORECAST_TABLE = "demand_forecast.csv"
RECOMMENDATIONS_TABLE = "purchase_recommendations.csv"


def quality_report_path():
    """Devuelve la ruta del informe de calidad de la etapa de limpieza.

    Entrada:
        Ninguna.

    Salida:
        Ruta del archivo JSON escrito por el perfilado.

    Funcionalidad:
        Centraliza la ubicacion para que la comprobacion de existencia y la
        lectura no la compongan por separado.
    """
    return QUALITY_DIR / QUALITY_FILE


def summary_path():
    """Devuelve la ruta del informe de pipeline publicado.

    Entrada:
        Ninguna.

    Salida:
        Ruta del archivo JSON con el recorrido completo.

    Funcionalidad:
        La interfaz lee este archivo en lugar de recalcular el resumen en cada
        peticion.
    """
    return pipeline.ARTIFACT_DIR / pipeline.SUMMARY_FILE


def report_is_available() -> bool:
    """Indica si el informe de pipeline ya se genero.

    Entrada:
        Ninguna.

    Salida:
        True si el archivo del informe existe.

    Funcionalidad:
        Permite que la interfaz explique que falta correr el informe en lugar de
        fallar con un error tecnico.
    """
    return summary_path().exists()


def load_quality_report() -> dict:
    """Lee el informe de calidad de las fuentes crudas.

    Entrada:
        Ninguna.

    Salida:
        Diccionario con las claves antes, despues y limpieza. Vacio si el
        perfilado aun no se ha corrido.

    Funcionalidad:
        Devolver un diccionario vacio en lugar de fallar deja que el informe se
        genere igual, con la etapa de limpieza sin detalle, cuando alguien
        construyo el dataset sin perfilar primero.
    """
    path = quality_report_path()
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_training_metrics() -> dict:
    """Lee las metricas del ultimo entrenamiento.

    Entrada:
        Ninguna.

    Salida:
        Diccionario con metricas, referencias, variables e importancia. Vacio si
        el modelo aun no se ha entrenado.

    Funcionalidad:
        Igual que con el informe de calidad, la ausencia no bloquea: el recorrido
        se publica con la etapa de modelo sin cifras.
    """
    path = training.ARTIFACT_DIR / training.METRICS_FILE
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_dataset_tables(refresh: bool = False) -> dict:
    """Carga las tablas del dataset relacional.

    Entrada:
        refresh: fuerza releer desde disco.

    Salida:
        Diccionario de DataFrames indexado por nombre corto de tabla.

    Funcionalidad:
        Reutiliza el cache del explorador de datos, de modo que abrir el
        explorador y abrir el recorrido del pipeline no lean dos veces los
        mismos archivos.
    """
    return {
        name: load_table(filename, refresh=refresh) for name, filename in DATASET_TABLES.items()
    }


def build_stages(refresh: bool = False) -> list:
    """Compone el recorrido del pipeline a partir de lo que hay en disco.

    Entrada:
        refresh: fuerza releer las tablas.

    Salida:
        Lista de resumenes de etapa.

    Funcionalidad:
        Es el punto donde la capa de servicios reune los insumos y el dominio
        hace el resumen. Separarlo asi es lo que permite probar los resumenes sin
        tocar el disco.
    """
    return pipeline.build_stages(
        quality_report=load_quality_report(),
        tables=load_dataset_tables(refresh=refresh),
        patterns=load_table(PATTERNS_TABLE, refresh=refresh),
        training_metrics=load_training_metrics(),
        recommendations=load_table(RECOMMENDATIONS_TABLE, refresh=refresh),
    )


def publish_report() -> dict:
    """Genera y publica el informe completo del pipeline.

    Entrada:
        Ninguna.

    Salida:
        Diccionario con las etapas y la ruta de cada grafica generada.

    Funcionalidad:
        Escribe el documento JSON y las imagenes en la carpeta de artefactos.
        Es lo unico que hay que volver a correr cuando se regenera el dataset o
        se reentrena el modelo.
    """
    stages = build_stages(refresh=True)
    charts = build_pipeline_charts(stages)

    pipeline.ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    document = {"stages": stages, "charts": charts}
    summary_path().write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    return document


def load_report() -> dict:
    """Lee el informe de pipeline publicado.

    Entrada:
        Ninguna.

    Salida:
        Diccionario con las etapas y las graficas.

    Funcionalidad:
        La interfaz consume el informe ya calculado, de modo que abrir la
        pantalla no dispare la agregacion de cuarenta series ni la cotizacion de
        las ofertas de cada compra.
    """
    return json.loads(summary_path().read_text(encoding="utf-8"))


def chart_path(name: str):
    """Resuelve la ruta de una grafica del recorrido.

    Entrada:
        name: nombre logico de la grafica.

    Salida:
        Ruta del archivo de imagen, o None si el nombre no esta declarado.

    Funcionalidad:
        Solo resuelve nombres declarados en la configuracion, de modo que la
        ruta no pueda usarse para leer archivos arbitrarios del disco.
    """
    filename = pipeline.CHART_FILES.get(name)
    if not filename:
        return None
    return pipeline.ARTIFACT_DIR / filename


def trace_part(sku_id: str, city_id: str) -> dict:
    """Sigue una pieza concreta por todas las etapas.

    Entrada:
        sku_id: identificador de la pieza.
        city_id: identificador de la ciudad.

    Salida:
        Diccionario con el recorrido de esa pieza, o None si la combinacion no
        existe.

    Funcionalidad:
        Se resuelve en vivo sobre las tablas cacheadas y no desde el informe
        publicado, porque el detalle de las cuarenta series no cabe en un
        documento que se lee entero en cada peticion.

        Las tres filas que vienen de una tabla se limpian antes de devolverlas:
        una recomendacion de no comprar deja vacios el proveedor y el precio, y
        esos nulos de pandas no se pueden serializar como JSON.
    """
    trace = pipeline.trace_part(
        sku_id=sku_id,
        city_id=city_id,
        demand=load_table(DATASET_TABLES["demand_history"]),
        patterns=load_table(PATTERNS_TABLE),
        forecast=load_table(FORECAST_TABLE),
        recommendations=load_table(RECOMMENDATIONS_TABLE),
        offers=load_table(DATASET_TABLES["supplier_offers"]),
        coverage=load_table(DATASET_TABLES["supplier_coverage"]),
        suppliers=load_table(DATASET_TABLES["suppliers"]),
    )
    if trace is None:
        return None

    for key in ("pattern", "forecast", "decision"):
        trace[key] = json_safe_record(trace[key])
    return trace
