"""Punto de entrada para proyectar la demanda del dataset MVP.

Funcionalidad:
    Lee el historico, la clasificacion de patrones, el maestro de piezas y los
    proveedores, proyecta cada serie con el metodo que le corresponde y publica
    la demanda esperada durante el tiempo de entrega junto con el inventario
    minimo resultante.

    Uso: python -m app.services.build_forecast
"""

import pandas as pd

from app.core.dataset import OUT_DIR
from app.core.forecast import build_demand_forecast
from app.services.model_registry import (
    blend_forecasts,
    load_trained_model,
    model_projection,
)

OUTPUT_NAME = "demand_forecast.csv"

REQUIRED = [
    "demand_history.csv",
    "demand_patterns.csv",
    "parts_master.csv",
    "suppliers.csv",
]


def main() -> None:
    """Proyecta la demanda y publica el resultado.

    Entrada:
        Ninguna. Requiere el dataset y los patrones ya generados.

    Salida:
        Ninguna. Escribe demand_forecast.csv e imprime el resumen.

    Funcionalidad:
        Aborta indicando que comandos ejecutar si falta alguna entrada, y al
        terminar resume la proyeccion por metodo, el error de validacion y las
        piezas que quedan por debajo de su inventario minimo.
    """
    missing = [name for name in REQUIRED if not (OUT_DIR / name).exists()]
    if missing:
        raise SystemExit(
            "Faltan archivos: " + ", ".join(missing) + "\nCorre antes:\n"
            "  python -m app.services.build_dataset\n"
            "  python -m app.services.build_patterns"
        )

    tables = {name: pd.read_csv(OUT_DIR / name) for name in REQUIRED}
    forecast = build_demand_forecast(
        tables["demand_history.csv"],
        tables["demand_patterns.csv"],
        tables["parts_master.csv"],
        tables["suppliers.csv"],
    )
    model, run_id = load_trained_model()
    if model is not None:
        projected = model_projection(
            tables["demand_history.csv"], tables["parts_master.csv"], model
        )
        forecast = blend_forecasts(forecast, projected)
        forecast = build_demand_forecast(
            tables["demand_history.csv"],
            tables["demand_patterns.csv"],
            tables["parts_master.csv"],
            tables["suppliers.csv"],
            override_demand=forecast[
                [
                    "sku_id",
                    "city_id",
                    "forecast_q50",
                    "forecast_q25",
                    "forecast_q75",
                    "forecast_model",
                    "forecast_source",
                ]
            ],
        )
        print(f"Modelo aplicado: run {run_id}\n")
    else:
        print("Sin modelo entrenado: se usa solo la proyeccion estadistica.")
        print("Corre 'python -m app.services.train_model' para incorporarlo.\n")

    forecast.to_csv(OUT_DIR / OUTPUT_NAME, index=False)

    print(f"Proyeccion generada en {OUT_DIR / OUTPUT_NAME}")
    print(f"  {len(forecast)} series proyectadas")
    print(f"  tiempo de entrega de planificacion: {forecast['lead_time_days'].iloc[0]} dias\n")

    print("Metodo aplicado:")
    for method, count in forecast["method"].value_counts().items():
        print(f"  {method:<20} {count:>3} series")

    measured = forecast["wmape_backtest"].dropna()
    if len(measured):
        print("\nError de validacion retrospectiva (menor es mejor):")
        print(f"  mediano: {measured.median():.1%}")
        print(f"  mejor:   {measured.min():.1%}")
        print(f"  peor:    {measured.max():.1%}")

    print("\nConfianza final:")
    print(f"  promedio: {forecast['confidence_final'].mean():.2f}")
    print(f"  series marcadas para revision humana: {int(forecast['needs_review'].sum())}")

    inventory = pd.read_csv(OUT_DIR / "inventory_current.csv")
    merged = inventory.merge(forecast, on=["sku_id", "city_id"])
    shortage = merged[merged["on_hand_qty"] < merged["inventory_min"]]
    print(
        f"\n{len(shortage)} de {len(merged)} combinaciones estan por debajo "
        f"del inventario minimo calculado:"
    )
    columns = [
        "sku_id",
        "city_id",
        "on_hand_qty",
        "inventory_min",
        "demand_lead_time",
        "safety_stock",
        "confidence_final",
    ]
    print(shortage.nsmallest(8, "on_hand_qty")[columns].to_string(index=False))


if __name__ == "__main__":
    main()
