"""Script de perfilado y limpieza de las fuentes crudas.

Funcionalidad:
    Analiza los CSV de origen, aplica las reglas de limpieza y publica el
    informe de calidad junto con el reporte de meses de consumo atipico. Es el
    paso previo a construir el dataset y el que deja evidencia de que se hizo
    con los datos antes de modelar.

    Uso: python -m app.services.profile_data
"""

import json

import pandas as pd

from app.core.cleaning import (
    clean_procurement,
    clean_spine,
    demand_outlier_report,
    flag_sensor_outliers,
)
from app.core.dataset import OUT_DIR, RAW_DIR
from app.core.profiling import profile_dataset

REPORT_DIR = OUT_DIR / "quality"
REPORT_FILE = "data_quality_report.json"
OUTLIERS_FILE = "demand_outliers.csv"

SPINE_FILE = "synthetic_industrial_machine_data.csv"
PROCUREMENT_FILE = "Procurement KPI Analysis Dataset.csv"


def _print_log(title: str, log: list) -> None:
    """Imprime la bitacora de limpieza de una fuente.

    Entrada:
        title: nombre de la fuente.
        log: lista de reglas aplicadas.

    Salida:
        Ninguna. Escribe por consola.

    Funcionalidad:
        Presenta cada regla con su motivo y las filas afectadas, para que la
        limpieza sea revisable sin abrir el codigo.
    """
    print(f"\n{title}")
    for entry in log:
        marker = "  =" if entry["regla"] == "RESULTADO" else "  -"
        print(f"{marker} {entry['regla']}")
        print(f"      {entry['motivo']} ({entry['filas']} filas)")


def main() -> None:
    """Perfila, limpia y publica el informe de calidad.

    Entrada:
        Ninguna. Lee los CSV crudos.

    Salida:
        Ninguna. Escribe el informe y el reporte de atipicos, e imprime el
        resumen.

    Funcionalidad:
        Perfila antes y despues de limpiar, de modo que el informe muestre el
        efecto de cada regla. Los meses de consumo atipico se reportan pero no
        se corrigen: requieren confirmacion de mantenimiento.
    """
    spine_raw = pd.read_csv(RAW_DIR / SPINE_FILE)
    procurement_raw = pd.read_csv(RAW_DIR / PROCUREMENT_FILE)

    before = {
        "spine": profile_dataset(
            spine_raw, SPINE_FILE, keys=["transaction_date", "asset_tag", "part_no"]
        ),
        "procurement": profile_dataset(procurement_raw, PROCUREMENT_FILE, keys=["PO_ID"]),
    }

    print("=" * 74)
    print("PERFILADO DE FUENTES CRUDAS")
    print("=" * 74)
    for report in before.values():
        print(f"\n{report['name']}: {report['rows']} filas x {report['columns']} columnas")
        if report["flags"]:
            print("  Advertencias:")
            for flag in report["flags"]:
                print(f"    - {flag}")
        worst = sorted(report["outliers"].items(), key=lambda item: -item[1]["mad_outliers"])[:3]
        if worst:
            print("  Columnas con mas atipicos:")
            for column, stats in worst:
                print(f"    - {column}: {stats['mad_outliers']} por desviacion mediana")

    print("\n" + "=" * 74)
    print("LIMPIEZA")
    print("=" * 74)

    spine_clean, spine_log = clean_spine(spine_raw)
    spine_clean, sensor_log = flag_sensor_outliers(spine_clean)
    procurement_clean, procurement_log = clean_procurement(procurement_raw)

    _print_log(SPINE_FILE, spine_log + sensor_log)
    _print_log(PROCUREMENT_FILE, procurement_log)

    after = {
        "spine": profile_dataset(spine_clean, SPINE_FILE),
        "procurement": profile_dataset(procurement_clean, PROCUREMENT_FILE),
    }

    demand_path = OUT_DIR / "demand_history.csv"
    outliers = pd.DataFrame()
    if demand_path.exists():
        outliers = demand_outlier_report(pd.read_csv(demand_path))

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / REPORT_FILE).write_text(
        json.dumps(
            {
                "antes": before,
                "despues": after,
                "limpieza": {"spine": spine_log + sensor_log, "procurement": procurement_log},
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    if len(outliers):
        outliers.to_csv(REPORT_DIR / OUTLIERS_FILE, index=False)

    print("\n" + "=" * 74)
    print("RESULTADO")
    print("=" * 74)
    print(f"  informe de calidad: {REPORT_DIR / REPORT_FILE}")
    if len(outliers):
        print(f"  meses de consumo atipico: {len(outliers)} en {REPORT_DIR / OUTLIERS_FILE}")
        print("\n  Los 5 mas extremos (requieren confirmacion de mantenimiento):")
        columns = ["sku_id", "city_id", "period_month", "qty_issued", "ratio_vs_median"]
        print(outliers.nlargest(5, "ratio_vs_median")[columns].to_string(index=False))


if __name__ == "__main__":
    main()
