"""Tests del build del dataset MVP."""

import numpy as np
import pytest

from app.data.build_mvp_dataset import main
from app.services.dataset_builder import FILE_NAMES, build_all
from app.core import dataset_config as config
from app.services.dataset_service import (
    build_demand_history,
    build_inventory_current,
    build_parts_master,
    build_supplier_offers,
    build_suppliers,
    load_procurement,
    load_spine,
)
from app.services.validation_service import validate

FAMILIES = {
    "Bearing", "Coupling", "Drive Belt", "Electrical", "Fastener",
    "Filter", "Lubrication", "Seal & Gasket", "Sensor",
}


@pytest.fixture(scope="module")
def tables():
    return build_all()


# --------------------------------------------------------------------------- #
# Fuentes crudas
# --------------------------------------------------------------------------- #

def test_spine_loads_with_expected_scope():
    spine = load_spine(config.RAW_DIR)
    assert spine["part_no"].nunique() == 20
    assert set(spine["plant_code"]) == {"PUN-01", "CHN-02", "DHR-03"}
    assert (spine["qty_issued"] >= 0).all()


def test_raw_files_are_not_modified_by_build():
    """El build solo lee: los CSV crudos deben quedar intactos."""
    raw = config.RAW_DIR / "synthetic_industrial_machine_data.csv"
    before = raw.stat().st_mtime
    build_all()
    assert raw.stat().st_mtime == before


# --------------------------------------------------------------------------- #
# Entrada 1: maestro de piezas
# --------------------------------------------------------------------------- #

def test_parts_master_scope_and_currency(tables):
    parts = tables["parts"]
    assert len(parts) == 20
    assert parts["sku_id"].is_unique
    assert (parts["currency"] == "USD").all()
    # MRO-10045 cuesta 850 INR en el dato crudo
    row = parts.loc[parts["sku_id"] == "MRO-10045"].iloc[0]
    assert row["unit_cost_usd"] == round(850 / 83, 2)


def test_parts_master_shelf_life_covers_every_family(tables):
    parts = tables["parts"]
    assert set(parts["category"]).issubset(FAMILIES)
    assert (parts["shelf_life_days"] > 0).all()
    assert set(parts["criticality"]).issubset({"A", "B", "C"})


# --------------------------------------------------------------------------- #
# Entrada 2: inventario actual
# --------------------------------------------------------------------------- #

def test_inventory_has_one_row_per_sku_city(tables):
    inv = tables["inventory"]
    assert len(inv) == 20 * len(config.CITY_IDS)
    assert not inv.duplicated(["sku_id", "city_id"]).any()
    assert (inv["on_hand_qty"] >= 0).all()
    assert (inv["reorder_qty"] >= 1).all()


def test_inventory_derived_columns_are_consistent(tables):
    inv = tables["inventory"]
    expected_flag = (inv["on_hand_qty"] < inv["reorder_point"]).astype(int)
    assert (inv["below_reorder"] == expected_flag).all()
    expected_value = (inv["on_hand_qty"] * inv["unit_cost_usd"]).round(2)
    assert (inv["stock_value_usd"] == expected_value).all()


def test_inventory_mixes_both_sides_of_the_reorder_point(tables):
    """El motor de reglas necesita casos que compran y casos que no."""
    below = tables["inventory"]["below_reorder"]
    assert 0.25 <= below.mean() <= 0.75, f"reparto sesgado: {below.mean():.2f} bajo reorden"


# --------------------------------------------------------------------------- #
# Entrada 3: demanda historica
# --------------------------------------------------------------------------- #

def test_demand_preserves_quantity_of_complete_months(tables):
    """El agregado mensual no debe perder ni inventar consumo.

    Solo se excluye lo registrado en meses incompletos, que el build descarta
    para no leerlos como una caida de la demanda.
    """
    spine = load_spine(config.RAW_DIR)
    days = spine.groupby(spine["transaction_date"].dt.strftime("%Y-%m"))["transaction_date"].nunique()
    complete = days[days >= config.MIN_DAYS_PER_MONTH].index
    expected = spine[spine["transaction_date"].dt.strftime("%Y-%m").isin(complete)]["qty_issued"].sum()
    assert tables["demand"]["qty_issued"].sum() == expected


def test_demand_grain_is_sku_city_month(tables):
    demand = tables["demand"]
    assert not demand.duplicated(["sku_id", "city_id", "period_month"]).any()
    assert demand["period_month"].str.match(r"^\d{4}-\d{2}$").all()
    assert (demand["issue_events"] >= 0).all()


def test_demand_covers_at_least_twelve_months(tables):
    """El spec pide 6-12 meses de historico como minimo."""
    assert tables["demand"]["period_month"].nunique() >= 12


def test_demand_ends_at_configured_horizon(tables):
    """La serie debe llegar al mes que exige la operacion."""
    assert tables["demand"]["period_month"].max() == config.DEMAND_HORIZON


def test_cities_are_the_configured_ones(tables):
    cities = tables["cities"]
    assert list(cities["city_id"]) == config.CITY_IDS
    assert (cities["country"] == "Mexico").all()


# --------------------------------------------------------------------------- #
# Entrada 4: proveedores y ofertas
# --------------------------------------------------------------------------- #

def test_suppliers_lead_times_are_ordered(tables):
    sup = tables["suppliers"]
    assert len(sup) == 5
    assert (sup["lead_time_min_days"] > 0).all()
    assert (sup["lead_time_min_days"] <= sup["lead_time_avg_days"]).all()
    assert (sup["lead_time_avg_days"] <= sup["lead_time_max_days"]).all()


def test_every_sku_has_at_least_two_offers(tables):
    counts = tables["offers"].groupby("sku_id").size()
    assert len(counts) == 20
    assert (counts >= 2).all()


def test_offer_price_never_below_cost(tables):
    offers, parts = tables["offers"], tables["parts"]
    cost = dict(zip(parts["sku_id"], parts["unit_cost_usd"]))
    assert all(r["unit_price_usd"] >= cost[r["sku_id"]] for _, r in offers.iterrows())


def test_offer_capacity_meets_peak_demand(tables):
    """Sin capacidad suficiente el MILP seria infactible."""
    peak = tables["demand"].groupby("sku_id")["qty_issued"].max()
    merged = tables["offers"].join(peak.rename("peak"), on="sku_id")
    assert (merged["capacity_per_month"] >= merged["peak"]).all()


# --------------------------------------------------------------------------- #
# Integridad referencial y validacion
# --------------------------------------------------------------------------- #

def test_referential_integrity_holds(tables):
    skus = set(tables["parts"]["sku_id"])
    cities = set(tables["cities"]["city_id"])
    suppliers = set(tables["suppliers"]["supplier_id"])

    assert set(tables["inventory"]["sku_id"]) <= skus
    assert set(tables["demand"]["sku_id"]) <= skus
    assert set(tables["offers"]["sku_id"]) <= skus
    assert set(tables["inventory"]["city_id"]) <= cities
    assert set(tables["demand"]["city_id"]) <= cities
    assert set(tables["offers"]["supplier_id"]) <= suppliers


def test_no_nulls_anywhere(tables):
    for name, df in tables.items():
        assert not df.isna().any().any(), f"{name} contiene nulos"


def test_validate_passes_on_generated_tables(tables):
    assert isinstance(validate(tables), list)


def test_validate_rejects_orphan_sku(tables):
    broken = {k: v.copy() for k, v in tables.items()}
    broken["inventory"].loc[0, "sku_id"] = "MRO-99999"
    with pytest.raises(ValueError, match="Integridad"):
        validate(broken)


def test_validate_rejects_negative_price(tables):
    broken = {k: v.copy() for k, v in tables.items()}
    broken["offers"].loc[0, "unit_price_usd"] = -1
    with pytest.raises(ValueError, match="unit_price_usd"):
        validate(broken)


# --------------------------------------------------------------------------- #
# Determinismo y escritura
# --------------------------------------------------------------------------- #

def test_synthetic_fields_are_deterministic():
    spine = load_spine(config.RAW_DIR)
    parts = build_parts_master(spine)
    demand = build_demand_history(spine)
    suppliers = build_suppliers(load_procurement(config.RAW_DIR))

    first = build_inventory_current(parts, demand, np.random.default_rng(config.SEED))
    second = build_inventory_current(parts, demand, np.random.default_rng(config.SEED))
    assert first.equals(second)

    offers_a = build_supplier_offers(parts, demand, suppliers, np.random.default_rng(config.SEED))
    offers_b = build_supplier_offers(parts, demand, suppliers, np.random.default_rng(config.SEED))
    assert offers_a.equals(offers_b)


def test_main_writes_every_file_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUT_DIR", tmp_path)
    main()
    for filename in list(FILE_NAMES.values()) + ["data_dictionary.md"]:
        assert (tmp_path / filename).exists(), filename

    snapshot = {f: (tmp_path / f).read_bytes() for f in FILE_NAMES.values()}
    main()
    for filename, content in snapshot.items():
        assert (tmp_path / filename).read_bytes() == content, f"{filename} no es idempotente"
