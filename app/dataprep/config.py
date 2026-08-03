"""Constantes de construccion del dataset MVP.

Todo campo sintetico se deriva de SEED para que el build sea idempotente.
"""

from pathlib import Path

SEED = 20260803
INR_TO_USD = 1 / 83

RAW_DIR = Path(__file__).resolve().parents[1] / "data"
OUT_DIR = RAW_DIR / "mvp"

# plant_code (dato crudo) -> ciudad canonica del MVP
CITY_MAP = {
    "PUN-01": {"city_id": "PUNE", "city_name": "Pune", "country": "India", "warehouse_id": "PUN-01"},
    "CHN-02": {"city_id": "CHEN", "city_name": "Chennai", "country": "India", "warehouse_id": "CHN-02"},
    "DHR-03": {"city_id": "DHAR", "city_name": "Dharuhera", "country": "India", "warehouse_id": "DHR-03"},
}

# Vida util por familia de pieza (dias). Sintetico: el dato crudo no lo trae.
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

# Nivel de servicio por criticidad: a mayor criticidad, mas stock de seguridad.
Z_BY_CRITICALITY = {"A": 1.65, "B": 1.28, "C": 0.84}

# Stock actual como multiplo del punto de reorden. Centrado en 1.0 para que el
# dataset traiga tanto piezas que requieren compra como piezas que no.
COVERAGE_RANGE = (0.35, 1.75)
