"""Tests del optimizador de abastecimiento."""

import math

import pandas as pd
import pytest

from app.core import optimization as config
from app.core.dataset import CITY_IDS, OUT_DIR
from app.core.optimization import (
    COLUMNS,
    build_recommendations,
    candidate_offers,
    consumable_within_shelf_life,
    economic_order_quantity,
    replenishment_level,
    solve_single_purchase,
)


def _offer(offer_id, supplier_id, price, moq, capacity, freight):
    return {
        "offer_id": offer_id,
        "supplier_id": supplier_id,
        "sku_id": "SKU-1",
        "unit_price_usd": price,
        "moq": moq,
        "capacity_per_month": capacity,
        "freight_cost_usd": freight,
        "name": supplier_id,
        "lead_time_days": 10.0,
    }


@pytest.fixture(scope="module")
def published():
    names = [
        "inventory_current.csv",
        "demand_forecast.csv",
        "parts_master.csv",
        "supplier_offers.csv",
        "supplier_coverage.csv",
        "suppliers.csv",
    ]
    return {name: pd.read_csv(OUT_DIR / name) for name in names}


@pytest.fixture(scope="module")
def recommendations(published):
    return build_recommendations(
        published["inventory_current.csv"],
        published["demand_forecast.csv"],
        published["parts_master.csv"],
        published["supplier_offers.csv"],
        published["supplier_coverage.csv"],
        published["suppliers.csv"],
    )


def test_cheapest_supplier_is_selected():
    offers = pd.DataFrame(
        [
            _offer("A", "SUP-01", 10.0, 1, 100, 5.0),
            _offer("B", "SUP-02", 8.0, 1, 100, 5.0),
        ]
    )
    result = solve_single_purchase(need=10, ceiling=20, offers=offers)
    assert result["offer"]["supplier_id"] == "SUP-02"
    assert result["total_cost"] == pytest.approx(85.0)


def test_freight_can_outweigh_a_lower_unit_price():
    """Un proveedor mas barato por unidad puede salir caro con flete alto."""
    offers = pd.DataFrame(
        [
            _offer("A", "SUP-01", 10.0, 1, 100, 1.0),
            _offer("B", "SUP-02", 9.0, 1, 100, 90.0),
        ]
    )
    result = solve_single_purchase(need=5, ceiling=20, offers=offers)
    assert result["offer"]["supplier_id"] == "SUP-01"


def test_minimum_order_quantity_is_respected():
    offers = pd.DataFrame([_offer("A", "SUP-01", 2.0, 25, 500, 5.0)])
    result = solve_single_purchase(need=3, ceiling=100, offers=offers)
    assert result["quantity"] >= 25


def test_supplier_capacity_is_respected():
    offers = pd.DataFrame(
        [
            _offer("A", "SUP-01", 1.0, 1, 10, 5.0),
            _offer("B", "SUP-02", 50.0, 1, 500, 5.0),
        ]
    )
    result = solve_single_purchase(need=40, ceiling=60, offers=offers)
    assert result["offer"]["supplier_id"] == "SUP-02", "el barato no tiene capacidad"


def test_ceiling_is_never_exceeded():
    offers = pd.DataFrame([_offer("A", "SUP-01", 1.0, 1, 500, 5.0)])
    result = solve_single_purchase(need=5, ceiling=12, offers=offers)
    assert result["quantity"] <= 12


def test_purchase_is_infeasible_when_moq_exceeds_the_ceiling():
    offers = pd.DataFrame([_offer("A", "SUP-01", 1.0, 50, 500, 5.0)])
    assert solve_single_purchase(need=5, ceiling=10, offers=offers)["quantity"] == 0


def test_shelf_life_limits_the_purchase():
    """Una pieza de vida corta no admite comprar mas de lo que se consume."""
    limit = consumable_within_shelf_life(monthly_demand=30.0, shelf_life_days=180, on_hand=0)
    assert limit == int(30.0 / 30 * 180 * config.SHELF_LIFE_SAFETY_RATIO)
    assert consumable_within_shelf_life(30.0, 180, on_hand=1000) == 0


def test_shelf_life_is_stricter_for_perishable_parts():
    perishable = consumable_within_shelf_life(30.0, 180, 0)
    durable = consumable_within_shelf_life(30.0, 3650, 0)
    assert durable > perishable


def test_the_replenishment_level_never_falls_below_the_minimum():
    level = replenishment_level(
        monthly_demand=0.0, inventory_min=40, unit_cost_usd=10.0, order_cost_usd=30.0
    )
    assert level["level"] >= 40


def test_the_replenishment_level_scales_with_demand():
    high = replenishment_level(100.0, 10, 10.0, 30.0)["level"]
    low = replenishment_level(10.0, 10, 10.0, 30.0)["level"]
    assert high > low


def test_the_economic_quantity_grows_with_freight_and_shrinks_with_value():
    """Es la tension que la formula de Wilson resuelve: flete contra bodega."""
    base = economic_order_quantity(monthly_demand=20.0, unit_cost_usd=10.0, order_cost_usd=30.0)
    pricier_freight = economic_order_quantity(20.0, 10.0, 120.0)
    pricier_part = economic_order_quantity(20.0, 40.0, 30.0)

    assert pricier_freight > base
    assert pricier_part < base


def test_the_economic_quantity_matches_the_closed_form():
    """Q* = sqrt(2*K*D/h), con h = tasa anual por el valor de la pieza."""
    quantity = economic_order_quantity(monthly_demand=20.0, unit_cost_usd=10.0, order_cost_usd=30.0)
    annual = 20.0 * config.MONTHS_PER_YEAR
    holding = 10.0 * config.HOLDING_COST_RATE_ANNUAL

    assert quantity == pytest.approx(math.sqrt(2 * 30.0 * annual / holding))


def test_without_freight_or_value_there_is_no_economic_quantity():
    """Sin las dos mitades del equilibrio la formula no significa nada."""
    assert economic_order_quantity(20.0, 10.0, 0.0) == 0.0
    assert economic_order_quantity(20.0, 0.0, 30.0) == 0.0
    assert economic_order_quantity(0.0, 10.0, 30.0) == 0.0


def test_the_obsolescence_cap_bounds_the_economic_quantity():
    """Una pieza barata con flete caro pediria mas de un año de consumo."""
    level = replenishment_level(
        monthly_demand=10.0, inventory_min=5, unit_cost_usd=0.10, order_cost_usd=80.0
    )

    assert level["eoq_raw"] > level["coverage_cap_units"]
    assert level["eoq_units"] == level["coverage_cap_units"]
    assert level["eoq_units"] == int(10.0 * config.EOQ_MAX_COVERAGE_MONTHS)


def test_candidate_offers_cover_every_city(published):
    """El bloqueante de cobertura debe estar resuelto para todas las piezas."""
    for city in CITY_IDS:
        for sku in published["parts_master.csv"]["sku_id"]:
            applicable = candidate_offers(
                sku,
                city,
                published["supplier_offers.csv"],
                published["supplier_coverage.csv"],
                published["suppliers.csv"],
            )
            assert not applicable.empty, f"{sku} en {city} se quedo sin proveedor"


def test_remote_delivery_costs_more_and_takes_longer(published):
    coverage = published["supplier_coverage.csv"]
    home = coverage[coverage["is_home"] == 1]
    remote = coverage[coverage["is_home"] == 0]
    assert remote["freight_cost_usd"].mean() > home["freight_cost_usd"].mean()
    assert (remote["lead_time_extra_days"] > 0).all()
    assert (home["lead_time_extra_days"] == 0).all()


def test_recommendations_cover_every_series(recommendations):
    assert len(recommendations) == 20 * len(CITY_IDS)
    assert list(recommendations.columns) == COLUMNS
    assert not recommendations.duplicated(["sku_id", "city_id"]).any()


def test_every_decision_is_a_known_state(recommendations):
    valid = {
        config.DECISION_BUY,
        config.DECISION_HOLD,
        config.DECISION_REVIEW,
        config.DECISION_DEFERRED,
    }
    assert set(recommendations["decision"]).issubset(valid)


def test_every_row_carries_a_reason(recommendations):
    assert recommendations["reason"].notna().all()
    assert (recommendations["reason"].str.len() > 10).all()


def test_purchases_have_a_supplier_and_a_cost(recommendations):
    buy = recommendations[recommendations["decision"] == config.DECISION_BUY]
    assert len(buy) > 0, "el dataset debe producir compras para ser demostrable"
    assert buy["supplier_id"].notna().all()
    assert (buy["recommended_qty"] > 0).all()
    assert (buy["total_cost_usd"] > 0).all()


def test_no_purchase_rows_have_no_supplier(recommendations):
    hold = recommendations[recommendations["decision"] == config.DECISION_HOLD]
    assert hold["supplier_id"].isna().all()
    assert (hold["recommended_qty"] == 0).all()


def test_purchases_reach_the_minimum_without_passing_the_maximum(recommendations):
    buy = recommendations[recommendations["decision"] == config.DECISION_BUY]
    resulting = buy["on_hand_qty"] + buy["recommended_qty"]
    assert (resulting >= buy["inventory_min"]).all(), "una compra debe cubrir el minimo"
    assert (resulting <= buy["inventory_max"]).all(), "una compra no debe pasar el maximo"


def test_dataset_exercises_both_branches_of_the_decision(recommendations):
    """La demo pierde valor si todo se compra o nada se compra."""
    share = (recommendations["decision"] == config.DECISION_BUY).mean()
    assert 0.05 <= share <= 0.80, f"reparto sesgado: {share:.0%} de compras"


def test_review_cases_are_flagged_and_explained(recommendations):
    review = recommendations[recommendations["decision"] == config.DECISION_REVIEW]
    assert (review["needs_review"] == 1).all()
    assert review["reason"].str.contains("minimum order quantity").all()


def test_low_confidence_purchases_are_flagged(recommendations):
    risky = recommendations[
        (recommendations["decision"] == config.DECISION_BUY) & (recommendations["confidence"] < 0.5)
    ]
    assert (risky["needs_review"] == 1).all()


def test_recommendations_are_deterministic(published):
    first = build_recommendations(
        published["inventory_current.csv"],
        published["demand_forecast.csv"],
        published["parts_master.csv"],
        published["supplier_offers.csv"],
        published["supplier_coverage.csv"],
        published["suppliers.csv"],
    )
    second = build_recommendations(
        published["inventory_current.csv"],
        published["demand_forecast.csv"],
        published["parts_master.csv"],
        published["supplier_offers.csv"],
        published["supplier_coverage.csv"],
        published["suppliers.csv"],
    )
    assert first.equals(second)
