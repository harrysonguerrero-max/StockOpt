"""Tests del costo de quiebre y de su efecto sobre la decision de compra."""

import pandas as pd
import pytest

from app.core.optimization import (
    DECISION_BUY,
    DECISION_HOLD,
    PLANNING_PERIOD_DAYS,
    REASON_NOT_WORTH_IT,
    STOCKOUT_COST_PER_DAY_USD,
    days_of_cover,
    stockout_cost,
    stockout_days_avoided,
)


def test_cover_translates_stock_into_days():
    assert days_of_cover(30, 30.0) == pytest.approx(30.0)
    assert days_of_cover(15, 30.0) == pytest.approx(15.0)


def test_a_piece_without_demand_never_runs_out():
    assert days_of_cover(0, 0.0) > PLANNING_PERIOD_DAYS * 10


def test_plenty_of_stock_avoids_no_stockout():
    assert stockout_days_avoided(1000, 10.0, 14.0) == 0.0


def test_an_empty_shelf_saturates_at_one_planning_period():
    assert stockout_days_avoided(0, 30.0, 14.0) == PLANNING_PERIOD_DAYS


def test_avoided_days_never_exceed_the_planning_period():
    for on_hand in range(0, 60, 7):
        for lead in (1.0, 10.6, 20.0):
            avoided = stockout_days_avoided(on_hand, 30.0, lead)
            assert 0.0 <= avoided <= PLANNING_PERIOD_DAYS


def test_a_longer_lead_time_never_reduces_the_exposure():
    corto = stockout_days_avoided(10, 30.0, 5.0)
    largo = stockout_days_avoided(10, 30.0, 20.0)

    assert largo >= corto


def test_criticality_sets_the_price_of_a_day_without_the_part():
    critica = stockout_cost(0, 30.0, 10.0, "A")
    corriente = stockout_cost(0, 30.0, 10.0, "C")

    assert critica == PLANNING_PERIOD_DAYS * STOCKOUT_COST_PER_DAY_USD["A"]
    assert corriente == PLANNING_PERIOD_DAYS * STOCKOUT_COST_PER_DAY_USD["C"]
    assert critica > corriente


def test_an_unknown_criticality_costs_nothing():
    assert stockout_cost(0, 30.0, 10.0, "Z") == 0.0


def test_two_identical_parts_differ_only_by_criticality():
    a = stockout_cost(5, 30.0, 14.0, "A")
    b = stockout_cost(5, 30.0, 14.0, "B")
    c = stockout_cost(5, 30.0, 14.0, "C")

    assert a > b > c


def test_a_purchase_that_costs_more_than_the_stockout_is_dropped(monkeypatch):
    from app.core import optimization

    monkeypatch.setitem(optimization.STOCKOUT_COST_PER_DAY_USD, "C", 0.01)
    barato = optimization.stockout_cost(0, 30.0, 10.0, "C")

    assert barato < 1.0


def test_the_reason_names_the_economics():
    assert "costs" in REASON_NOT_WORTH_IT
    assert "stockout" in REASON_NOT_WORTH_IT


def test_the_recommendation_carries_both_sides_of_the_decision():
    rec = pd.read_csv("app/data/mvp/purchase_recommendations.csv")

    assert "stockout_cost_usd" in rec.columns
    assert "net_benefit_usd" in rec.columns

    buying = rec[rec.decision == DECISION_BUY]
    assert (buying.net_benefit_usd > 0).all()
    assert (buying.stockout_cost_usd > buying.total_cost_usd).all()


def test_critical_parts_are_never_left_out_while_cheaper_ones_are_bought():
    rec = pd.read_csv("app/data/mvp/purchase_recommendations.csv")
    buying = rec[rec.decision == DECISION_BUY]
    hold = rec[(rec.decision == DECISION_HOLD) & (rec.on_hand_qty < rec.inventory_min)]

    if len(buying) and len(hold):
        assert buying.stockout_cost_usd.min() >= hold.stockout_cost_usd.max()
