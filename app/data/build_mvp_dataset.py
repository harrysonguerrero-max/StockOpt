"""Construye el dataset MVP a partir de los CSV crudos de app/data/.

Los archivos crudos no se modifican. Uso:

    python -m app.data.build_mvp_dataset
"""

import numpy as np

from app.dataprep import config
from app.dataprep.builders import (
    build_cities,
    build_demand_history,
    build_inventory_current,
    build_parts_master,
    build_supplier_offers,
    build_suppliers,
    load_procurement,
    load_spine,
)
from app.dataprep.dictionary import write_data_dictionary
from app.dataprep.validate import validate

FILE_NAMES = {
    "cities": "cities.csv",
    "parts": "parts_master.csv",
    "inventory": "inventory_current.csv",
    "demand": "demand_history.csv",
    "suppliers": "suppliers.csv",
    "offers": "supplier_offers.csv",
}


def build_all() -> dict:
    rng = np.random.default_rng(config.SEED)
    spine = load_spine(config.RAW_DIR)
    procurement = load_procurement(config.RAW_DIR)

    parts = build_parts_master(spine)
    demand = build_demand_history(spine)
    suppliers = build_suppliers(procurement)

    return {
        "cities": build_cities(),
        "parts": parts,
        "demand": demand,
        "inventory": build_inventory_current(parts, demand, rng),
        "suppliers": suppliers,
        "offers": build_supplier_offers(parts, demand, suppliers, rng),
    }


def main() -> None:
    tables = build_all()
    warnings = validate(tables)

    config.OUT_DIR.mkdir(parents=True, exist_ok=True)
    for key, filename in FILE_NAMES.items():
        tables[key].to_csv(config.OUT_DIR / filename, index=False)
    write_data_dictionary(config.OUT_DIR)

    print(f"Dataset MVP generado en {config.OUT_DIR}")
    for key, filename in FILE_NAMES.items():
        print(f"  {filename:<24} {len(tables[key]):>5} filas")
    print("  data_dictionary.md")

    print("\nValidacion: sin errores criticos.")
    if warnings:
        print("Advertencias (no bloquean, requieren revision):")
        for w in warnings:
            print(f"  - {w}")


if __name__ == "__main__":
    main()
