"""Punto de entrada para clasificar los patrones de demanda.

Funcionalidad:
    Lee el historico de demanda ya generado, clasifica cada serie y publica el
    resultado, informando el reparto por patron y las series que ameritan
    revision humana.

    Uso: python -m app.services.build_patterns
"""

import pandas as pd

from app.core import patterns as config
from app.core.dataset import CITY_IDS, OUT_DIR
from app.core.patterns import build_demand_patterns

OUTPUT_NAME = "demand_patterns.csv"


def main() -> None:
    """Clasifica las series de demanda y publica el resultado.

    Entrada:
        Ninguna. Requiere demand_history.csv en la carpeta de salida.

    Salida:
        Ninguna. Escribe demand_patterns.csv e imprime el resumen.

    Funcionalidad:
        Aborta con un mensaje claro si el historico no existe todavia, y al
        terminar lista las series de menor confianza para que el equipo decida
        si necesitan intervencion manual.
    """
    demand_path = OUT_DIR / "demand_history.csv"
    if not demand_path.exists():
        raise SystemExit(
            f"No existe {demand_path}. Corre antes: python -m app.services.build_dataset"
        )

    demand = pd.read_csv(demand_path)
    patterns = build_demand_patterns(demand)
    patterns.to_csv(OUT_DIR / OUTPUT_NAME, index=False)

    print(f"Patrones de demanda generados en {OUT_DIR / OUTPUT_NAME}")
    print(f"  {len(patterns)} series clasificadas\n")

    counts = patterns["pattern"].value_counts()
    print("Reparto por patron:")
    for label in config.PRECEDENCE:
        if label in counts:
            share = counts[label] / len(patterns)
            model = config.RECOMMENDED_MODEL[label]
            print(f"  {label:<14} {counts[label]:>3} series ({share:>5.1%})  -> {model}")

    print("\nConfianza:")
    print(f"  promedio: {patterns['confidence'].mean():.2f}")
    print(f"  minima:   {patterns['confidence'].min():.2f}")
    print(f"  maxima:   {patterns['confidence'].max():.2f}")

    low = patterns[patterns["confidence"] < 0.5]
    if len(low):
        print(f"\n{len(low)} series con confianza menor a 0.5 (revision humana sugerida):")
        for _, record in low.head(10).iterrows():
            print(f"  {record['sku_id']} / {record['city_id']}  "
                  f"{record['pattern']}  conf={record['confidence']}")


if __name__ == "__main__":
    main()
