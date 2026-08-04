"""Tests de la proyeccion de demanda y la politica de inventario."""

import numpy as np
import pandas as pd
import pytest

from app.core import patterns as config
from app.core.dataset import CITY_IDS, OUT_DIR
from app.core.forecast import (
    COLUMNS,
    adjust_confidence,
    backtest_wmape,
    build_demand_forecast,
    forecast_seasonal,
    forecast_series,
    forecast_stable,
    forecast_trend,
    forecast_volatile,
)
from app.core.inventory import (
    inventory_minimum,
    monthly_to_daily,
    planning_lead_time,
    safety_stock,
)

MONTHS = 36


def _months(n=MONTHS):
    return np.arange(n, dtype=float)


@pytest.fixture(scope="module")
def published():
    names = ["demand_history.csv", "demand_patterns.csv", "parts_master.csv",
             "suppliers.csv", "inventory_current.csv"]
    return {name: pd.read_csv(OUT_DIR / name) for name in names}


@pytest.fixture(scope="module")
def forecast(published):
    return build_demand_forecast(
        published["demand_history.csv"],
        published["demand_patterns.csv"],
        published["parts_master.csv"],
        published["suppliers.csv"],
    )


def test_stable_forecast_tracks_the_mean():
    values = np.full(MONTHS, 20.0)
    q25, q50, q75 = forecast_stable(values)
    assert q50 == pytest.approx(20.0)
    assert q25 == pytest.approx(20.0)
    assert q75 == pytest.approx(20.0)


def test_volatile_forecast_uses_robust_percentiles():
    values = np.array([5, 5, 5, 5, 5, 200], dtype=float)
    q25, q50, q75 = forecast_volatile(values)
    assert q50 < 50, "la mediana no debe dejarse arrastrar por un mes extremo"
    assert q25 <= q50 <= q75


def test_trend_forecast_extends_the_ramp():
    values = 10 + 2 * _months()
    _, q50, _ = forecast_trend(values)
    assert q50 > values[-1], "una serie creciente debe proyectar por encima del ultimo mes"


def test_seasonal_forecast_follows_the_cycle():
    cycle = 50 + 20 * np.sin(2 * np.pi * _months() / 12)
    _, q50, _ = forecast_seasonal(cycle)
    expected = 50 + 20 * np.sin(2 * np.pi * MONTHS / 12)
    assert abs(q50 - expected) < 12


def test_seasonal_falls_back_when_history_is_short():
    values = np.array([4, 6, 5, 7, 6, 5], dtype=float)
    assert forecast_seasonal(values) == forecast_stable(values)


def test_quantiles_are_ordered_and_non_negative():
    rng = np.random.default_rng(5)
    for pattern in (config.STABLE, config.VOLATILE, config.TREND, config.SEASONAL):
        values = np.abs(rng.normal(10, 8, MONTHS))
        q25, q50, q75 = forecast_series(values, pattern)
        assert 0 <= q25 <= q50 <= q75, f"cuartiles mal ordenados en {pattern}"


def test_insufficient_pattern_is_not_projected():
    assert forecast_series(np.full(MONTHS, 9.0), config.INSUFFICIENT) == (0.0, 0.0, 0.0)


def test_backtest_is_near_zero_on_a_predictable_series():
    assert backtest_wmape(np.full(MONTHS, 15.0), config.STABLE) == pytest.approx(0.0, abs=1e-6)


def test_backtest_returns_nan_without_enough_history():
    assert np.isnan(backtest_wmape(np.full(10, 5.0), config.STABLE))


def test_confidence_drops_when_the_method_failed():
    assert adjust_confidence(0.9, 0.10) == 0.9
    assert adjust_confidence(0.9, 0.40) < 0.9
    assert adjust_confidence(0.9, 0.80) < adjust_confidence(0.9, 0.40)


def test_confidence_survives_a_missing_backtest():
    assert adjust_confidence(0.77, float("nan")) == 0.77


def test_safety_stock_grows_with_delivery_variability():
    steady = safety_stock(2.0, 0.5, 11.0, 0.0, 1.65)
    erratic = safety_stock(2.0, 0.5, 11.0, 6.0, 1.65)
    assert erratic > steady, "un proveedor irregular exige mas colchon"


def test_safety_stock_grows_with_service_level():
    critical = safety_stock(2.0, 0.5, 11.0, 5.0, 1.65)
    ordinary = safety_stock(2.0, 0.5, 11.0, 5.0, 0.84)
    assert critical > ordinary


def test_monthly_to_daily_conversion():
    daily_mean, daily_std = monthly_to_daily(30.0, np.sqrt(30.0))
    assert daily_mean == pytest.approx(1.0)
    assert daily_std == pytest.approx(1.0)


def test_inventory_minimum_covers_lead_time_demand():
    demand_lt, buffer, minimum = inventory_minimum(30.0, 6.0, 30.0, 2.0, 1.65)
    assert demand_lt == pytest.approx(30.0)
    assert buffer > 0
    assert minimum >= demand_lt


def test_forecast_has_one_row_per_series(forecast):
    assert len(forecast) == 20 * len(CITY_IDS)
    assert list(forecast.columns) == COLUMNS
    assert not forecast.duplicated(["sku_id", "city_id"]).any()


def test_published_forecast_values_are_sane(forecast):
    assert (forecast["forecast_q25"] <= forecast["forecast_q50"]).all()
    assert (forecast["forecast_q50"] <= forecast["forecast_q75"]).all()
    assert (forecast["forecast_q25"] >= 0).all()
    assert (forecast["inventory_min"] >= 0).all()
    assert forecast["confidence_final"].between(0, 1).all()


def test_method_matches_the_classified_pattern(forecast):
    for _, record in forecast.iterrows():
        assert record["method"] == config.RECOMMENDED_MODEL[record["pattern"]]


def test_low_confidence_series_are_flagged(forecast):
    flagged = forecast[forecast["confidence_final"] < 0.5]
    assert (flagged["needs_review"] == 1).all()


def test_inventory_minimum_has_no_systematic_bias_against_reorder_point(published, forecast):
    """El dataset y la proyeccion deben compartir la definicion de minimo.

    Antes convivian dos definiciones distintas: el dataset cubria un mes
    completo de demanda y la proyeccion solo el plazo de entrega, lo que dejaba
    el umbral del dataset casi al doble y hacia que ambas etapas dieran
    respuestas opuestas sobre que piezas reponer.

    Con la politica unificada solo deben quedar diferencias por serie, ya que el
    dataset parte de la media historica y la proyeccion mira hacia adelante. Lo
    que no puede reaparecer es un sesgo sistematico entre ambas.
    """
    merged = published["inventory_current.csv"].merge(forecast, on=["sku_id", "city_id"])
    ratio = merged["reorder_point"] / merged["inventory_min"].clip(lower=1)
    assert 0.85 <= ratio.median() <= 1.15, f"sesgo sistematico: ratio {ratio.median():.2f}"
    assert merged["reorder_point"].corr(merged["inventory_min"]) > 0.90


def test_forecast_is_deterministic(published):
    first = build_demand_forecast(
        published["demand_history.csv"], published["demand_patterns.csv"],
        published["parts_master.csv"], published["suppliers.csv"],
    )
    second = build_demand_forecast(
        published["demand_history.csv"], published["demand_patterns.csv"],
        published["parts_master.csv"], published["suppliers.csv"],
    )
    assert first.equals(second)


def test_planning_lead_time_matches_the_catalog(published):
    lead_time, lead_std = planning_lead_time(published["suppliers.csv"])
    assert lead_time == pytest.approx(published["suppliers.csv"]["lead_time_avg_days"].mean())
    assert lead_std > 0
