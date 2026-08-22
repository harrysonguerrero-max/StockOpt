"""Punto de entrada para entrenar el modelo de proyeccion de demanda.

Funcionalidad:
    Construye las variables desde el historico, entrena el modelo global,
    compara su error contra las referencias, genera las graficas y publica todo
    en MLflow a traves del SDK de MLOps.

    Uso: python -m app.services.train_model
"""

import json

import pandas as pd
from mlops_sdk import MLObserver

from app.core import training
from app.core.dataset import OUT_DIR
from app.core.training import (
    DemandModel,
    build_features,
    feature_columns,
    moving_average_baseline,
    naive_baseline,
    naive_scale,
    permutation_importance,
    temporal_split,
)
from app.services.charts import build_all_charts

REQUIRED = ["demand_history.csv", "parts_master.csv"]


def main() -> None:
    """Entrena el modelo y publica metricas, graficas y artefactos.

    Entrada:
        Ninguna. Requiere el dataset ya generado.

    Salida:
        Ninguna. Escribe metricas, predicciones y graficas en la carpeta de
        artefactos e imprime el resumen del entrenamiento.

    Funcionalidad:
        Reserva los ultimos meses para validar, entrena sobre el resto y mide el
        error contra dos referencias. Registra el entrenamiento en MLflow y
        expone las metricas a Prometheus mediante el observador del SDK.
    """
    missing = [name for name in REQUIRED if not (OUT_DIR / name).exists()]
    if missing:
        raise SystemExit(
            "Faltan archivos: "
            + ", ".join(missing)
            + "\nCorre antes: python -m app.services.build_dataset"
        )

    demand = pd.read_csv(OUT_DIR / "demand_history.csv")
    parts = pd.read_csv(OUT_DIR / "parts_master.csv")

    frame = build_features(demand, parts)
    train, validation = temporal_split(frame, training.VALIDATION_MONTHS)
    columns = feature_columns(frame)

    baselines = {
        "ultimo_mes": naive_baseline(validation),
        "promedio_movil": moving_average_baseline(validation),
    }

    observer = MLObserver(project=training.PROJECT, version="v1", env="local")
    model = DemandModel(observer=observer)
    model.baselines = baselines
    model.scale = naive_scale(validation)

    run_id = model.fit_and_save(
        X={"train": train[columns], "val": validation[columns]},
        y={"train": train["qty_issued"], "val": validation["qty_issued"]},
        params=training.MODEL_PARAMS,
    )

    predicted = model.validation_predictions
    metrics = model.metrics

    importance = permutation_importance(model.model, validation[columns], validation["qty_issued"])
    charts = build_all_charts(metrics, baselines, validation, predicted, importance)

    training.ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_id,
        "project": training.PROJECT,
        "metrics": metrics,
        "baselines": baselines,
        "charts": {name: path.split("training")[-1].lstrip("\\/") for name, path in charts.items()},
        "features": columns,
        "importance": importance.to_dict(orient="records"),
        "n_series": int(frame.groupby(["sku_id", "city_id"]).ngroups),
        "train_months": min(train["period_month"].unique())
        + " a "
        + max(train["period_month"].unique()),
        "validation_months": min(validation["period_month"].unique())
        + " a "
        + max(validation["period_month"].unique()),
    }
    (training.ARTIFACT_DIR / training.METRICS_FILE).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    output = validation[["sku_id", "city_id", "period_month", "qty_issued"]].copy()
    output["prediccion"] = predicted
    output.to_csv(training.ARTIFACT_DIR / training.PREDICTIONS_FILE, index=False)

    print(f"Entrenamiento completado · run {run_id}")
    print(f"  series: {payload['n_series']} | variables: {len(columns)}")
    print(f"  entrenamiento: {payload['train_months']} ({metrics['n_train']} filas)")
    print(f"  validacion:    {payload['validation_months']} ({metrics['n_val']} filas)\n")

    print("Error en validacion:")
    print(
        f"  WMAPE {metrics['wmape']:.1%} | MAE {metrics['mae']:.2f} | "
        f"RMSE {metrics['rmse']:.2f} | sesgo {metrics['bias']:+.2f}"
    )

    print("\nComparacion contra referencias:")
    print(f"  {'modelo global':<22} WMAPE {metrics['wmape']:.1%}")
    for name, reference in baselines.items():
        gap = metrics.get(f"mejora_vs_{name}", 0)
        print(f"  {name:<22} WMAPE {reference['wmape']:.1%}   (el modelo mejora {gap:+.1%})")

    print("\nVariables mas influyentes:")
    for _, record in importance.head(5).iterrows():
        print(f"  {record['variable']:<22} {record['aporte']:+.4f}")

    print(f"\nGraficas en {training.ARTIFACT_DIR}")
    for name in charts:
        print(f"  {training.CHART_FILES[name]}")


if __name__ == "__main__":
    main()
