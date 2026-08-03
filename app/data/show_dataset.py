"""Punto de entrada para inspeccionar el dataset MVP generado.

Funcionalidad:
    Imprime un resumen legible de todas las tablas publicadas: que se genero,
    que piezas necesitan compra, como se ve la demanda, quien puede surtir cada
    referencia y como quedo clasificado cada patron. Es de solo lectura.

    Uso: python -m app.data.show_dataset
"""

import pandas as pd

from app.core import dataset_config as config

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 30)

TABLES = [
    ("parts_master.csv", "MAESTRO DE PIEZAS"),
    ("inventory_current.csv", "INVENTARIO ACTUAL"),
    ("demand_history.csv", "DEMANDA HISTORICA"),
    ("suppliers.csv", "PROVEEDORES"),
    ("supplier_offers.csv", "CATALOGO PROVEEDOR-PIEZA"),
    ("cities.csv", "CIUDADES"),
    ("demand_patterns.csv", "PATRONES DE DEMANDA"),
]


def _rule(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def main() -> None:
    """Imprime el resumen del dataset publicado.

    Entrada:
        Ninguna. Lee los CSV de la carpeta de salida.

    Salida:
        Ninguna. Escribe el reporte por consola.

    Funcionalidad:
        Aborta indicando que comandos ejecutar si falta algun archivo, y en caso
        contrario recorre las tablas mostrando los datos mas relevantes para
        revisar el estado del dataset.
    """
    missing = [f for f, _ in TABLES if not (config.OUT_DIR / f).exists()]
    if missing:
        raise SystemExit(
            "Faltan archivos: " + ", ".join(missing)
            + "\nCorre primero:\n"
            "  python -m app.data.build_mvp_dataset\n"
            "  python -m app.data.build_patterns"
        )

    data = {f: pd.read_csv(config.OUT_DIR / f) for f, _ in TABLES}

    _rule("1. QUE SE GENERO")
    for filename, label in TABLES:
        df = data[filename]
        print(f"  {filename:<24} {len(df):>5} filas x {len(df.columns):>2} columnas   {label}")

    _rule("2. MAESTRO DE PIEZAS (primeras 8 de 20)")
    print(data["parts_master.csv"].head(8).to_string(index=False))

    _rule("3. INVENTARIO: QUE NECESITA COMPRA")
    inv = data["inventory_current.csv"]
    bajo = inv[inv.below_reorder == 1]
    print(f"  {len(bajo)} de {len(inv)} combinaciones pieza-ciudad estan bajo el punto de reorden\n")
    print(bajo.nsmallest(8, "on_hand_qty")[
        ["sku_id", "city_id", "on_hand_qty", "reorder_point", "reorder_qty", "stock_value_usd"]
    ].to_string(index=False))

    _rule("4. DEMANDA: ULTIMOS 6 MESES DE UNA PIEZA")
    dem = data["demand_history.csv"]
    sku = dem.sku_id.iloc[0]
    print(f"  Pieza {sku}, las 3 ciudades:\n")
    ultimos = sorted(dem.period_month.unique())[-6:]
    pivot = (dem[(dem.sku_id == sku) & (dem.period_month.isin(ultimos))]
             .pivot(index="period_month", columns="city_id", values="qty_issued"))
    print(pivot.to_string())

    _rule("5. PROVEEDORES Y SUS TIEMPOS DE ENTREGA")
    print(data["suppliers.csv"][
        ["supplier_id", "name", "city_id", "lead_time_avg_days",
         "lead_time_max_days", "lead_time_std_days"]
    ].to_string(index=False))

    _rule("6. OFERTAS: A QUIEN SE LE PUEDE COMPRAR UNA PIEZA")
    off = data["supplier_offers.csv"]
    print(f"  Ejemplo con {sku}:\n")
    print(off[off.sku_id == sku][
        ["supplier_id", "unit_price_usd", "moq", "capacity_per_month", "freight_cost_usd"]
    ].to_string(index=False))

    _rule("7. PATRONES DE DEMANDA (Etapa 1.3)")
    pat = data["demand_patterns.csv"]
    print("  Reparto:")
    for label, n in pat.pattern.value_counts().items():
        model = pat.loc[pat.pattern == label, "recommended_model"].iloc[0]
        print(f"    {label:<13} {n:>3} series ({n / len(pat):>5.1%})  -> {model}")
    print(f"\n  Confianza: media {pat.confidence.mean():.2f} | "
          f"min {pat.confidence.min():.2f} | max {pat.confidence.max():.2f}")

    revision = pat.nsmallest(5, "confidence")
    print("\n  Las 5 series con menos confianza (candidatas a revision humana):")
    print(revision[["sku_id", "city_id", "cv", "pattern", "confidence"]].to_string(index=False))

    _rule("8. TODO UNIDO: LO QUE VERA EL OPTIMIZADOR")
    full = (inv
            .merge(data["parts_master.csv"], on="sku_id")
            .merge(off, on="sku_id")
            .merge(data["suppliers.csv"], on="supplier_id", suffixes=("", "_sup"))
            .merge(pat, on=["sku_id", "city_id"]))
    print(f"  El join de las 6 tablas produce {len(full)} filas, "
          f"nulos: {int(full.isna().sum().sum())}\n")
    print(full[full.below_reorder == 1].head(6)[
        ["sku_id", "city_id", "criticality", "on_hand_qty", "reorder_point",
         "pattern", "confidence", "supplier_id", "unit_price_usd", "lead_time_avg_days"]
    ].to_string(index=False))
    print("\n  Cada fila ya tiene: que pieza, donde, cuanto queda, como se comporta")
    print("  su demanda, quien la vende, a que precio y en cuantos dias llega.")
    print()


if __name__ == "__main__":
    main()
