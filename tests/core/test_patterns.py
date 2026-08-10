"""Tests del clasificador de patrones de demanda.

La prueba de fondo son las series de control: se construyen series con un
patron conocido y se verifica que el clasificador lo reconoce.
"""

import numpy as np
import pandas as pd
import pytest

from app.core import patterns as config
from app.core.dataset import CITY_IDS, OUT_DIR
from app.core.patterns import (
    COLUMNS,
    build_demand_patterns,
    classify_series,
    confidence_score,
    seasonal_strength,
    seasonality_pvalue,
    trend_test,
)

MONTHS = 36


def _months(n=MONTHS):
    return np.arange(n)


# --------------------------------------------------------------------------- #
# Series de control: patron conocido -> etiqueta esperada
# --------------------------------------------------------------------------- #


def test_sine_wave_is_classified_seasonal():
    values = 50 + 20 * np.sin(2 * np.pi * _months() / 12)
    assert classify_series(values)["pattern"] == config.SEASONAL


def test_rising_ramp_is_classified_trend():
    values = 10 + 2 * _months()
    assert classify_series(values)["pattern"] == config.TREND


def test_falling_ramp_is_classified_trend():
    result = classify_series(100 - 2 * _months())
    assert result["pattern"] == config.TREND
    assert result["trend_tau"] < 0, "una serie decreciente debe dar tau negativo"


def test_flat_noise_is_classified_stable():
    rng = np.random.default_rng(7)
    values = 100 + rng.normal(0, 3, MONTHS)
    assert classify_series(values)["pattern"] == config.STABLE


def test_erratic_series_is_classified_volatile():
    rng = np.random.default_rng(11)
    values = np.abs(rng.normal(50, 60, MONTHS))
    result = classify_series(values)
    assert result["cv"] > config.CV_VOLATILE
    assert result["pattern"] in {config.VOLATILE, config.SEASONAL, config.TREND}


def test_short_series_is_insufficient():
    result = classify_series([5, 7, 6])
    assert result["pattern"] == config.INSUFFICIENT
    assert result["confidence"] == 0.0
    assert result["recommended_model"] == "manual_input"


def test_series_without_demand_is_insufficient():
    """Sin consumo no hay nada que proyectar, por larga que sea la serie."""
    result = classify_series(np.zeros(MONTHS))
    assert result["pattern"] == config.INSUFFICIENT
    assert result["zero_ratio"] == 1.0


def test_constant_series_does_not_crash():
    result = classify_series(np.full(MONTHS, 42.0))
    assert result["cv"] == 0.0
    assert result["pattern"] == config.STABLE


# --------------------------------------------------------------------------- #
# Precedencia: el punto de diseño que el spec no define
# --------------------------------------------------------------------------- #


def test_seasonal_wins_over_volatile():
    """Una serie estacional tiene CV alto por definicion.

    Si 'volatil' se evaluara primero, la estacionalidad no se detectaria nunca.
    """
    values = 50 + 45 * np.sin(2 * np.pi * _months() / 12)
    result = classify_series(values)
    assert result["cv"] > config.CV_VOLATILE, "la serie de control debe ser de CV alto"
    assert result["pattern"] == config.SEASONAL


def test_trend_wins_over_volatile():
    values = 5 + 6 * _months()
    result = classify_series(values)
    assert result["cv"] > config.CV_VOLATILE
    assert result["pattern"] == config.TREND


# --------------------------------------------------------------------------- #
# Señales individuales
# --------------------------------------------------------------------------- #


def test_seasonal_strength_high_for_cycle_low_for_noise():
    rng = np.random.default_rng(3)
    cycle = 50 + 20 * np.sin(2 * np.pi * _months() / 12)
    noise = 50 + rng.normal(0, 20, MONTHS)
    assert seasonal_strength(cycle) > seasonal_strength(noise)


def test_seasonal_strength_zero_when_series_too_short():
    assert seasonal_strength(np.arange(10, dtype=float)) == 0.0


def test_noise_is_rarely_labelled_seasonal():
    """Blindaje de la calibracion (ver nota en config.py).

    Con solo 3 ciclos, la fuerza estacional por si sola marca ruido puro como
    estacional en ~26% de los casos. La regla combinada debe mantener ese error
    por debajo del 10%. Si este test empieza a fallar, alguien relajo un umbral.
    """
    rng = np.random.default_rng(42)
    labels = [classify_series(rng.poisson(6, 37).astype(float))["pattern"] for _ in range(200)]
    false_positives = labels.count(config.SEASONAL) / len(labels)
    assert false_positives < 0.10, f"falsos positivos estacionales: {false_positives:.0%}"


def test_real_seasonality_is_still_detected():
    """El filtro anti-ruido no debe cegar al clasificador."""
    rng = np.random.default_rng(17)
    t = np.arange(37)
    detected = [
        classify_series(50 + 10 * np.sin(2 * np.pi * t / 12) + rng.normal(0, 5, 37))["pattern"]
        for _ in range(50)
    ]
    assert detected.count(config.SEASONAL) / len(detected) > 0.90


def test_seasonality_pvalue_separates_signal_from_noise():
    rng = np.random.default_rng(3)
    t = np.arange(36)
    cycle = 50 + 20 * np.sin(2 * np.pi * t / 12)
    assert seasonality_pvalue(cycle) < config.SEASONAL_PVALUE_MAX
    assert seasonality_pvalue(rng.normal(50, 10, 36)) > config.SEASONAL_PVALUE_MAX


def test_seasonality_pvalue_is_one_when_too_short():
    assert seasonality_pvalue(np.arange(10, dtype=float)) == 1.0


def test_trend_test_detects_direction():
    tau_up, p_up = trend_test(np.arange(MONTHS, dtype=float))
    tau_down, _ = trend_test(np.arange(MONTHS, 0, -1, dtype=float))
    assert tau_up > 0 and p_up < config.TREND_PVALUE_MAX
    assert tau_down < 0


def test_trend_test_on_flat_series_is_not_significant():
    _, pvalue = trend_test(np.full(MONTHS, 10.0))
    assert pvalue >= config.TREND_PVALUE_MAX


def test_confidence_rewards_history_and_penalises_volatility():
    steady = np.full(MONTHS, 20.0)
    assert confidence_score(MONTHS, 0.1, steady) > confidence_score(6, 0.1, steady[:6])
    assert confidence_score(MONTHS, 0.1, steady) > confidence_score(MONTHS, 1.5, steady)


def test_confidence_is_bounded():
    rng = np.random.default_rng(5)
    for cv in (0.0, 0.4, 0.9, 3.0):
        score = confidence_score(MONTHS, cv, rng.normal(30, 5, MONTHS))
        assert 0.0 <= score <= 1.0


def test_recent_shift_lowers_confidence():
    stable = np.full(MONTHS, 20.0)
    shifted = stable.copy()
    shifted[-config.RECENT_WINDOW :] = 60.0  # el patron cambia al final
    assert confidence_score(MONTHS, 0.1, shifted) < confidence_score(MONTHS, 0.1, stable)


# --------------------------------------------------------------------------- #
# Integracion con el dataset real
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def real_patterns():
    demand = pd.read_csv(OUT_DIR / "demand_history.csv")
    return build_demand_patterns(demand)


def test_one_row_per_series(real_patterns):
    assert len(real_patterns) == 20 * len(CITY_IDS)
    assert not real_patterns.duplicated(["sku_id", "city_id"]).any()
    assert list(real_patterns.columns) == COLUMNS


def test_every_series_gets_a_valid_label(real_patterns):
    assert set(real_patterns["pattern"]).issubset(set(config.PRECEDENCE))
    assert real_patterns["recommended_model"].notna().all()
    assert real_patterns["confidence"].between(0, 1).all()


def test_no_series_is_insufficient(real_patterns):
    """Con la historia disponible ninguna serie deberia quedar sin clasificar."""
    assert (real_patterns["pattern"] != config.INSUFFICIENT).all()


def test_label_matches_recommended_model(real_patterns):
    for _, r in real_patterns.iterrows():
        assert r["recommended_model"] == config.RECOMMENDED_MODEL[r["pattern"]]


def test_classification_is_deterministic(real_patterns):
    demand = pd.read_csv(OUT_DIR / "demand_history.csv")
    assert build_demand_patterns(demand).equals(real_patterns)
