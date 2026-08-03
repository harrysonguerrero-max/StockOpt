"""Orquestacion del build completo del dataset MVP.

Funcionalidad:
    Encadena la carga de fuentes crudas, la construccion de las seis tablas, la
    validacion y la publicacion en disco. Es el unico punto donde se escribe;
    los servicios que invoca no tocan el sistema de archivos.
"""

import numpy as np
import pandas as pd

from app.core import dataset_config as config
from app.services.dataset_service import (
    build_cities,
    build_demand_history,
    build_inventory_current,
    build_parts_master,
    build_supplier_offers,
    build_suppliers,
    load_procurement,
    load_spine,
    shift_demand_to_horizon,
)
from app.services.dictionary_service import write_data_dictionary
from app.services.validation_service import validate

FILE_NAMES = {
    "cities": "cities.csv",
    "parts": "parts_master.csv",
    "inventory": "inventory_current.csv",
    "demand": "demand_history.csv",
    "suppliers": "suppliers.csv",
    "offers": "supplier_offers.csv",
}


def build_all() -> dict:
    """Construye todas las tablas del dataset en memoria.

    Entrada:
        Ninguna. Lee los CSV crudos desde la ruta configurada.

    Salida:
        Diccionario con las claves cities, parts, demand, inventory, suppliers y
        offers, cada una con su DataFrame.

    Funcionalidad:
        Genera las tablas en el orden de sus dependencias y comparte un unico
        generador aleatorio con semilla fija, de modo que dos ejecuciones
        producen exactamente el mismo resultado.
    """
    rng = np.random.default_rng(config.SEED)
    spine = load_spine(config.RAW_DIR)
    procurement = load_procurement(config.RAW_DIR)

    parts = build_parts_master(spine)
    demand = shift_demand_to_horizon(build_demand_history(spine), config.DEMAND_HORIZON)
    suppliers = build_suppliers(procurement)

    return {
        "cities": build_cities(),
        "parts": parts,
        "demand": demand,
        "inventory": build_inventory_current(parts, demand, rng),
        "suppliers": suppliers,
        "offers": build_supplier_offers(parts, demand, suppliers, rng),
    }


def publish(tables: dict) -> list:
    """Valida y escribe las tablas en la carpeta de salida.

    Entrada:
        tables: diccionario de DataFrames devuelto por build_all.

    Salida:
        Lista de advertencias emitidas por la validacion.

    Funcionalidad:
        Ejecuta la validacion antes de escribir, de modo que un dataset invalido
        nunca llega a publicarse, y añade el diccionario de datos junto a los
        CSV.
    """
    warnings = validate(tables)
    config.OUT_DIR.mkdir(parents=True, exist_ok=True)
    for key, filename in FILE_NAMES.items():
        tables[key].to_csv(config.OUT_DIR / filename, index=False)
    write_data_dictionary(config.OUT_DIR)
    return warnings
