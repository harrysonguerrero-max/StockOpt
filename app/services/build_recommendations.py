"""Punto de entrada para generar las recomendaciones de compra.

Funcionalidad:
    Cruza el inventario, la proyeccion de demanda y el catalogo de proveedores,
    resuelve el modelo de abastecimiento y publica la tabla de recomendaciones
    que revisa el comprador.

    Uso: python -m app.services.build_recommendations
"""

import pandas as pd

from app.core import optimization as config
from app.core.dataset import CITY_IDS, OUT_DIR
from app.core.optimization import build_recommendations

OUTPUT_NAME = "purchase_recommendations.csv"

REQUIRED = [
    "inventory_current.csv",
    "demand_forecast.csv",
    "parts_master.csv",
    "supplier_offers.csv",
    "supplier_coverage.csv",
    "suppliers.csv",
]


def main() -> None:
    """Genera y publica las recomendaciones de compra.

    Entrada:
        Ninguna. Requiere el dataset y la proyeccion ya generados.

    Salida:
        Ninguna. Escribe purchase_recommendations.csv e imprime el resumen.

    Funcionalidad:
        Aborta indicando que comandos ejecutar si falta alguna entrada, y al
        terminar resume cuantas piezas se recomienda comprar, cuanto suma la
        inversion, como se reparte entre proveedores y que casos quedan para
        revision humana.
    """
    missing = [name for name in REQUIRED if not (OUT_DIR / name).exists()]
    if missing:
        raise SystemExit(
            "Faltan archivos: " + ", ".join(missing) + "\nCorre antes:\n"
            "  python -m app.services.build_dataset\n"
            "  python -m app.services.build_patterns\n"
            "  python -m app.services.build_forecast"
        )

    tables = {name: pd.read_csv(OUT_DIR / name) for name in REQUIRED}
    recommendations = build_recommendations(
        tables["inventory_current.csv"],
        tables["demand_forecast.csv"],
        tables["parts_master.csv"],
        tables["supplier_offers.csv"],
        tables["supplier_coverage.csv"],
        tables["suppliers.csv"],
    )
    recommendations.to_csv(OUT_DIR / OUTPUT_NAME, index=False)

    buy = recommendations[recommendations["decision"] == config.DECISION_BUY]
    hold = recommendations[recommendations["decision"] == config.DECISION_HOLD]
    review = recommendations[recommendations["decision"] == config.DECISION_REVIEW]

    print(f"Recomendaciones generadas en {OUT_DIR / OUTPUT_NAME}")
    print(f"  {len(recommendations)} combinaciones evaluadas\n")
    print(f"  {config.DECISION_BUY:<12} {len(buy):>3}")
    print(f"  {config.DECISION_HOLD:<12} {len(hold):>3}")
    print(f"  {config.DECISION_REVIEW:<12} {len(review):>3}\n")

    if len(buy):
        print(f"Inversion total recomendada: {buy['total_cost_usd'].sum():,.2f} USD")
        print(f"Unidades totales: {int(buy['recommended_qty'].sum())}\n")
        print("Reparto por proveedor:")
        for supplier, group in buy.groupby("supplier_name"):
            print(f"  {supplier:<18} {len(group):>2} ordenes  "
                  f"{group['total_cost_usd'].sum():>10,.2f} USD")

    print("\nMotivos de no comprar:")
    for reason, count in hold["reason"].value_counts().items():
        print(f"  {count:>2}  {reason}")

    if len(review):
        print("\nCasos que requieren decision del comprador:")
        for _, record in review.head(4).iterrows():
            print(f"  {record['sku_id']}/{record['city_id']}: {record['reason']}")

    flagged = recommendations[recommendations["needs_review"] == 1]
    print(f"\n{len(flagged)} filas marcadas para revision humana")

    print("\nEjemplo de recomendaciones de compra:")
    columns = ["sku_id", "city_id", "on_hand_qty", "inventory_min",
               "recommended_qty", "supplier_id", "total_cost_usd", "lead_time_days"]
    print(buy.nlargest(8, "total_cost_usd")[columns].to_string(index=False))


if __name__ == "__main__":
    main()
