"""Parametros de construccion del dataset MVP de inventario.

Funcionalidad:
    Centraliza las constantes que gobiernan la generacion del dataset: rutas de
    entrada y salida, tasa de cambio, mapeo de plantas a ciudades, vida util por
    familia de pieza y niveles de servicio por criticidad. Todo campo sintetico
    se deriva de SEED, lo que hace el build reproducible.
"""

from pathlib import Path

SEED = 20260803
INR_TO_USD = 1 / 83

RAW_DIR = Path(__file__).resolve().parents[1] / "data"
OUT_DIR = RAW_DIR / "mvp"

CITY_MAP = {
    "PUN-01": {"city_id": "NAVA", "city_name": "Nava, Coahuila",
               "country": "Mexico", "warehouse_id": "NAVA-01"},
    "DHR-03": {"city_id": "NAVA", "city_name": "Nava, Coahuila",
               "country": "Mexico", "warehouse_id": "NAVA-01"},
    "CHN-02": {"city_id": "OBRE", "city_name": "Ciudad Obregon, Sonora",
               "country": "Mexico", "warehouse_id": "OBRE-01"},
}

CITY_IDS = ["NAVA", "OBRE"]

SHELF_LIFE_BY_FAMILY = {
    "Lubrication": 180,
    "Filter": 365,
    "Seal & Gasket": 730,
    "Drive Belt": 1095,
    "Bearing": 1825,
    "Coupling": 2555,
    "Electrical": 1825,
    "Sensor": 1825,
    "Fastener": 3650,
}

Z_BY_CRITICALITY = {"A": 1.65, "B": 1.28, "C": 0.84}

COVERAGE_RANGE = (0.35, 1.75)

DEMAND_HORIZON = "2026-01"

MIN_DAYS_PER_MONTH = 20
