"""Orquestacion del dataset MVP.

Funcionalidad:
    Encadena la carga de fuentes crudas, la construccion de las tablas, la
    validacion y la publicacion en disco. Es el unico modulo del nucleo que
    escribe archivos; los demas solo transforman datos en memoria.
"""

import numpy as np

from app.core.dataset import (
    DEMAND_HORIZON,
    OUT_DIR,
    RAW_DIR,
    SEED,
    SYNTHETIC_EXTRA_YEARS,
    build_cities,
    build_demand_history,
    build_inventory_current,
    build_parts_master,
    build_supplier_coverage,
    build_supplier_offers,
    build_suppliers,
    load_procurement,
    load_spine,
    shift_demand_to_horizon,
)
from app.core.synthesis import extend_history
from app.core.validation import validate
from app.services.dictionary import write_data_dictionary

FILE_NAMES = {
    "cities": "cities.csv",
    "parts": "parts_master.csv",
    "inventory": "inventory_current.csv",
    "demand": "demand_history.csv",
    "suppliers": "suppliers.csv",
    "offers": "supplier_offers.csv",
    "coverage": "supplier_coverage.csv",
}


def build_all() -> dict:
    """Construye todas las tablas del dataset en memoria.

    Entrada:
        Ninguna. Lee los CSV crudos desde la carpeta de datos.

    Salida:
        Diccionario con las claves cities, parts, demand, inventory, suppliers,
        offers y coverage, cada una con su DataFrame.

    Funcionalidad:
        Genera las tablas en el orden de sus dependencias y comparte un unico
        generador aleatorio con semilla fija, de modo que dos ejecuciones
        producen exactamente el mismo resultado.

        La historia se amplia hacia atras con meses simulados para dar
        profundidad al entrenamiento. Quedan marcados con is_synthetic, de modo
        que cualquier medicion pueda restringirse al dato observado.
    """
    rng = np.random.default_rng(SEED)
    spine = load_spine(RAW_DIR)
    procurement = load_procurement(RAW_DIR)

    parts = build_parts_master(spine)
    demand = shift_demand_to_horizon(build_demand_history(spine), DEMAND_HORIZON)
    demand = extend_history(demand, SYNTHETIC_EXTRA_YEARS)
    suppliers = build_suppliers(procurement)

    return {
        "cities": build_cities(),
        "parts": parts,
        "demand": demand,
        "inventory": build_inventory_current(parts, demand, suppliers, rng),
        "suppliers": suppliers,
        "offers": build_supplier_offers(parts, demand, suppliers, rng),
        "coverage": build_supplier_coverage(suppliers),
    }


def publish(tables: dict) -> list:
    """Valida y escribe las tablas en la carpeta de salida.

    Entrada:
        tables: diccionario de DataFrames devuelto por build_all.

    Salida:
        Lista de advertencias emitidas por la validacion.

    Funcionalidad:
        Ejecuta la validacion antes de escribir, de modo que un dataset invalido
        nunca llegue a publicarse, y añade el diccionario de datos junto a los
        CSV.
    """
    warnings = validate(tables)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for key, filename in FILE_NAMES.items():
        tables[key].to_csv(OUT_DIR / filename, index=False)
    write_data_dictionary(OUT_DIR)
    return warnings
