"""Constructores de las tablas del MVP a partir de los CSV crudos.

Cada builder es una funcion pura: recibe DataFrames y devuelve un DataFrame.
Los campos sinteticos consumen un unico `numpy.random.Generator` sobre datos
ordenados de forma determinista.
"""

import math
from pathlib import Path

import pandas as pd

from app.dataprep import config

_CITY_TO_WAREHOUSE = {v["city_id"]: v["warehouse_id"] for v in config.CITY_MAP.values()}
_CITY_CYCLE = ["PUNE", "CHEN", "DHAR"]


# --------------------------------------------------------------------------- #
# Carga de fuentes
# --------------------------------------------------------------------------- #

def load_spine(raw_dir: Path) -> pd.DataFrame:
    """Dataset columna vertebral: consumo diario de repuestos MRO por planta."""
    df = pd.read_csv(raw_dir / "synthetic_industrial_machine_data.csv")
    df["transaction_date"] = pd.to_datetime(df["transaction_date"])
    df["breakdown_flag"] = df["breakdown_flag"].fillna(0).astype(int)
    return df


def load_procurement(raw_dir: Path) -> pd.DataFrame:
    """Ordenes de compra historicas: fuente de proveedores y lead time real."""
    df = pd.read_csv(raw_dir / "Procurement KPI Analysis Dataset.csv")
    df["Order_Date"] = pd.to_datetime(df["Order_Date"], errors="coerce")
    df["Delivery_Date"] = pd.to_datetime(df["Delivery_Date"], errors="coerce")
    return df


# --------------------------------------------------------------------------- #
# Entrada 1: maestro de piezas
# --------------------------------------------------------------------------- #

def build_cities() -> pd.DataFrame:
    rows = [config.CITY_MAP[p] for p in ("PUN-01", "CHN-02", "DHR-03")]
    return pd.DataFrame(rows)[["city_id", "city_name", "country", "warehouse_id"]]


def build_parts_master(spine: pd.DataFrame) -> pd.DataFrame:
    cols = ["part_no", "part_description", "part_family", "criticality", "uom", "unit_cost_inr"]
    parts = spine[cols].drop_duplicates("part_no").sort_values("part_no").reset_index(drop=True)
    return pd.DataFrame({
        "sku_id": parts["part_no"],
        "description": parts["part_description"],
        "category": parts["part_family"],
        "criticality": parts["criticality"],
        "uom": parts["uom"],
        "unit_cost_usd": (parts["unit_cost_inr"] * config.INR_TO_USD).round(2),
        "currency": "USD",
        "shelf_life_days": parts["part_family"].map(config.SHELF_LIFE_BY_FAMILY).astype(int),
    })


# --------------------------------------------------------------------------- #
# Entrada 3: demanda historica y señal operativa
# --------------------------------------------------------------------------- #

def build_demand_history(spine: pd.DataFrame) -> pd.DataFrame:
    """Agrega el consumo diario a grano sku x ciudad x mes."""
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


# --------------------------------------------------------------------------- #
# Entrada 2: inventario actual
# --------------------------------------------------------------------------- #

def build_inventory_current(parts: pd.DataFrame, demand: pd.DataFrame, rng) -> pd.DataFrame:
    """Stock por sku x ciudad.

    El dato crudo registra consumo, no existencias: on_hand y los puntos de
    reorden se sintetizan a partir de la estadistica mensual de demanda.
    """
    snapshot = demand["period_month"].max() + "-28"
    criticality = dict(zip(parts["sku_id"], parts["criticality"]))
    unit_costs = dict(zip(parts["sku_id"], parts["unit_cost_usd"]))

    stats = (
        demand.groupby(["sku_id", "city_id"])["qty_issued"]
        .agg(mu="mean", sigma=lambda s: float(s.std(ddof=0)))
        .reset_index()
        .sort_values(["sku_id", "city_id"])
        .reset_index(drop=True)
    )

    rows = []
    for _, r in stats.iterrows():
        sku, city, mu, sigma = r["sku_id"], r["city_id"], r["mu"], r["sigma"]
        z = config.Z_BY_CRITICALITY[criticality[sku]]
        reorder_point = math.ceil(mu + z * sigma)
        reorder_qty = max(1, math.ceil(mu))
        # Cobertura relativa al punto de reorden, no a la media: deja el stock
        # repartido a ambos lados del umbral para que el motor de reglas
        # ejercite tanto el caso "comprar" como el caso "no comprar".
        coverage = float(rng.uniform(*config.COVERAGE_RANGE))
        on_hand = int(round(reorder_point * coverage))
        unit_cost = unit_costs[sku]
        rows.append({
            "sku_id": sku,
            "city_id": city,
            "warehouse_id": _CITY_TO_WAREHOUSE[city],
            "snapshot_date": snapshot,
            "on_hand_qty": on_hand,
            "reorder_point": reorder_point,
            "reorder_qty": reorder_qty,
            "unit_cost_usd": unit_cost,
            "stock_value_usd": round(on_hand * unit_cost, 2),
            "below_reorder": int(on_hand < reorder_point),
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Entrada 4: proveedores y ofertas
# --------------------------------------------------------------------------- #

def build_suppliers(procurement: pd.DataFrame) -> pd.DataFrame:
    """Proveedores con lead time derivado de Order_Date -> Delivery_Date."""
    df = procurement.dropna(subset=["Order_Date", "Delivery_Date"]).copy()
    df["lead_days"] = (df["Delivery_Date"] - df["Order_Date"]).dt.days
    df = df[df["lead_days"] > 0]

    rows = []
    for i, name in enumerate(sorted(procurement["Supplier"].unique())):
        lead = df.loc[df["Supplier"] == name, "lead_days"]
        slug = name.lower().replace("_", "-")
        rows.append({
            "supplier_id": f"SUP-{i + 1:02d}",
            "name": name,
            "city_id": _CITY_CYCLE[i % len(_CITY_CYCLE)],
            "active": True,
            "contact_email": f"ordenes@{slug}.com",
            "lead_time_avg_days": round(float(lead.mean()), 1),
            "lead_time_min_days": int(lead.min()),
            "lead_time_max_days": int(lead.max()),
            "lead_time_std_days": round(float(lead.std(ddof=0)), 2),
        })
    return pd.DataFrame(rows)


def build_supplier_offers(parts: pd.DataFrame, demand: pd.DataFrame,
                          suppliers: pd.DataFrame, rng) -> pd.DataFrame:
    """Catalogo proveedor-pieza: 2 o 3 ofertas por sku para dar eleccion al optimizador."""
    supplier_ids = list(suppliers["supplier_id"])
    markup = {sid: round(1.05 + 0.03 * i, 4) for i, sid in enumerate(supplier_ids)}
    freight = {sid: round(10 + 5 * i, 2) for i, sid in enumerate(supplier_ids)}
    unit_costs = dict(zip(parts["sku_id"], parts["unit_cost_usd"]))
    max_demand = demand.groupby("sku_id")["qty_issued"].max().to_dict()

    rows = []
    for sku in sorted(parts["sku_id"]):
        n_offers = int(rng.integers(2, 4))
        chosen = rng.choice(supplier_ids, size=n_offers, replace=False)
        unit_cost = unit_costs[sku]
        # Piezas baratas se compran en lote grande; las caras, de a pocas.
        moq = min(100, max(1, int(round(200 / max(unit_cost, 1)))))
        capacity = max(int(max_demand.get(sku, 0)), moq) * 3
        for sid in chosen:
            rows.append({
                "offer_id": f"{sid}_{sku}",
                "supplier_id": sid,
                "sku_id": sku,
                "unit_price_usd": round(unit_cost * markup[sid], 2),
                "moq": moq,
                "capacity_per_month": capacity,
                "freight_cost_usd": freight[sid],
                "currency": "USD",
            })
    return pd.DataFrame(rows).sort_values(["sku_id", "supplier_id"]).reset_index(drop=True)
