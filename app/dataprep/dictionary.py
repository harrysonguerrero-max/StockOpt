"""Genera el diccionario de datos del dataset MVP."""

from pathlib import Path

_CONTENT = """# Diccionario de datos - MVP StockOpt

Generado por `app/data/build_mvp_dataset.py`. Montos en USD (1 USD = 83 INR).
Alcance: 20 piezas MRO x 3 ciudades x 5 proveedores, demanda mensual.

## Fuentes
| Tabla generada | Fuente cruda |
|---|---|
| parts_master, demand_history, inventory_current | `synthetic_industrial_machine_data.csv` |
| suppliers, supplier_offers | `Procurement KPI Analysis Dataset.csv` |
| cities | mapeo fijo de `plant_code` |

## Llaves
- `sku_id` -> parts_master (PK). Referenciada por inventory, demand, offers.
- `city_id` -> cities (PK). Referenciada por inventory, demand, suppliers.
- `supplier_id` -> suppliers (PK). Referenciada por offers.
- `offer_id` = `supplier_id` + `_` + `sku_id` (PK de supplier_offers).

---

## cities.csv
| Columna | Tipo | Origen |
|---|---|---|
| city_id | str | Derivado de plant_code |
| city_name | str | Mapeo fijo |
| country | str | Fijo (India) |
| warehouse_id | str | plant_code |

## parts_master.csv - Maestro de piezas (20 filas)
| Columna | Tipo | Unidad | Origen |
|---|---|---|---|
| sku_id | str | - | part_no (real) |
| description | str | - | real |
| category | str | - | part_family (real) |
| criticality | str A/B/C | - | real |
| uom | str | - | real |
| unit_cost_usd | float | USD | real, convertido de INR |
| currency | str | - | fijo USD |
| shelf_life_days | int | dias | sintetico, por familia |

Vida util por familia: Lubrication 180, Filter 365, Seal & Gasket 730,
Drive Belt 1095, Bearing 1825, Coupling 2555, Electrical 1825, Sensor 1825,
Fastener 3650.

## inventory_current.csv - Inventario actual (60 filas)
| Columna | Tipo | Unidad | Origen |
|---|---|---|---|
| sku_id | str | - | FK parts_master |
| city_id | str | - | FK cities |
| warehouse_id | str | - | derivado de city_id |
| snapshot_date | str | fecha | ultimo mes del historico |
| on_hand_qty | int | uds | sintetico: round(reorder_point * coverage), coverage ~ U(0.35, 1.75) |
| reorder_point | int | uds | sintetico: ceil(mu + z*sigma), z por criticidad |
| reorder_qty | int | uds | sintetico: max(1, ceil(mu)) |
| unit_cost_usd | float | USD | real |
| stock_value_usd | float | USD | on_hand_qty * unit_cost_usd |
| below_reorder | int 0/1 | - | on_hand_qty < reorder_point |

mu y sigma son la media y desviacion de `qty_issued` mensual por sku x ciudad.
z: criticidad A = 1.65, B = 1.28, C = 0.84.

## demand_history.csv - Demanda historica y señal operativa
| Columna | Tipo | Unidad | Origen |
|---|---|---|---|
| sku_id | str | - | FK parts_master |
| city_id | str | - | FK cities |
| period_month | str | YYYY-MM | real |
| qty_issued | int | uds | real, suma mensual |
| issue_events | int | dias | real, dias del mes con consumo > 0 |
| breakdown_events | int | eventos | real, suma de breakdown_flag |

`issue_events` mide intermitencia: con pocos dias de consumo al mes, la demanda
es intermitente y el forecast necesita metodos robustos.

## suppliers.csv - Proveedores (5 filas)
| Columna | Tipo | Unidad | Origen |
|---|---|---|---|
| supplier_id | str | - | asignado |
| name | str | - | real |
| city_id | str | - | asignado round-robin |
| active | bool | - | fijo True |
| contact_email | str | - | sintetico |
| lead_time_avg_days | float | dias | real, Delivery_Date - Order_Date |
| lead_time_min_days | int | dias | real |
| lead_time_max_days | int | dias | real |
| lead_time_std_days | float | dias | real |

## supplier_offers.csv - Catalogo proveedor-pieza
| Columna | Tipo | Unidad | Origen |
|---|---|---|---|
| offer_id | str | - | supplier_id + sku_id |
| supplier_id | str | - | FK suppliers |
| sku_id | str | - | FK parts_master |
| unit_price_usd | float | USD | sintetico: unit_cost_usd * markup |
| moq | int | uds | sintetico: min(100, max(1, 200/costo)) |
| capacity_per_month | int | uds | sintetico: max(demanda mensual max, moq) * 3 |
| freight_cost_usd | float | USD | sintetico, fijo por proveedor |
| currency | str | - | fijo USD |

markup por proveedor: 1.05 a 1.17 en pasos de 0.03.
Cada sku recibe 2 o 3 ofertas.
"""


def write_data_dictionary(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "data_dictionary.md"
    path.write_text(_CONTENT, encoding="utf-8")
    return path
