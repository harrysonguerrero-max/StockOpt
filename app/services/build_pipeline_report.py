"""Punto de entrada para publicar el recorrido del pipeline.

Funcionalidad:
    Resume lo que hizo cada etapa y genera las graficas que la interfaz muestra
    en la pestaña de modelo.

    No ejecuta ninguna etapa: solo lee lo que las anteriores dejaron en disco.
    Hay que volver a correrlo cada vez que se regenera el dataset o se reentrena
    el modelo, o el recorrido quedara describiendo la corrida anterior.

    Uso: python -m app.services.build_pipeline_report
"""

from app.core import pipeline
from app.core.dataset import OUT_DIR
from app.services.pipeline_report import (
    DATASET_TABLES,
    PATTERNS_TABLE,
    RECOMMENDATIONS_TABLE,
    publish_report,
    quality_report_path,
)

REQUIRED = [*list(DATASET_TABLES.values()), PATTERNS_TABLE, RECOMMENDATIONS_TABLE]


def main() -> None:
    """Genera y publica el informe del recorrido del pipeline.

    Entrada:
        Ninguna. Requiere el dataset, los patrones y las recomendaciones ya
        generados.

    Salida:
        Ninguna. Escribe el informe y las graficas, e imprime un resumen de cada
        etapa.

    Funcionalidad:
        Aborta indicando que comandos ejecutar si falta alguna entrada, y avisa
        cuando el perfilado o el entrenamiento no se han corrido: el recorrido se
        publica igual, pero esas dos etapas apareceran sin cifras.
    """
    missing = [name for name in REQUIRED if not (OUT_DIR / name).exists()]
    if missing:
        raise SystemExit(
            "Faltan archivos: " + ", ".join(missing) + "\nCorre antes:\n"
            "  python -m app.services.build_dataset\n"
            "  python -m app.services.build_patterns\n"
            "  python -m app.services.build_forecast\n"
            "  python -m app.services.build_recommendations"
        )

    if not quality_report_path().exists():
        print("Aviso: sin informe de calidad. La etapa de limpieza ira vacia.")
        print("       Corre: python -m app.services.profile_data\n")

    document = publish_report()
    stages = document["stages"]

    print(f"Informe publicado en {pipeline.ARTIFACT_DIR}\n")

    for stage in stages:
        print(f"{stage['title']}")
        print(f"  entra: {stage['input']}")
        print(f"  sale:  {stage['output']}")

    cleaning, dataset, patterns, model, optimization = stages

    if cleaning["sources"]:
        print(
            f"\nLimpieza: de {cleaning['rows_before']:,} filas crudas quedan "
            f"{cleaning['rows_after']:,}, con {cleaning['adjusted']:,} filas "
            f"ajustadas sin descartar"
        )

    print(
        f"\nDataset: {dataset['months']} meses "
        f"({dataset['first_month']} a {dataset['last_month']}), "
        f"{dataset['series']} series, "
        f"{dataset['synthetic_rows']:,} filas simuladas de "
        f"{dataset['synthetic_rows'] + dataset['real_rows']:,}"
    )

    print(
        "\nPatrones: " + " · ".join(f"{count} {name}" for name, count in patterns["counts"].items())
    )

    if model["metrics"]:
        print(
            f"\nModelo: {len(model['features'])} variables en "
            f"{len(model['families'])} familias, "
            f"WMAPE {model['metrics']['wmape']:.1%}"
        )
    else:
        print("\nModelo: sin metricas. Corre: python -m app.services.train_model")

    print(
        "\nOptimizacion: "
        + " · ".join(f"{count} {decision}" for decision, count in optimization["counts"].items())
    )
    print(f"  ahorro frente a la peor oferta aplicable: {optimization['saving_usd']:,.2f} USD")

    print("\nGraficas generadas:")
    for name, path in document["charts"].items():
        print(f"  {name:<12} {path}")


if __name__ == "__main__":
    main()
