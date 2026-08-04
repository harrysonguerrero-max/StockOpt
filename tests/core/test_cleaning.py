"""Tests del perfilado, la limpieza y la generacion de historia sintetica."""

import numpy as np
import pandas as pd
import pytest

from app.core.cleaning import (
    DELIVERED_STATUSES,
    clean_procurement,
    clean_spine,
    demand_outlier_report,
    flag_sensor_outliers,
)
from app.core.dataset import RAW_DIR
from app.core.patterns import build_demand_patterns
from app.core.profiling import (
    column_profile,
    detect_outliers_iqr,
    detect_outliers_mad,
    duplicate_summary,
    profile_dataset,
    quality_flags,
)
from app.core.synthesis import estimate_process, extend_history, negative_binomial_draw


@pytest.fixture(scope="module")
def procurement_raw():
    return pd.read_csv(RAW_DIR / "Procurement KPI Analysis Dataset.csv")


@pytest.fixture(scope="module")
def spine_raw():
    return pd.read_csv(RAW_DIR / "synthetic_industrial_machine_data.csv")


# --------------------------------------------------------------------------- #
# Perfilado
# --------------------------------------------------------------------------- #

def test_profile_reports_nulls_and_cardinality():
    series = pd.Series([1.0, 2.0, None, 2.0])
    profile = column_profile(series)
    assert profile["nulls"] == 1
    assert profile["null_ratio"] == 0.25
    assert profile["unique"] == 2
    assert profile["mean"] == pytest.approx(1.6667, abs=1e-3)


def test_profile_of_text_column_lists_top_values():
    profile = column_profile(pd.Series(["a", "a", "b"]))
    assert profile["top_values"]["a"] == 2


def test_iqr_flags_an_extreme_value():
    series = pd.Series([10, 11, 10, 12, 11, 500])
    assert detect_outliers_iqr(series).iloc[-1]
    assert not detect_outliers_iqr(series).iloc[0]


def test_mad_resists_contamination():
    """Con varios extremos, la desviacion tipica se infla y el criterio clasico ciega.

    La desviacion absoluta mediana usa la mediana, asi que los extremos no
    desplazan el umbral y siguen detectandose.
    """
    series = pd.Series([10, 10, 10, 10, 10, 10, 900, 950, 1000])
    assert detect_outliers_mad(series).sum() >= 3


def test_outlier_detection_survives_constant_and_short_series():
    assert not detect_outliers_iqr(pd.Series([5, 5, 5, 5])).any()
    assert not detect_outliers_mad(pd.Series([5, 5, 5, 5])).any()
    assert not detect_outliers_iqr(pd.Series([1, 2])).any()


def test_duplicate_summary_separates_exact_from_key():
    frame = pd.DataFrame({"k": [1, 1, 2], "v": [10, 20, 30]})
    result = duplicate_summary(frame, keys=["k"])
    assert result["exact_duplicates"] == 0
    assert result["key_duplicates"] == 1


def test_quality_flags_warn_about_constant_and_negative_columns():
    frame = pd.DataFrame({"constante": [1, 1, 1], "negativa": [-1, 2, 3]})
    profile = {name: column_profile(frame[name]) for name in frame}
    flags = " ".join(quality_flags(frame, profile))
    assert "constante" in flags
    assert "negativa" in flags


def test_profile_dataset_covers_the_real_source(procurement_raw):
    report = profile_dataset(procurement_raw, "procurement", keys=["PO_ID"])
    assert report["rows"] == len(procurement_raw)
    assert "Unit_Price" in report["profile"]
    assert "duplicates" in report


# --------------------------------------------------------------------------- #
# Limpieza
# --------------------------------------------------------------------------- #

def test_cleaning_drops_orders_that_were_never_delivered(procurement_raw):
    """Una orden cancelada con fecha de entrega no evidencia un plazo real.

    El archivo original trae 130 registros asi, y contarlos sesgaba a la baja el
    lead time que despues usa el optimizador.
    """
    clean, log = clean_procurement(procurement_raw)
    assert set(clean["Order_Status"]).issubset(set(DELIVERED_STATUSES))
    assert any("Delivered" in entry["regla"] for entry in log)


def test_cleaning_produces_only_valid_lead_times(procurement_raw):
    clean, _ = clean_procurement(procurement_raw)
    assert (clean["lead_days"] > 0).all()
    assert clean["lead_days"].notna().all()


def test_cleaning_imputes_defects_as_zero(procurement_raw):
    clean, _ = clean_procurement(procurement_raw)
    assert clean["Defective_Units"].notna().all()


def test_cleaning_log_explains_every_rule(procurement_raw):
    _, log = clean_procurement(procurement_raw)
    for entry in log:
        assert entry["regla"] and entry["motivo"]
        assert isinstance(entry["filas"], int)


def test_spine_cleaning_drops_incomplete_months(spine_raw):
    clean, log = clean_spine(spine_raw)
    days = clean.groupby(clean["transaction_date"].dt.strftime("%Y-%m"))["transaction_date"].nunique()
    assert (days >= 20).all()
    assert any("dias registrados" in entry["regla"] for entry in log)


def test_spine_cleaning_keeps_zero_consumption(spine_raw):
    """El consumo cero no es un defecto sino la intermitencia del negocio."""
    clean, _ = clean_spine(spine_raw)
    assert (clean["qty_issued"] == 0).sum() > 0


def test_spine_cleaning_labels_missing_work_order(spine_raw):
    clean, _ = clean_spine(spine_raw)
    assert clean["wo_type"].notna().all()
    assert "SIN_ORDEN" in set(clean["wo_type"])


def test_sensor_outliers_are_flagged_not_removed(spine_raw):
    """Una lectura extrema anticipa la falla: se marca, no se borra."""
    clean, _ = clean_spine(spine_raw)
    flagged, log = flag_sensor_outliers(clean)
    assert len(flagged) == len(clean)
    assert flagged["sensor_outlier"].sum() > 0
    assert log[0]["filas"] == int(flagged["sensor_outlier"].sum())


def test_demand_outlier_report_compares_each_series_with_itself():
    demand = pd.DataFrame({
        "sku_id": ["A"] * 12 + ["B"] * 12,
        "city_id": ["NAVA"] * 24,
        "period_month": [f"2025-{m:02d}" for m in range(1, 13)] * 2,
        "qty_issued": [2] * 11 + [40] + [100] * 12,
    })
    report = demand_outlier_report(demand)
    assert set(report["sku_id"]) == {"A"}, "solo A tiene un mes fuera de su escala"
    assert report.iloc[0]["qty_issued"] == 40


# --------------------------------------------------------------------------- #
# Historia sintetica
# --------------------------------------------------------------------------- #

def test_negative_binomial_reproduces_the_requested_mean():
    rng = np.random.default_rng(1)
    draws = [negative_binomial_draw(20.0, 60.0, rng) for _ in range(4000)]
    assert abs(np.mean(draws) - 20.0) < 1.5
    assert np.var(draws) > 20.0, "debe tener mas dispersion que una Poisson"


def test_negative_binomial_falls_back_when_variance_is_low():
    rng = np.random.default_rng(2)
    draws = [negative_binomial_draw(5.0, 1.0, rng) for _ in range(2000)]
    assert abs(np.mean(draws) - 5.0) < 0.5


def test_process_detects_real_seasonality():
    months = np.arange(48)
    cycle = 50 + 20 * np.sin(2 * np.pi * months / 12)
    assert estimate_process(cycle)["has_season"]


def test_process_does_not_invent_seasonality_on_noise():
    """Es la salvaguarda del metodo.

    Si el proceso inyectara un perfil estacional en series planas, la historia
    generada fabricaria un ciclo inexistente y la clasificacion lo detectaria
    como real.
    """
    rng = np.random.default_rng(7)
    assert not estimate_process(rng.poisson(20, 48).astype(float))["has_season"]


def test_extension_marks_and_places_synthetic_months():
    demand = pd.DataFrame({
        "sku_id": ["A"] * 24,
        "city_id": ["NAVA"] * 24,
        "period_month": [str(pd.Period("2024-01", freq="M") + i) for i in range(24)],
        "qty_issued": list(np.random.default_rng(3).poisson(15, 24)),
        "issue_events": [10] * 24,
        "breakdown_events": [3] * 24,
    })
    extended = extend_history(demand, extra_years=2)

    assert len(extended) == 24 + 24
    synthetic = extended[extended["is_synthetic"] == 1]
    assert synthetic["period_month"].max() < demand["period_month"].min()
    assert (synthetic["issue_events"] <= synthetic["qty_issued"]).all()


def test_extension_is_reproducible():
    demand = pd.DataFrame({
        "sku_id": ["A"] * 24, "city_id": ["NAVA"] * 24,
        "period_month": [str(pd.Period("2024-01", freq="M") + i) for i in range(24)],
        "qty_issued": [12] * 24, "issue_events": [8] * 24, "breakdown_events": [2] * 24,
    })
    assert extend_history(demand, 2).equals(extend_history(demand, 2))


def test_extension_does_not_fabricate_seasonality(tables=None):
    """La prueba que hizo fracasar el intento anterior.

    Remuestrear los meses observados triplicaba las series estacionales, de 6 a
    20, porque inflaba la muestra sin aportar evidencia. Simular desde un
    proceso ajustado, e inyectar ciclo solo donde es detectable, debe dejar el
    reparto de patrones practicamente igual.
    """
    from app.core.dataset import OUT_DIR

    demand = pd.read_csv(OUT_DIR / "demand_history.csv")
    real = demand[demand["is_synthetic"] == 0]

    patterns_real = build_demand_patterns(real)
    patterns_full = build_demand_patterns(demand)

    seasonal_real = (patterns_real["pattern"] == "Estacional").sum()
    seasonal_full = (patterns_full["pattern"] == "Estacional").sum()
    assert abs(int(seasonal_full) - int(seasonal_real)) <= 2, (
        f"la extension altero la estacionalidad: {seasonal_real} -> {seasonal_full}"
    )
