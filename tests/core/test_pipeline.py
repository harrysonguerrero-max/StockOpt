"""Tests de los resumenes por etapa del pipeline."""

import pandas as pd
import pytest

from app.core import pipeline
from app.core.optimization import (
    DECISION_BUY,
    DECISION_HOLD,
    DECISION_REVIEW,
    REASON_ABOVE_MINIMUM,
    REASON_LOW_CONFIDENCE,
)


@pytest.fixture
def quality_report():
    return {
        "antes": {
            "spine": {"name": "crudo.csv", "rows": 1000, "columns": 5},
            "compras": {"name": "compras.csv", "rows": 100, "columns": 4},
        },
        "despues": {
            "spine": {"name": "crudo.csv", "rows": 950, "columns": 6},
            "compras": {"name": "compras.csv", "rows": 80, "columns": 4},
        },
        "limpieza": {
            "spine": [
                {"regla": "Rellenar wo_type nulo con SIN_ORDEN",
                 "motivo": "El nulo significa sin orden", "filas": 700},
                {"regla": "Descartar meses incompletos",
                 "motivo": "Se leerian como caida", "filas": 50},
                {"regla": "RESULTADO", "motivo": "De 1000 quedan 950", "filas": 50},
            ],
            "compras": [
                {"regla": "Conservar solo ordenes entregadas",
                 "motivo": "Una cancelada no evidencia plazo", "filas": 20},
                {"regla": "RESULTADO", "motivo": "De 100 quedan 80", "filas": 20},
            ],
        },
    }


@pytest.fixture
def demand():
    rows = []
    for month, synthetic in [("2025-01", 1), ("2025-02", 1), ("2025-03", 0)]:
        for sku, city in [("MRO-1", "NAVA"), ("MRO-2", "OBRE")]:
            rows.append({"sku_id": sku, "city_id": city, "period_month": month,
                         "qty_issued": 10, "is_synthetic": synthetic})
    return pd.DataFrame(rows)


@pytest.fixture
def tables(demand):
    return {
        "demand_history": demand,
        "parts_master": pd.DataFrame({"sku_id": ["MRO-1", "MRO-2"]}),
        "cities": pd.DataFrame({"city_id": ["NAVA", "OBRE"]}),
        "inventory_current": pd.DataFrame({"sku_id": ["MRO-1"], "city_id": ["NAVA"]}),
        "suppliers": pd.DataFrame({"supplier_id": ["SUP-01"]}),
        "supplier_offers": pd.DataFrame({"offer_id": ["SUP-01_MRO-1"]}),
        "supplier_coverage": pd.DataFrame({"supplier_id": ["SUP-01"]}),
    }


@pytest.fixture
def catalog():
    offers = pd.DataFrame([
        {"sku_id": "MRO-1", "supplier_id": "SUP-01", "unit_price_usd": 10.0,
         "moq": 5, "capacity_per_month": 100},
        {"sku_id": "MRO-1", "supplier_id": "SUP-02", "unit_price_usd": 14.0,
         "moq": 5, "capacity_per_month": 100},
    ])
    coverage = pd.DataFrame([
        {"supplier_id": "SUP-01", "city_id": "NAVA", "freight_cost_usd": 10.0,
         "lead_time_extra_days": 0},
        {"supplier_id": "SUP-02", "city_id": "NAVA", "freight_cost_usd": 20.0,
         "lead_time_extra_days": 2},
    ])
    suppliers = pd.DataFrame([
        {"supplier_id": "SUP-01", "name": "Alpha", "active": True,
         "lead_time_avg_days": 10.0},
        {"supplier_id": "SUP-02", "name": "Beta", "active": True,
         "lead_time_avg_days": 12.0},
    ])
    return offers, coverage, suppliers


@pytest.fixture
def recommendations():
    return pd.DataFrame([
        {"sku_id": "MRO-1", "city_id": "NAVA", "decision": DECISION_BUY,
         "reason": "Quedan 3 unidades y el minimo es 10. Se eligio Alpha",
         "recommended_qty": 10, "supplier_id": "SUP-01", "total_cost_usd": 110.0,
         "stockout_cost_usd": 4500.0, "net_benefit_usd": 4390.0, "needs_review": 0},
        {"sku_id": "MRO-2", "city_id": "NAVA", "decision": DECISION_BUY,
         "reason": f"Quedan 1 unidades y el minimo es 4. {REASON_LOW_CONFIDENCE}",
         "recommended_qty": 5, "supplier_id": "SUP-01", "total_cost_usd": 60.0,
         "stockout_cost_usd": 900.0, "net_benefit_usd": 840.0, "needs_review": 1},
        {"sku_id": "MRO-3", "city_id": "NAVA", "decision": DECISION_HOLD,
         "reason": REASON_ABOVE_MINIMUM, "recommended_qty": 0, "supplier_id": None,
         "total_cost_usd": 0.0, "stockout_cost_usd": 0.0, "net_benefit_usd": 0.0,
         "needs_review": 0},
        {"sku_id": "MRO-4", "city_id": "NAVA", "decision": DECISION_REVIEW,
         "reason": "El minimo de orden de Alpha es 100 unidades y el maximo es 12",
         "recommended_qty": 100, "supplier_id": "SUP-01", "total_cost_usd": 1010.0,
         "stockout_cost_usd": 1200.0, "net_benefit_usd": 190.0, "needs_review": 1},
    ])


def test_adjust_rules_are_not_counted_as_discards(quality_report):
    summary = pipeline.cleaning_summary(quality_report)

    assert summary["rows_before"] == 1100
    assert summary["rows_after"] == 1030
    assert summary["discarded"] == 70
    assert summary["adjusted"] == 700


def test_result_rule_is_excluded_from_the_rule_list(quality_report):
    summary = pipeline.cleaning_summary(quality_report)
    kinds = [rule["kind"] for source in summary["sources"] for rule in source["rules"]]

    assert kinds.count(pipeline.KIND_RESULT) == 2
    assert kinds.count(pipeline.KIND_DISCARD) == 2
    assert kinds.count(pipeline.KIND_ADJUST) == 1


def test_dataset_summary_separates_simulated_from_observed(tables):
    summary = pipeline.dataset_summary(tables)

    assert summary["months"] == 3
    assert summary["series"] == 2
    assert summary["synthetic_rows"] == 4
    assert summary["real_rows"] == 2
    assert [row["is_synthetic"] for row in summary["monthly"]] == [1, 1, 0]
    assert summary["monthly"][0]["qty_issued"] == 20


def test_dataset_summary_survives_history_without_the_flag(tables):
    tables["demand_history"] = tables["demand_history"].drop(columns=["is_synthetic"])
    summary = pipeline.dataset_summary(tables)

    assert summary["synthetic_rows"] == 0
    assert summary["real_rows"] == 6


def test_pattern_summary_reports_the_thresholds_it_applied():
    patterns = pd.DataFrame([
        {"sku_id": "MRO-1", "city_id": "NAVA", "cv": 0.2, "seasonal_strength": 0.6,
         "seasonal_pvalue": 0.01, "confidence": 0.9, "pattern": "Estacional"},
        {"sku_id": "MRO-2", "city_id": "NAVA", "cv": 0.8, "seasonal_strength": 0.1,
         "seasonal_pvalue": 0.7, "confidence": 0.4, "pattern": "Volatil"},
    ])
    summary = pipeline.pattern_summary(patterns)

    assert summary["counts"] == {"Estacional": 1, "Volatil": 1}
    assert summary["thresholds"]["cv_volatile"] == 0.5
    assert summary["thresholds"]["seasonal_strength"] == 0.45
    assert len(summary["points"]) == 2


def test_features_are_grouped_into_readable_families():
    families = pipeline.feature_families(
        ["lag_1", "lag_12", "roll_mean_6", "month_sin", "unit_cost_usd", "rareza"]
    )
    by_name = {family["family"]: family["features"] for family in families}

    assert by_name["Rezagos de la propia serie"] == ["lag_1", "lag_12"]
    assert by_name["Medias y desviaciones moviles"] == ["roll_mean_6"]
    assert by_name[pipeline.OTHER_FAMILY] == ["rareza"]


def test_every_feature_lands_in_exactly_one_family():
    features = ["lag_1", "roll_std_3", "issue_events_lag_1", "breakdown_lag_1",
                "month_cos", "shelf_life_days", "criticality_rank", "is_nava",
                "is_synthetic"]
    grouped = [name for family in pipeline.feature_families(features)
               for name in family["features"]]

    assert sorted(grouped) == sorted(features)


def test_buy_reasons_collapse_into_one_cause():
    first = pipeline.reason_cause(DECISION_BUY, "Quedan 3 unidades y el minimo es 10")
    second = pipeline.reason_cause(DECISION_BUY, "Quedan 7 unidades y el minimo es 40")

    assert first == second


def test_hold_reasons_keep_their_own_cause():
    above = pipeline.reason_cause(DECISION_HOLD, REASON_ABOVE_MINIMUM)
    detailed = pipeline.reason_cause(
        DECISION_HOLD, f"{REASON_ABOVE_MINIMUM} y ademas sobra"
    )

    assert above == REASON_ABOVE_MINIMUM
    assert detailed == REASON_ABOVE_MINIMUM


def test_optimization_summary_groups_by_cause(recommendations, catalog):
    offers, coverage, suppliers = catalog
    summary = pipeline.optimization_summary(recommendations, offers, coverage, suppliers)

    assert summary["counts"][DECISION_BUY] == 2
    assert summary["counts"][DECISION_REVIEW] == 1
    assert summary["counts"][DECISION_HOLD] == 1
    assert len(summary["reasons"]) == 3
    assert summary["reasons"][0]["count"] == 2
    assert summary["low_confidence"] == 1


def test_saving_compares_against_the_worst_applicable_offer(recommendations, catalog):
    offers, coverage, suppliers = catalog
    summary = pipeline.optimization_summary(recommendations, offers, coverage, suppliers)
    saving = next(item for item in summary["savings"] if item["sku_id"] == "MRO-1")

    assert saving["chosen_cost_usd"] == 110.0
    assert saving["worst_cost_usd"] == 160.0
    assert saving["saving_usd"] == 50.0


def test_series_without_offers_are_left_out_of_the_saving(recommendations, catalog):
    offers, coverage, suppliers = catalog
    summary = pipeline.optimization_summary(recommendations, offers, coverage, suppliers)

    assert [item["sku_id"] for item in summary["savings"]] == ["MRO-1"]


def test_trace_returns_nothing_for_an_unknown_combination(demand, recommendations,
                                                          catalog):
    offers, coverage, suppliers = catalog
    empty = pd.DataFrame(columns=["sku_id", "city_id"])

    assert pipeline.trace_part(
        "MRO-99", "NAVA", demand, empty, empty, recommendations,
        offers, coverage, suppliers,
    ) is None


def test_trace_follows_a_piece_through_every_stage(demand, recommendations, catalog):
    offers, coverage, suppliers = catalog
    patterns = pd.DataFrame([{"sku_id": "MRO-1", "city_id": "NAVA",
                              "pattern": "Estable", "cv": 0.2}])
    forecast = pd.DataFrame([{"sku_id": "MRO-1", "city_id": "NAVA",
                              "forecast_q50": 12.0, "inventory_min": 10}])

    trace = pipeline.trace_part("MRO-1", "NAVA", demand, patterns, forecast,
                                recommendations, offers, coverage, suppliers)

    assert len(trace["history"]) == 3
    assert trace["pattern"]["pattern"] == "Estable"
    assert trace["forecast"]["forecast_q50"] == 12.0
    assert trace["decision"]["decision"] == DECISION_BUY
    assert [offer["chosen"] for offer in trace["offers"]] == [True, False]


def test_every_stage_declares_where_its_charts_come_from(quality_report, tables,
                                                         recommendations, catalog):
    patterns = pd.DataFrame([{"sku_id": "MRO-1", "city_id": "NAVA", "cv": 0.2,
                              "seasonal_strength": 0.1, "seasonal_pvalue": 0.5,
                              "confidence": 0.8, "pattern": "Estable"}])
    offers, coverage, suppliers = catalog
    tables["supplier_offers"] = offers
    tables["supplier_coverage"] = coverage
    tables["suppliers"] = suppliers

    stages = pipeline.build_stages(quality_report, tables, patterns, {},
                                   recommendations)

    assert [stage["id"] for stage in stages] == pipeline.STAGE_ORDER
    for stage in stages:
        for chart in stage["charts"]:
            assert chart["source"] in (pipeline.SOURCE_PIPELINE, pipeline.SOURCE_TRAINING)
            if chart["source"] == pipeline.SOURCE_PIPELINE:
                assert chart["key"] in pipeline.CHART_FILES
