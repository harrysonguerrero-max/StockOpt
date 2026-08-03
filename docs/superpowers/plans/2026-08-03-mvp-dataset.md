# MVP Dataset Build — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transformar los CSV crudos de `app/data/` en 7 tablas relacionadas y validadas (las 4 entradas de datos del proyecto) mediante un script reproducible.

**Architecture:** Un paquete `app/dataprep/` con funciones puras de construcción (`config`, `builders`, `validate`) y un entrypoint delgado `app/data/build_mvp_dataset.py`. Cada builder toma DataFrames de entrada y devuelve un DataFrame de salida; los campos sintéticos usan un único `numpy.random.default_rng(SEED)` sobre datos ordenados de forma determinista, de modo que el build es idempotente. La validación corre al final y falla ante errores críticos.

**Tech Stack:** Python 3.10 (`.venv` existente), pandas ≥2.2, numpy, pytest.

## Global Constraints

- Los CSV crudos en `app/data/*.csv` **no se modifican ni se mueven**. Solo se leen.
- Salidas se escriben en `app/data/mvp/`.
- Toda aleatoriedad usa `numpy.random.default_rng(SEED)` con `SEED = 20260803`. El build es **idempotente** (dos corridas → archivos idénticos).
- Moneda: `INR_TO_USD = 1/83`; todos los montos monetarios en USD redondeados a 2 decimales.
- Alcance fijo: **20 piezas × 3 ciudades × 5 proveedores**, demanda **mensual**.
- Fuentes usadas: `synthetic_industrial_machine_data.csv` (spine) y `Procurement KPI Analysis Dataset.csv`. Los demás CSV quedan fuera de alcance.
- Mapeo de ciudades: `PUN-01→PUNE (Pune)`, `CHN-02→CHEN (Chennai)`, `DHR-03→DHAR (Dharuhera)`, todas country `India`.
- Vida útil por familia (días): Lubrication 180, Filter 365, Seal & Gasket 730, Drive Belt 1095, Bearing 1825, Coupling 2555, Electrical 1825, Sensor 1825, Fastener 3650.
- Z por criticidad para reorder point: A=1.65, B=1.28, C=0.84.
- Cada `sku_id` debe tener ≥ 2 ofertas de proveedor.

---

### Task 0: Entorno y scaffold del paquete

**Files:**
- Modify: entorno `.venv` (instalar dependencias)
- Create: `app/dataprep/__init__.py`
- Create: `app/dataprep/config.py`
- Create: `tests/__init__.py`
- Create: `tests/dataprep/__init__.py`
- Test: `tests/dataprep/test_config.py`

**Interfaces:**
- Produces: `app.dataprep.config` con constantes:
  - `SEED: int = 20260803`
  - `INR_TO_USD: float = 1/83`
  - `RAW_DIR: pathlib.Path` (apunta a `app/data`), `OUT_DIR: pathlib.Path` (`app/data/mvp`)
  - `CITY_MAP: dict[str, dict]` — `plant_code → {"city_id","city_name","country","warehouse_id"}`
  - `SHELF_LIFE_BY_FAMILY: dict[str, int]`
  - `Z_BY_CRITICALITY: dict[str, float]`

- [ ] **Step 1: Instalar dependencias en el venv**

Run:
```bash
.venv/Scripts/python.exe -m pip install "pandas>=2.2" numpy pytest
```
Expected: instala pandas, numpy, pytest sin error.

- [ ] **Step 2: Crear los `__init__.py` vacíos**

Crear `app/dataprep/__init__.py`, `tests/__init__.py`, `tests/dataprep/__init__.py` como archivos vacíos.

- [ ] **Step 3: Escribir el test de config (falla)**

`tests/dataprep/test_config.py`:
```python
from app.dataprep import config

FAMILIES = {"Lubrication","Filter","Seal & Gasket","Drive Belt","Bearing",
            "Coupling","Electrical","Sensor","Fastener"}

def test_seed_and_rate():
    assert config.SEED == 20260803
    assert abs(config.INR_TO_USD - 1/83) < 1e-12

def test_city_map_has_three_plants():
    assert set(config.CITY_MAP) == {"PUN-01","CHN-02","DHR-03"}
    pune = config.CITY_MAP["PUN-01"]
    assert pune["city_id"] == "PUNE"
    assert pune["warehouse_id"] == "PUN-01"
    assert pune["country"] == "India"

def test_shelf_life_covers_every_family():
    assert set(config.SHELF_LIFE_BY_FAMILY) == FAMILIES
    assert all(v > 0 for v in config.SHELF_LIFE_BY_FAMILY.values())

def test_z_by_criticality():
    assert config.Z_BY_CRITICALITY == {"A": 1.65, "B": 1.28, "C": 0.84}

def test_dirs_exist():
    assert config.RAW_DIR.name == "data"
    assert (config.RAW_DIR / "synthetic_industrial_machine_data.csv").exists()
```

- [ ] **Step 4: Correr el test (falla por import)**

Run: `.venv/Scripts/python.exe -m pytest tests/dataprep/test_config.py -v`
Expected: FAIL (ModuleNotFoundError / AttributeError).

- [ ] **Step 5: Implementar `config.py`**

`app/dataprep/config.py`:
```python
from pathlib import Path

SEED = 20260803
INR_TO_USD = 1 / 83

RAW_DIR = Path(__file__).resolve().parents[1] / "data"
OUT_DIR = RAW_DIR / "mvp"

CITY_MAP = {
    "PUN-01": {"city_id": "PUNE", "city_name": "Pune",      "country": "India", "warehouse_id": "PUN-01"},
    "CHN-02": {"city_id": "CHEN", "city_name": "Chennai",   "country": "India", "warehouse_id": "CHN-02"},
    "DHR-03": {"city_id": "DHAR", "city_name": "Dharuhera", "country": "India", "warehouse_id": "DHR-03"},
}

SHELF_LIFE_BY_FAMILY = {
    "Lubrication": 180, "Filter": 365, "Seal & Gasket": 730, "Drive Belt": 1095,
    "Bearing": 1825, "Coupling": 2555, "Electrical": 1825, "Sensor": 1825, "Fastener": 3650,
}

Z_BY_CRITICALITY = {"A": 1.65, "B": 1.28, "C": 0.84}
```

- [ ] **Step 6: Correr el test (pasa)**

Run: `.venv/Scripts/python.exe -m pytest tests/dataprep/test_config.py -v`
Expected: PASS (5 tests).

- [ ] **Step 7: Commit**

```bash
git add app/dataprep/__init__.py app/dataprep/config.py tests/__init__.py tests/dataprep/__init__.py tests/dataprep/test_config.py
git commit -m "feat(dataprep): scaffold paquete y constantes de config"
```

---

### Task 1: Cargadores de fuentes

**Files:**
- Create: `app/dataprep/builders.py`
- Test: `tests/dataprep/test_sources.py`

**Interfaces:**
- Consumes: `app.dataprep.config` (RAW_DIR).
- Produces:
  - `load_spine(raw_dir: Path) -> pd.DataFrame` — lee `synthetic_industrial_machine_data.csv`, parsea `transaction_date` a datetime. Columnas garantizadas: `transaction_date, plant_code, part_no, part_description, part_family, criticality, uom, unit_cost_inr, qty_issued, breakdown_flag`.
  - `load_procurement(raw_dir: Path) -> pd.DataFrame` — lee `Procurement KPI Analysis Dataset.csv`, parsea `Order_Date` y `Delivery_Date` a datetime.

- [ ] **Step 1: Escribir el test (falla)**

`tests/dataprep/test_sources.py`:
```python
import pandas as pd
from app.dataprep import config
from app.dataprep.builders import load_spine, load_procurement

def test_load_spine_shape():
    df = load_spine(config.RAW_DIR)
    assert df["part_no"].nunique() == 20
    assert set(df["plant_code"].unique()) == {"PUN-01", "CHN-02", "DHR-03"}
    assert pd.api.types.is_datetime64_any_dtype(df["transaction_date"])
    assert (df["qty_issued"] >= 0).all()

def test_load_procurement_dates():
    df = load_procurement(config.RAW_DIR)
    assert pd.api.types.is_datetime64_any_dtype(df["Order_Date"])
    assert pd.api.types.is_datetime64_any_dtype(df["Delivery_Date"])
    assert df["Supplier"].nunique() == 5
```

- [ ] **Step 2: Correr (falla)**

Run: `.venv/Scripts/python.exe -m pytest tests/dataprep/test_sources.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implementar loaders en `builders.py`**

`app/dataprep/builders.py` (inicio del archivo):
```python
from pathlib import Path
import numpy as np
import pandas as pd
from app.dataprep import config


def load_spine(raw_dir: Path) -> pd.DataFrame:
    df = pd.read_csv(raw_dir / "synthetic_industrial_machine_data.csv")
    df["transaction_date"] = pd.to_datetime(df["transaction_date"])
    df["breakdown_flag"] = df["breakdown_flag"].fillna(0).astype(int)
    return df


def load_procurement(raw_dir: Path) -> pd.DataFrame:
    df = pd.read_csv(raw_dir / "Procurement KPI Analysis Dataset.csv")
    df["Order_Date"] = pd.to_datetime(df["Order_Date"], errors="coerce")
    df["Delivery_Date"] = pd.to_datetime(df["Delivery_Date"], errors="coerce")
    return df
```

- [ ] **Step 4: Correr (pasa)**

Run: `.venv/Scripts/python.exe -m pytest tests/dataprep/test_sources.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/dataprep/builders.py tests/dataprep/test_sources.py
git commit -m "feat(dataprep): loaders de spine y procurement"
```

---

### Task 2: `build_cities` y `build_parts_master`

**Files:**
- Modify: `app/dataprep/builders.py`
- Test: `tests/dataprep/test_parts_cities.py`

**Interfaces:**
- Consumes: `load_spine`, `config`.
- Produces:
  - `build_cities() -> pd.DataFrame` — columnas `city_id, city_name, country, warehouse_id` (3 filas).
  - `build_parts_master(spine: pd.DataFrame) -> pd.DataFrame` — columnas `sku_id, description, category, criticality, uom, unit_cost_usd, currency, shelf_life_days` (20 filas, ordenadas por `sku_id`).

- [ ] **Step 1: Escribir el test (falla)**

`tests/dataprep/test_parts_cities.py`:
```python
from app.dataprep import config
from app.dataprep.builders import load_spine, build_cities, build_parts_master

def test_build_cities():
    c = build_cities()
    assert len(c) == 3
    assert set(c["city_id"]) == {"PUNE", "CHEN", "DHAR"}
    assert list(c.columns) == ["city_id", "city_name", "country", "warehouse_id"]

def test_parts_master_rows_and_usd():
    spine = load_spine(config.RAW_DIR)
    parts = build_parts_master(spine)
    assert len(parts) == 20
    assert parts["sku_id"].is_unique
    # MRO-10045 cuesta 850 INR en el spine -> 850/83 = 10.24 USD
    row = parts.loc[parts["sku_id"] == "MRO-10045"].iloc[0]
    assert abs(row["unit_cost_usd"] - round(850 / 83, 2)) < 1e-9
    assert row["currency"] == "USD"

def test_parts_master_shelf_life_and_no_nulls():
    spine = load_spine(config.RAW_DIR)
    parts = build_parts_master(spine)
    assert parts.notna().all().all()
    assert (parts["shelf_life_days"] > 0).all()
    assert set(parts["criticality"]).issubset({"A", "B", "C"})
```

- [ ] **Step 2: Correr (falla)**

Run: `.venv/Scripts/python.exe -m pytest tests/dataprep/test_parts_cities.py -v`
Expected: FAIL.

- [ ] **Step 3: Implementar en `builders.py`**

```python
def build_cities() -> pd.DataFrame:
    rows = [config.CITY_MAP[p] for p in ("PUN-01", "CHN-02", "DHR-03")]
    return pd.DataFrame(rows)[["city_id", "city_name", "country", "warehouse_id"]]


def build_parts_master(spine: pd.DataFrame) -> pd.DataFrame:
    cols = ["part_no", "part_description", "part_family", "criticality", "uom", "unit_cost_inr"]
    parts = spine[cols].drop_duplicates("part_no").sort_values("part_no").reset_index(drop=True)
    out = pd.DataFrame({
        "sku_id": parts["part_no"],
        "description": parts["part_description"],
        "category": parts["part_family"],
        "criticality": parts["criticality"],
        "uom": parts["uom"],
        "unit_cost_usd": (parts["unit_cost_inr"] * config.INR_TO_USD).round(2),
        "currency": "USD",
        "shelf_life_days": parts["part_family"].map(config.SHELF_LIFE_BY_FAMILY).astype(int),
    })
    return out
```

- [ ] **Step 4: Correr (pasa)**

Run: `.venv/Scripts/python.exe -m pytest tests/dataprep/test_parts_cities.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/dataprep/builders.py tests/dataprep/test_parts_cities.py
git commit -m "feat(dataprep): build_cities y build_parts_master"
```

---

### Task 3: `build_demand_history` (mensual)

**Files:**
- Modify: `app/dataprep/builders.py`
- Test: `tests/dataprep/test_demand.py`

**Interfaces:**
- Consumes: `load_spine`, `config`.
- Produces: `build_demand_history(spine: pd.DataFrame) -> pd.DataFrame` — grano sku×ciudad×mes. Columnas `sku_id, city_id, period_month, qty_issued, issue_events, breakdown_events`. `period_month` es string `YYYY-MM`. `city_id` mapeada desde `plant_code`. Ordenada por `sku_id, city_id, period_month`.

- [ ] **Step 1: Escribir el test (falla)**

`tests/dataprep/test_demand.py`:
```python
from app.dataprep import config
from app.dataprep.builders import load_spine, build_demand_history

def test_demand_grain_and_columns():
    spine = load_spine(config.RAW_DIR)
    d = build_demand_history(spine)
    assert list(d.columns) == ["sku_id", "city_id", "period_month",
                               "qty_issued", "issue_events", "breakdown_events"]
    assert set(d["city_id"]) == {"PUNE", "CHEN", "DHAR"}
    # grano único
    assert not d.duplicated(["sku_id", "city_id", "period_month"]).any()

def test_demand_totals_match_spine():
    spine = load_spine(config.RAW_DIR)
    d = build_demand_history(spine)
    assert d["qty_issued"].sum() == spine["qty_issued"].sum()
    assert (d["issue_events"] >= 0).all()
    assert (d["qty_issued"] >= 0).all()
```

- [ ] **Step 2: Correr (falla)**

Run: `.venv/Scripts/python.exe -m pytest tests/dataprep/test_demand.py -v`
Expected: FAIL.

- [ ] **Step 3: Implementar en `builders.py`**

```python
def build_demand_history(spine: pd.DataFrame) -> pd.DataFrame:
    df = spine.copy()
    df["city_id"] = df["plant_code"].map(lambda p: config.CITY_MAP[p]["city_id"])
    df["period_month"] = df["transaction_date"].dt.strftime("%Y-%m")
    grp = df.groupby(["part_no", "city_id", "period_month"], as_index=False).agg(
        qty_issued=("qty_issued", "sum"),
        issue_events=("qty_issued", lambda s: int((s > 0).sum())),
        breakdown_events=("breakdown_flag", "sum"),
    )
    grp = grp.rename(columns={"part_no": "sku_id"})
    grp = grp.sort_values(["sku_id", "city_id", "period_month"]).reset_index(drop=True)
    grp["qty_issued"] = grp["qty_issued"].astype(int)
    grp["breakdown_events"] = grp["breakdown_events"].astype(int)
    return grp
```

- [ ] **Step 4: Correr (pasa)**

Run: `.venv/Scripts/python.exe -m pytest tests/dataprep/test_demand.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/dataprep/builders.py tests/dataprep/test_demand.py
git commit -m "feat(dataprep): build_demand_history mensual"
```

---

### Task 4: `build_inventory_current`

**Files:**
- Modify: `app/dataprep/builders.py`
- Test: `tests/dataprep/test_inventory.py`

**Interfaces:**
- Consumes: `build_parts_master`, `build_demand_history`, `config`.
- Produces: `build_inventory_current(parts: pd.DataFrame, demand: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame`. 60 filas (20 sku × 3 ciudades). Columnas `sku_id, city_id, warehouse_id, snapshot_date, on_hand_qty, reorder_point, reorder_qty, unit_cost_usd, stock_value_usd, below_reorder`.
  - Estadística: por sku×ciudad, `mu = mean(qty_issued mensual)`, `sigma = std(qty_issued mensual, ddof=0)`.
  - `reorder_point = ceil(mu + z*sigma)` con z según criticidad de la pieza.
  - `reorder_qty = max(1, ceil(mu))`.
  - `on_hand_qty = round(mu * coverage)` con `coverage = rng.uniform(0.3, 2.0)` (una extracción por fila, en orden sku,city).
  - `below_reorder = int(on_hand_qty < reorder_point)`.
  - `stock_value_usd = round(on_hand_qty * unit_cost_usd, 2)`.
  - `snapshot_date` = último `period_month` global + "-28" (string).
  - `warehouse_id` derivado de `city_id` vía CITY_MAP inverso.

- [ ] **Step 1: Escribir el test (falla)**

`tests/dataprep/test_inventory.py`:
```python
import numpy as np
from app.dataprep import config
from app.dataprep.builders import (load_spine, build_parts_master,
                                    build_demand_history, build_inventory_current)

def _fixtures():
    spine = load_spine(config.RAW_DIR)
    return build_parts_master(spine), build_demand_history(spine)

def test_inventory_shape_and_integrity():
    parts, demand = _fixtures()
    inv = build_inventory_current(parts, demand, np.random.default_rng(config.SEED))
    assert len(inv) == 60
    assert set(inv["sku_id"]).issubset(set(parts["sku_id"]))
    assert set(inv["city_id"]) == {"PUNE", "CHEN", "DHAR"}
    assert (inv["reorder_qty"] >= 1).all()
    assert (inv["on_hand_qty"] >= 0).all()

def test_below_reorder_and_stock_value():
    parts, demand = _fixtures()
    inv = build_inventory_current(parts, demand, np.random.default_rng(config.SEED))
    expected_flag = (inv["on_hand_qty"] < inv["reorder_point"]).astype(int)
    assert (inv["below_reorder"] == expected_flag).all()
    calc = (inv["on_hand_qty"] * inv["unit_cost_usd"]).round(2)
    assert (inv["stock_value_usd"] == calc).all()

def test_inventory_deterministic():
    parts, demand = _fixtures()
    a = build_inventory_current(parts, demand, np.random.default_rng(config.SEED))
    b = build_inventory_current(parts, demand, np.random.default_rng(config.SEED))
    assert a.equals(b)
```

- [ ] **Step 2: Correr (falla)**

Run: `.venv/Scripts/python.exe -m pytest tests/dataprep/test_inventory.py -v`
Expected: FAIL.

- [ ] **Step 3: Implementar en `builders.py`**

```python
import math

_CITY_TO_WH = {v["city_id"]: v["warehouse_id"] for v in config.CITY_MAP.values()}


def build_inventory_current(parts, demand, rng):
    snapshot = demand["period_month"].max() + "-28"
    crit = dict(zip(parts["sku_id"], parts["criticality"]))
    cost = dict(zip(parts["sku_id"], parts["unit_cost_usd"]))

    stats = demand.groupby(["sku_id", "city_id"])["qty_issued"].agg(
        mu="mean", sigma=lambda s: float(s.std(ddof=0))
    ).reset_index().sort_values(["sku_id", "city_id"]).reset_index(drop=True)

    rows = []
    for _, r in stats.iterrows():
        sku, city, mu, sigma = r["sku_id"], r["city_id"], r["mu"], r["sigma"]
        z = config.Z_BY_CRITICALITY[crit[sku]]
        reorder_point = math.ceil(mu + z * sigma)
        reorder_qty = max(1, math.ceil(mu))
        coverage = float(rng.uniform(0.3, 2.0))
        on_hand = int(round(mu * coverage))
        unit_cost = cost[sku]
        rows.append({
            "sku_id": sku,
            "city_id": city,
            "warehouse_id": _CITY_TO_WH[city],
            "snapshot_date": snapshot,
            "on_hand_qty": on_hand,
            "reorder_point": reorder_point,
            "reorder_qty": reorder_qty,
            "unit_cost_usd": unit_cost,
            "stock_value_usd": round(on_hand * unit_cost, 2),
            "below_reorder": int(on_hand < reorder_point),
        })
    return pd.DataFrame(rows)
```

- [ ] **Step 4: Correr (pasa)**

Run: `.venv/Scripts/python.exe -m pytest tests/dataprep/test_inventory.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/dataprep/builders.py tests/dataprep/test_inventory.py
git commit -m "feat(dataprep): build_inventory_current sintetizado"
```

---

### Task 5: `build_suppliers`

**Files:**
- Modify: `app/dataprep/builders.py`
- Test: `tests/dataprep/test_suppliers.py`

**Interfaces:**
- Consumes: `load_procurement`, `config`.
- Produces: `build_suppliers(procurement: pd.DataFrame) -> pd.DataFrame`. 5 filas. Columnas `supplier_id, name, city_id, active, contact_email, lead_time_avg_days, lead_time_min_days, lead_time_max_days, lead_time_std_days`.
  - Proveedores ordenados alfabéticamente por nombre de Procurement → `SUP-01..SUP-05`.
  - Lead time por proveedor: `(Delivery_Date - Order_Date).days` sobre órdenes con ambas fechas válidas → avg (round 1), min, max, std (round 2). Solo valores > 0.
  - `city_id` round-robin sobre ["PUNE","CHEN","DHAR"] por índice.
  - `contact_email = f"ordenes@{slug}.com"` con slug = name en minúsculas, `_`→`-`.
  - `active = True`.

- [ ] **Step 1: Escribir el test (falla)**

`tests/dataprep/test_suppliers.py`:
```python
from app.dataprep import config
from app.dataprep.builders import load_procurement, build_suppliers

def test_suppliers_rows_and_ids():
    s = build_suppliers(load_procurement(config.RAW_DIR))
    assert len(s) == 5
    assert list(s["supplier_id"]) == ["SUP-01","SUP-02","SUP-03","SUP-04","SUP-05"]
    assert set(s["city_id"]).issubset({"PUNE","CHEN","DHAR"})

def test_suppliers_lead_times_valid():
    s = build_suppliers(load_procurement(config.RAW_DIR))
    assert (s["lead_time_min_days"] > 0).all()
    assert (s["lead_time_min_days"] <= s["lead_time_avg_days"]).all()
    assert (s["lead_time_avg_days"] <= s["lead_time_max_days"]).all()
    assert s["contact_email"].str.contains("@").all()
```

- [ ] **Step 2: Correr (falla)**

Run: `.venv/Scripts/python.exe -m pytest tests/dataprep/test_suppliers.py -v`
Expected: FAIL.

- [ ] **Step 3: Implementar en `builders.py`**

```python
_CITY_CYCLE = ["PUNE", "CHEN", "DHAR"]


def build_suppliers(procurement: pd.DataFrame) -> pd.DataFrame:
    df = procurement.dropna(subset=["Order_Date", "Delivery_Date"]).copy()
    df["lead_days"] = (df["Delivery_Date"] - df["Order_Date"]).dt.days
    df = df[df["lead_days"] > 0]

    rows = []
    for i, name in enumerate(sorted(procurement["Supplier"].unique())):
        lt = df.loc[df["Supplier"] == name, "lead_days"]
        slug = name.lower().replace("_", "-")
        rows.append({
            "supplier_id": f"SUP-{i+1:02d}",
            "name": name,
            "city_id": _CITY_CYCLE[i % len(_CITY_CYCLE)],
            "active": True,
            "contact_email": f"ordenes@{slug}.com",
            "lead_time_avg_days": round(float(lt.mean()), 1),
            "lead_time_min_days": int(lt.min()),
            "lead_time_max_days": int(lt.max()),
            "lead_time_std_days": round(float(lt.std(ddof=0)), 2),
        })
    return pd.DataFrame(rows)
```

- [ ] **Step 4: Correr (pasa)**

Run: `.venv/Scripts/python.exe -m pytest tests/dataprep/test_suppliers.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/dataprep/builders.py tests/dataprep/test_suppliers.py
git commit -m "feat(dataprep): build_suppliers con lead time real"
```

---

### Task 6: `build_supplier_offers`

**Files:**
- Modify: `app/dataprep/builders.py`
- Test: `tests/dataprep/test_offers.py`

**Interfaces:**
- Consumes: `build_parts_master`, `build_demand_history`, `build_suppliers`, `config`.
- Produces: `build_supplier_offers(parts, demand, suppliers, rng) -> pd.DataFrame`. Columnas `offer_id, supplier_id, sku_id, unit_price_usd, moq, capacity_per_month, freight_cost_usd, currency`.
  - Para cada `sku_id` (orden ascendente): elegir `k = rng.integers(2, 4)` proveedores distintos (`rng.choice` sobre los 5 supplier_id, sin reemplazo).
  - `markup` por proveedor: `1.05 + 0.03*i` para `SUP-(i+1)` (i=0..4) → 1.05..1.17.
  - `unit_price_usd = round(unit_cost_usd * markup, 2)`.
  - `moq`: piezas baratas MOQ alto, caras bajo → `moq = max(1, int(round(200 / max(unit_cost_usd,1))))` acotado a [1, 100].
  - `capacity_per_month = max(demanda mensual máxima observada del sku en cualquier ciudad, moq) * 3`.
  - `freight_cost_usd`: fijo por proveedor = `round(10 + 5*i, 2)`.
  - `offer_id = f"{supplier_id}_{sku_id}"`.

- [ ] **Step 1: Escribir el test (falla)**

`tests/dataprep/test_offers.py`:
```python
import numpy as np
from app.dataprep import config
from app.dataprep.builders import (load_spine, load_procurement, build_parts_master,
                                    build_demand_history, build_suppliers, build_supplier_offers)

def _fx():
    spine = load_spine(config.RAW_DIR)
    parts = build_parts_master(spine)
    demand = build_demand_history(spine)
    suppliers = build_suppliers(load_procurement(config.RAW_DIR))
    return parts, demand, suppliers

def test_every_sku_has_at_least_two_offers():
    parts, demand, suppliers = _fx()
    offers = build_supplier_offers(parts, demand, suppliers, np.random.default_rng(config.SEED))
    counts = offers.groupby("sku_id").size()
    assert (counts >= 2).all()
    assert set(offers["supplier_id"]).issubset(set(suppliers["supplier_id"]))
    assert offers["offer_id"].is_unique

def test_offer_values_valid():
    parts, demand, suppliers = _fx()
    offers = build_supplier_offers(parts, demand, suppliers, np.random.default_rng(config.SEED))
    cost = dict(zip(parts["sku_id"], parts["unit_cost_usd"]))
    assert (offers["moq"] >= 1).all()
    assert (offers["freight_cost_usd"] >= 0).all()
    for _, r in offers.iterrows():
        assert r["unit_price_usd"] >= cost[r["sku_id"]]  # precio >= costo

def test_offers_deterministic():
    parts, demand, suppliers = _fx()
    a = build_supplier_offers(parts, demand, suppliers, np.random.default_rng(config.SEED))
    b = build_supplier_offers(parts, demand, suppliers, np.random.default_rng(config.SEED))
    assert a.equals(b)
```

- [ ] **Step 2: Correr (falla)**

Run: `.venv/Scripts/python.exe -m pytest tests/dataprep/test_offers.py -v`
Expected: FAIL.

- [ ] **Step 3: Implementar en `builders.py`**

```python
def build_supplier_offers(parts, demand, suppliers, rng):
    supplier_ids = list(suppliers["supplier_id"])
    markup = {sid: round(1.05 + 0.03 * i, 4) for i, sid in enumerate(supplier_ids)}
    freight = {sid: round(10 + 5 * i, 2) for i, sid in enumerate(supplier_ids)}
    cost = dict(zip(parts["sku_id"], parts["unit_cost_usd"]))
    max_dem = demand.groupby("sku_id")["qty_issued"].max().to_dict()

    rows = []
    for sku in sorted(parts["sku_id"]):
        k = int(rng.integers(2, 4))  # 2 o 3
        chosen = rng.choice(supplier_ids, size=k, replace=False)
        unit_cost = cost[sku]
        moq = min(100, max(1, int(round(200 / max(unit_cost, 1)))))
        cap = max(int(max_dem.get(sku, 0)), moq) * 3
        for sid in chosen:
            rows.append({
                "offer_id": f"{sid}_{sku}",
                "supplier_id": sid,
                "sku_id": sku,
                "unit_price_usd": round(unit_cost * markup[sid], 2),
                "moq": moq,
                "capacity_per_month": cap,
                "freight_cost_usd": freight[sid],
                "currency": "USD",
            })
    return pd.DataFrame(rows).sort_values(["sku_id", "supplier_id"]).reset_index(drop=True)
```

- [ ] **Step 4: Correr (pasa)**

Run: `.venv/Scripts/python.exe -m pytest tests/dataprep/test_offers.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/dataprep/builders.py tests/dataprep/test_offers.py
git commit -m "feat(dataprep): build_supplier_offers con 2-3 ofertas por sku"
```

---

### Task 7: Validación (Etapa 1.1 del spec)

**Files:**
- Create: `app/dataprep/validate.py`
- Test: `tests/dataprep/test_validate.py`

**Interfaces:**
- Consumes: los 6 DataFrames (`cities, parts, inventory, demand, suppliers, offers`).
- Produces: `validate(tables: dict[str, pd.DataFrame]) -> list[str]`. Devuelve lista de **advertencias**; **levanta `ValueError`** si hay error crítico. Chequeos:
  - Integridad referencial: `inventory.sku_id`, `demand.sku_id`, `offers.sku_id` ⊆ `parts.sku_id`; `inventory.city_id`, `demand.city_id` ⊆ `cities.city_id`; `offers.supplier_id` ⊆ `suppliers.supplier_id`.
  - Rangos: `parts.unit_cost_usd >= 0`, `offers.unit_price_usd >= 0`, `suppliers.lead_time_min_days > 0`, `demand.qty_issued >= 0`, `inventory.on_hand_qty >= 0`.
  - Cada `sku_id` tiene ≥ 2 ofertas (crítico).
  - Sin nulos en ninguna tabla (crítico).
  - Sin duplicados de llave: `parts.sku_id`, `offers.offer_id`, `inventory[sku_id,city_id]`, `demand[sku_id,city_id,period_month]` (crítico).

- [ ] **Step 1: Escribir el test (falla)**

`tests/dataprep/test_validate.py`:
```python
import numpy as np
import pytest
from app.dataprep import config
from app.dataprep.builders import (load_spine, load_procurement, build_cities,
    build_parts_master, build_demand_history, build_inventory_current,
    build_suppliers, build_supplier_offers)
from app.dataprep.validate import validate

def _tables():
    spine = load_spine(config.RAW_DIR)
    rng = np.random.default_rng(config.SEED)
    parts = build_parts_master(spine)
    demand = build_demand_history(spine)
    return {
        "cities": build_cities(),
        "parts": parts,
        "demand": demand,
        "inventory": build_inventory_current(parts, demand, rng),
        "suppliers": build_suppliers(load_procurement(config.RAW_DIR)),
        "offers": build_supplier_offers(parts, demand, build_suppliers(load_procurement(config.RAW_DIR)), rng),
    }

def test_validate_passes_on_good_tables():
    warnings = validate(_tables())
    assert isinstance(warnings, list)

def test_validate_raises_on_orphan_sku():
    t = _tables()
    t["inventory"].loc[0, "sku_id"] = "MRO-99999"
    with pytest.raises(ValueError):
        validate(t)

def test_validate_raises_on_negative_price():
    t = _tables()
    t["offers"].loc[0, "unit_price_usd"] = -1
    with pytest.raises(ValueError):
        validate(t)
```

- [ ] **Step 2: Correr (falla)**

Run: `.venv/Scripts/python.exe -m pytest tests/dataprep/test_validate.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implementar `validate.py`**

```python
import pandas as pd


def validate(tables: dict) -> list:
    errors, warnings = [], []
    parts = tables["parts"]; cities = tables["cities"]
    inv = tables["inventory"]; dem = tables["demand"]
    sup = tables["suppliers"]; off = tables["offers"]

    sku_set = set(parts["sku_id"]); city_set = set(cities["city_id"])
    sup_set = set(sup["supplier_id"])

    def subset(col_vals, ref, label):
        orphans = set(col_vals) - ref
        if orphans:
            errors.append(f"Integridad {label}: huérfanos {sorted(orphans)[:5]}")

    subset(inv["sku_id"], sku_set, "inventory.sku_id")
    subset(dem["sku_id"], sku_set, "demand.sku_id")
    subset(off["sku_id"], sku_set, "offers.sku_id")
    subset(inv["city_id"], city_set, "inventory.city_id")
    subset(dem["city_id"], city_set, "demand.city_id")
    subset(off["supplier_id"], sup_set, "offers.supplier_id")

    if (parts["unit_cost_usd"] < 0).any(): errors.append("parts.unit_cost_usd < 0")
    if (off["unit_price_usd"] < 0).any(): errors.append("offers.unit_price_usd < 0")
    if (sup["lead_time_min_days"] <= 0).any(): errors.append("suppliers.lead_time_min_days <= 0")
    if (dem["qty_issued"] < 0).any(): errors.append("demand.qty_issued < 0")
    if (inv["on_hand_qty"] < 0).any(): errors.append("inventory.on_hand_qty < 0")

    counts = off.groupby("sku_id").size()
    below = set(sku_set) - set(counts[counts >= 2].index)
    if below: errors.append(f"SKUs con <2 ofertas: {sorted(below)[:5]}")

    for name, df in tables.items():
        if df.isna().any().any():
            errors.append(f"{name}: contiene nulos")

    if not parts["sku_id"].is_unique: errors.append("parts.sku_id duplicado")
    if not off["offer_id"].is_unique: errors.append("offers.offer_id duplicado")
    if inv.duplicated(["sku_id", "city_id"]).any(): errors.append("inventory llave duplicada")
    if dem.duplicated(["sku_id", "city_id", "period_month"]).any(): errors.append("demand llave duplicada")

    if errors:
        raise ValueError("Errores críticos de validación:\n- " + "\n- ".join(errors))
    return warnings
```

- [ ] **Step 4: Correr (pasa)**

Run: `.venv/Scripts/python.exe -m pytest tests/dataprep/test_validate.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/dataprep/validate.py tests/dataprep/test_validate.py
git commit -m "feat(dataprep): validacion de integridad y rangos"
```

---

### Task 8: Entrypoint, diccionario de datos y build end-to-end

**Files:**
- Create: `app/data/build_mvp_dataset.py`
- Create: `app/dataprep/dictionary.py`
- Test: `tests/dataprep/test_build_end_to_end.py`

**Interfaces:**
- Consumes: todos los builders + `validate` + `config`.
- Produces:
  - `app.dataprep.dictionary.write_data_dictionary(out_dir: Path) -> Path` — escribe `data_dictionary.md`.
  - `app/data/build_mvp_dataset.py` con `build_all() -> dict[str, pd.DataFrame]` y `main()` que escribe los 7 CSV + diccionario en `config.OUT_DIR`, corre `validate`, e imprime el reporte. Ejecutable con `python -m app.data.build_mvp_dataset`.

- [ ] **Step 1: Escribir el test end-to-end (falla)**

`tests/dataprep/test_build_end_to_end.py`:
```python
import importlib
from app.dataprep import config

build_mod = importlib.import_module("app.data.build_mvp_dataset")

EXPECTED = ["cities.csv","parts_master.csv","inventory_current.csv",
            "demand_history.csv","suppliers.csv","supplier_offers.csv"]

def test_build_all_shapes():
    tables = build_mod.build_all()
    assert len(tables["parts"]) == 20
    assert len(tables["cities"]) == 3
    assert len(tables["inventory"]) == 60
    assert len(tables["suppliers"]) == 5

def test_main_writes_files_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUT_DIR", tmp_path)
    build_mod.main()
    for f in EXPECTED + ["data_dictionary.md"]:
        assert (tmp_path / f).exists()
    first = (tmp_path / "inventory_current.csv").read_bytes()
    build_mod.main()  # segunda corrida
    second = (tmp_path / "inventory_current.csv").read_bytes()
    assert first == second  # idempotente
```

- [ ] **Step 2: Correr (falla)**

Run: `.venv/Scripts/python.exe -m pytest tests/dataprep/test_build_end_to_end.py -v`
Expected: FAIL.

- [ ] **Step 3: Implementar `dictionary.py`**

`app/dataprep/dictionary.py` — función que escribe un `data_dictionary.md` describiendo cada tabla, sus columnas, tipo, unidad y origen (real/sintético). Contenido mínimo:
```python
from pathlib import Path

_CONTENT = """# Diccionario de datos — MVP StockOpt

Generado por `app/data/build_mvp_dataset.py`. Montos en USD (1 USD = 83 INR).

## cities.csv
| Columna | Tipo | Origen |
|---|---|---|
| city_id | str | Derivado de plant_code |
| city_name | str | Mapeo fijo |
| country | str | Fijo (India) |
| warehouse_id | str | plant_code |

## parts_master.csv (Maestro de piezas)
| Columna | Tipo | Unidad | Origen |
|---|---|---|---|
| sku_id | str | - | part_no (real) |
| description | str | - | real |
| category | str | - | part_family (real) |
| criticality | str A/B/C | - | real |
| uom | str | - | real |
| unit_cost_usd | float | USD | real (convertido de INR) |
| currency | str | - | fijo USD |
| shelf_life_days | int | días | sintético (por familia) |

## inventory_current.csv (Inventario actual)
| Columna | Tipo | Unidad | Origen |
|---|---|---|---|
| sku_id | str | - | FK parts |
| city_id | str | - | FK cities |
| warehouse_id | str | - | derivado |
| snapshot_date | str | fecha | derivado |
| on_hand_qty | int | uds | sintético (μ×coverage) |
| reorder_point | int | uds | sintético (μ+zσ) |
| reorder_qty | int | uds | sintético (≈μ) |
| unit_cost_usd | float | USD | real |
| stock_value_usd | float | USD | derivado |
| below_reorder | int 0/1 | - | derivado |

## demand_history.csv (Demanda histórica / señal operativa)
| Columna | Tipo | Unidad | Origen |
|---|---|---|---|
| sku_id | str | - | FK parts |
| city_id | str | - | FK cities |
| period_month | str | YYYY-MM | real |
| qty_issued | int | uds | real (suma mensual) |
| issue_events | int | días | real |
| breakdown_events | int | eventos | real |

## suppliers.csv (Proveedores)
| Columna | Tipo | Unidad | Origen |
|---|---|---|---|
| supplier_id | str | - | asignado |
| name | str | - | real (Procurement KPI) |
| city_id | str | - | asignado round-robin |
| active | bool | - | fijo |
| contact_email | str | - | sintético |
| lead_time_avg_days | float | días | real (Order→Delivery) |
| lead_time_min_days | int | días | real |
| lead_time_max_days | int | días | real |
| lead_time_std_days | float | días | real |

## supplier_offers.csv (Catálogo proveedor-pieza)
| Columna | Tipo | Unidad | Origen |
|---|---|---|---|
| offer_id | str | - | supplier_id+sku_id |
| supplier_id | str | - | FK suppliers |
| sku_id | str | - | FK parts |
| unit_price_usd | float | USD | sintético (costo×markup) |
| moq | int | uds | sintético |
| capacity_per_month | int | uds | sintético |
| freight_cost_usd | float | USD | sintético |
| currency | str | - | fijo USD |
"""


def write_data_dictionary(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "data_dictionary.md"
    path.write_text(_CONTENT, encoding="utf-8")
    return path
```

- [ ] **Step 4: Implementar el entrypoint `app/data/build_mvp_dataset.py`**

```python
"""Construye el dataset MVP a partir de los CSV crudos de app/data/.

Uso: python -m app.data.build_mvp_dataset
"""
import numpy as np
import pandas as pd

from app.dataprep import config
from app.dataprep.builders import (
    load_spine, load_procurement, build_cities, build_parts_master,
    build_demand_history, build_inventory_current, build_suppliers,
    build_supplier_offers,
)
from app.dataprep.validate import validate
from app.dataprep.dictionary import write_data_dictionary

_FILE_NAMES = {
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
    for key, fname in _FILE_NAMES.items():
        tables[key].to_csv(config.OUT_DIR / fname, index=False)
    write_data_dictionary(config.OUT_DIR)

    print("Dataset MVP generado en", config.OUT_DIR)
    for key, fname in _FILE_NAMES.items():
        print(f"  {fname}: {len(tables[key])} filas")
    if warnings:
        print("Advertencias:")
        for w in warnings:
            print("  -", w)
    else:
        print("Validacion: sin errores criticos ni advertencias.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Crear `app/data/__init__.py` si falta**

El directorio `app/data` tiene un archivo mal nombrado `__init__,py` (con coma). Crear el correcto:
```bash
touch app/data/__init__.py
```
(No borrar el archivo con coma en esta tarea; solo asegurar que exista `__init__.py` válido para poder importar `app.data.build_mvp_dataset`.)

- [ ] **Step 6: Correr el test end-to-end (pasa)**

Run: `.venv/Scripts/python.exe -m pytest tests/dataprep/test_build_end_to_end.py -v`
Expected: PASS.

- [ ] **Step 7: Correr el build real y toda la suite**

Run:
```bash
.venv/Scripts/python.exe -m app.data.build_mvp_dataset
.venv/Scripts/python.exe -m pytest tests/ -v
```
Expected: genera 7 CSV + `data_dictionary.md` en `app/data/mvp/`, imprime "sin errores criticos", y toda la suite pasa.

- [ ] **Step 8: Commit**

```bash
git add app/data/build_mvp_dataset.py app/dataprep/dictionary.py app/data/__init__.py tests/dataprep/test_build_end_to_end.py app/data/mvp/
git commit -m "feat(dataprep): entrypoint build, diccionario y salidas MVP"
```

---

## Notas de ejecución

- El `.gitignore` puede excluir CSV; verificar antes del commit del Task 8 que `app/data/mvp/*.csv` no esté ignorado (si lo está, forzar con `git add -f` o ajustar `.gitignore` para permitir `app/data/mvp/`).
- Si `pandas` no importa por versión de Python 3.10, usar `pandas==2.2.*` (compatible con 3.10).
