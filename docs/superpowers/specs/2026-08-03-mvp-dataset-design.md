# Diseño — Paso 1: Dataset MVP de optimización de inventario

**Fecha:** 2026-08-03
**Etapa del spec:** Etapa 1 — Ingesta y preparación de datos
**Estado:** Aprobado (pendiente revisión del spec escrito)

## 1. Objetivo

Transformar los CSV sueltos de `app/data/` en un conjunto de tablas relacionadas y con
integridad referencial que materialicen las **4 entradas de datos** del proyecto:

1. **Maestro de piezas:** SKU, categoría, criticidad, vida útil.
2. **Inventario actual:** stock disponible por ciudad/bodega.
3. **Demanda histórica / señal operativa.**
4. **Proveedores:** precio, ciudad, lead time, MOQ, capacidad, flete.

Los archivos crudos originales **no se modifican**. Un script reproducible los lee y
genera las tablas limpias en `app/data/mvp/`.

## 2. Decisión de fondo: columna vertebral MRO

Los 8 CSV pertenecen a dominios distintos e incompatibles (repuestos industriales,
componentes electrónicos, SKUs retail, sensores de máquina). Unir llaves entre dominios
distintos produce datos sin sentido para forecasting/optimización.

Se adopta como **spine** el dataset con demanda temporal real y criticidad:

- **`synthetic_industrial_machine_data.csv`** → piezas, demanda, criticidad, señal operativa.
- **`Procurement KPI Analysis Dataset.csv`** → proveedores y lead time real.
- **`inventory-levels.csv`** → donante de *esquema* para la tabla de inventario (no de datos).
- Resto de archivos: fuera de alcance del MVP (dominios incompatibles).

Campos que **no existen** en ninguna fuente y se sintetizan de forma determinista
(semilla fija): vida útil, on-hand, reorder point/qty, MOQ, capacidad, flete.

### Decisiones confirmadas con el usuario
- **Ciudades:** 3 (Pune, Chennai, Dharuhera) — más realista que el límite blando de 2 del spec.
- **Moneda:** convertir INR → **USD** a tasa fija **1 USD = 83 INR** (`INR_TO_USD = 1/83`).
- **Granularidad de demanda:** **mensual**.

## 3. Llaves canónicas (integridad referencial)

| Llave | Origen | Ejemplo / valores |
|---|---|---|
| `sku_id` | `part_no` del spine | MRO-10045 … (20 piezas) |
| `city_id` | mapeo de `plant_code` | PUNE, CHEN, DHAR |
| `warehouse_id` | `plant_code` | PUN-01, CHN-02, DHR-03 (1 bodega por ciudad) |
| `supplier_id` | 5 proveedores de Procurement KPI | SUP-01 … SUP-05 |
| `offer_id` | `supplier_id` + `sku_id` | SUP-02_MRO-10045 |

Mapeo de plantas → ciudades:
`PUN-01 → PUNE (Pune)`, `CHN-02 → CHEN (Chennai)`, `DHR-03 → DHAR (Dharuhera)`.

Reglas de integridad garantizadas por el build:
- Todo `sku_id` en inventario/demanda/ofertas existe en `parts_master`.
- Todo `city_id` existe en `cities`.
- Todo `supplier_id` en `supplier_offers` existe en `suppliers`.
- Cada `sku_id` tiene ≥ 2 ofertas de proveedor (para dar elección al optimizador).

## 4. Tablas de salida (`app/data/mvp/`)

### 4.1 `cities.csv` (3 filas)
`city_id, city_name, country, warehouse_id`

### 4.2 `parts_master.csv` — Maestro de piezas (20 filas)
`sku_id, description, category, criticality, uom, unit_cost_usd, currency, shelf_life_days`

- `category` = `part_family` del spine.
- `criticality` = A/B/C del spine.
- `unit_cost_usd` = `unit_cost_inr` × `INR_TO_USD`, redondeado a 2 decimales.
- `shelf_life_days` **sintetizada por familia** (vida útil):

  | Familia | Vida útil (días) |
  |---|---|
  | Lubrication | 180 |
  | Filter | 365 |
  | Seal & Gasket | 730 |
  | Drive Belt | 1095 |
  | Bearing | 1825 |
  | Coupling | 2555 |
  | Electrical | 1825 |
  | Sensor | 1825 |
  | Fastener | 3650 |

### 4.3 `inventory_current.csv` — Inventario actual (60 filas: 20 sku × 3 ciudades)
`sku_id, city_id, warehouse_id, snapshot_date, on_hand_qty, reorder_point, reorder_qty, unit_cost_usd, stock_value_usd, below_reorder`

- `snapshot_date` = fecha máxima del histórico (fin del periodo).
- Estadística base por sku×ciudad: `avg_monthly_demand` (μ) y `std` del `qty_issued` mensual.
- `reorder_point = ceil(μ + z·std)` con `z` según criticidad (A=1.65, B=1.28, C=0.84).
- `reorder_qty  = ceil(μ)` (≈ 1 mes de demanda; heurística MVP).
- `on_hand_qty` sintetizado determinista: `round(μ × coverage)` con `coverage ∈ [0.3, 2.0]`
  muestreado con semilla fija por sku×ciudad → genera casos por encima y por debajo del reorder.
- `below_reorder = 1 if on_hand_qty < reorder_point else 0`.
- `stock_value_usd = on_hand_qty × unit_cost_usd`.

### 4.4 `demand_history.csv` — Demanda histórica / señal operativa (~2,580 filas)
`sku_id, city_id, period_month, qty_issued, issue_events, breakdown_events`

- Grano: sku × ciudad × mes (`period_month` = `YYYY-MM`).
- `qty_issued` = suma mensual del `qty_issued` diario del spine.
- `issue_events` = nº de días del mes con `qty_issued > 0` (intermitencia).
- `breakdown_events` = suma mensual de `breakdown_flag` (señal operativa).

### 4.5 `suppliers.csv` — Proveedores (5 filas)
`supplier_id, name, city_id, active, contact_email, lead_time_avg_days, lead_time_min_days, lead_time_max_days, lead_time_std_days`

- Lead times **derivados de datos reales**: `Delivery_Date − Order_Date` por proveedor en
  Procurement KPI (avg/min/max/std sobre órdenes entregadas).
- `city_id` asignada round-robin entre las 3 ciudades (proveedor "opera para" esa ciudad).
- `contact_email` sintetizado (`ordenes@<slug>.com`); `active = True`.

### 4.6 `supplier_offers.csv` — Catálogo proveedor-pieza (~40-50 filas)
`offer_id, supplier_id, sku_id, unit_price_usd, moq, capacity_per_month, freight_cost_usd, currency`

- Cada `sku_id` recibe 2-3 ofertas (proveedores elegidos determinista por semilla).
- `unit_price_usd` = `unit_cost_usd` × markup; markup derivado del ratio
  `Unit_Price / Negotiated_Price` de Procurement KPI (rango ~1.05-1.20), variado por proveedor.
- `moq` sintetizado por criticidad/costo (piezas baratas MOQ alto, caras MOQ bajo).
- `capacity_per_month` sintetizado ≥ demanda mensual máxima observada (para factibilidad).
- `freight_cost_usd` sintetizado por proveedor (fijo por orden).

### 4.7 `data_dictionary.md`
Documento con cada tabla, columnas, tipos, unidades, origen (real vs sintético) y llaves.

## 5. Script de construcción

`app/data/build_mvp_dataset.py`

- **Entrada:** CSV crudos en `app/data/`.
- **Salida:** tablas en `app/data/mvp/` + `data_dictionary.md`.
- **Determinismo:** `numpy.random.default_rng(SEED)` con `SEED` fijo para todo campo sintético.
- **Constantes** al inicio: `INR_TO_USD`, `SEED`, mapeos de ciudad, tabla de vida útil, z por criticidad.
- **Validaciones al final** (Etapa 1.1 del spec): tipos, rangos (precio ≥ 0, lead_time > 0,
  qty ≥ 0), integridad referencial de todas las llaves, detección de nulos y duplicados.
  Imprime un reporte de validación; falla el build si hay error crítico.
- **Idempotente:** correr el script dos veces produce exactamente los mismos archivos.

## 6. Fuera de alcance (YAGNI para el Paso 1)

- Ingesta manual de proveedores con formulario/aprobación (spec 1.2) — etapa posterior.
- Clasificación de patrones de demanda (spec 1.3) — usa este dataset, es otro paso.
- Cualquier modelado, forecasting u optimización.
- Los archivos `parts.csv`, `manufacturers.csv`, `locations.csv`, `reorder_options.csv`,
  `ai4i2020.csv` (dominios incompatibles; no se integran en el MVP).

## 7. Criterio de aceptación

- Existen las 7 salidas en `app/data/mvp/` + `data_dictionary.md`.
- Reporte de validación sin errores críticos.
- Integridad referencial verificable: joins sku/ciudad/proveedor sin huérfanos.
- Todos los montos en USD; demanda mensual; 20 piezas × 3 ciudades × 5 proveedores.
- Re-ejecución del script reproduce byte a byte las salidas.
