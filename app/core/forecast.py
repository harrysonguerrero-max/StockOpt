"""Proyeccion de demanda y calculo de inventario minimo.

Funcionalidad:
    Proyecta la demanda futura de cada serie aplicando el metodo que le
    corresponde segun su patron, mide el error del metodo con una validacion
    retrospectiva y traduce la proyeccion a la demanda esperada durante el
    tiempo de entrega del proveedor, que es lo que consume el optimizador.

    Los metodos son deliberadamente simples y explicables. Con 36 observaciones
    mensuales por serie, un modelo pesado sobreajustaria sin aportar precision,
    y el objetivo del MVP es que el razonamiento sea auditable de punta a punta.
"""

import warnings as warning_control

import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from app.core.inventory import Z_BY_CRITICALITY, inventory_minimum, planning_lead_time
from app.core.patterns import (
    INSUFFICIENT,
    MIN_PERIODS_SEASONAL,
    RECOMMENDED_MODEL,
    SEASONAL,
    SEASONAL_PERIOD,
    STABLE,
    TREND,
    VOLATILE,
)

FORECAST_HORIZON_MONTHS = 3
MOVING_WINDOW = 6
BACKTEST_MONTHS = 6

QUANTILE_Z = 0.674

WMAPE_MEDIUM = 0.30
WMAPE_HIGH = 0.50
ACCURACY_PENALTY_MEDIUM = 0.85
ACCURACY_PENALTY_HIGH = 0.65

COLUMNS = [
    "sku_id", "city_id", "pattern", "method", "n_periods",
    "forecast_q25", "forecast_q50", "forecast_q75",
    "wmape_backtest", "confidence_pattern", "confidence_final",
    "lead_time_days", "demand_lead_time", "safety_stock", "inventory_min",
    "forecast_model", "forecast_source", "needs_review",
]


def _spread_from_std(center: float, std: float) -> tuple:
    """Deriva los cuartiles a partir de un centro y una dispersion.

    Entrada:
        center: valor central de la proyeccion.
        std: desviacion tipica asociada.

    Salida:
        Tupla (q25, q50, q75) con valores no negativos.

    Funcionalidad:
        Supone dispersion simetrica alrededor del centro y usa el factor normal
        correspondiente a los cuartiles.
    """
    delta = QUANTILE_Z * std
    return (max(0.0, center - delta), max(0.0, center), max(0.0, center + delta))


def forecast_stable(values: np.ndarray) -> tuple:
    """Proyecta una serie de demanda plana.

    Entrada:
        values: serie mensual ordenada cronologicamente.

    Salida:
        Tupla (q25, q50, q75) de demanda mensual esperada.

    Funcionalidad:
        Promedia la ventana reciente y abre el intervalo con la dispersion de
        esa misma ventana.
    """
    window = values[-MOVING_WINDOW:]
    return _spread_from_std(float(np.mean(window)), float(np.std(window, ddof=0)))


def forecast_volatile(values: np.ndarray) -> tuple:
    """Proyecta una serie de demanda erratica.

    Entrada:
        values: serie mensual ordenada cronologicamente.

    Salida:
        Tupla (q25, q50, q75) de demanda mensual esperada.

    Funcionalidad:
        Usa percentiles empiricos de la ventana reciente en lugar de la media,
        para que unos pocos meses extremos no arrastren la proyeccion.
    """
    window = values[-MOVING_WINDOW:]
    return (float(np.percentile(window, 25)),
            float(np.percentile(window, 50)),
            float(np.percentile(window, 75)))


def forecast_trend(values: np.ndarray) -> tuple:
    """Proyecta una serie con crecimiento o caida sostenida.

    Entrada:
        values: serie mensual ordenada cronologicamente.

    Salida:
        Tupla (q25, q50, q75) de demanda mensual esperada.

    Funcionalidad:
        Ajusta una recta por minimos cuadrados sobre toda la historia, evalua el
        siguiente periodo y abre el intervalo con la dispersion de los residuos.
    """
    index = np.arange(len(values), dtype=float)
    slope, intercept = np.polyfit(index, values, 1)
    prediction = slope * len(values) + intercept
    residuals = values - (slope * index + intercept)
    return _spread_from_std(float(prediction), float(np.std(residuals, ddof=0)))


def forecast_seasonal(values: np.ndarray) -> tuple:
    """Proyecta una serie con ciclo anual.

    Entrada:
        values: serie mensual ordenada cronologicamente.

    Salida:
        Tupla (q25, q50, q75) de demanda mensual esperada.

    Funcionalidad:
        Aplica suavizado exponencial de Holt-Winters con componente estacional
        aditiva. Se prefiere a modelos mas pesados porque con tres ciclos de
        historia estos sobreajustan, y porque Holt-Winters es directamente
        explicable ante negocio. Si el ajuste no converge, cae al metodo de
        serie plana para no dejar la serie sin proyeccion.
    """
    if len(values) < MIN_PERIODS_SEASONAL:
        return forecast_stable(values)
    try:
        with warning_control.catch_warnings():
            warning_control.simplefilter("ignore")
            model = ExponentialSmoothing(
                values, trend=None, seasonal="add",
                seasonal_periods=SEASONAL_PERIOD,
                initialization_method="estimated",
            ).fit()
        prediction = float(model.forecast(1)[0])
        residuals = values - np.asarray(model.fittedvalues, dtype=float)
        return _spread_from_std(prediction, float(np.std(residuals, ddof=0)))
    except (ValueError, np.linalg.LinAlgError):
        return forecast_stable(values)


FORECAST_METHODS = {
    STABLE: forecast_stable,
    VOLATILE: forecast_volatile,
    TREND: forecast_trend,
    SEASONAL: forecast_seasonal,
}


def forecast_series(values: np.ndarray, pattern: str) -> tuple:
    """Proyecta una serie con el metodo que corresponde a su patron.

    Entrada:
        values: serie mensual ordenada cronologicamente.
        pattern: etiqueta asignada en la clasificacion de patrones.

    Salida:
        Tupla (q25, q50, q75) de demanda mensual esperada.

    Funcionalidad:
        Enruta al metodo correspondiente. Una serie marcada como insuficiente no
        se proyecta automaticamente y devuelve ceros, para que la decision quede
        en manos del comprador.
    """
    if pattern == INSUFFICIENT or len(values) == 0:
        return (0.0, 0.0, 0.0)
    method = FORECAST_METHODS.get(pattern, forecast_stable)
    return method(np.asarray(values, dtype=float))


def backtest_wmape(values: np.ndarray, pattern: str) -> float:
    """Mide el error del metodo sobre meses ya conocidos.

    Entrada:
        values: serie mensual ordenada cronologicamente.
        pattern: etiqueta asignada en la clasificacion de patrones.

    Salida:
        Error porcentual ponderado entre 0 y 1. Devuelve NaN si no hay historia
        suficiente para reservar meses de prueba.

    Funcionalidad:
        Reserva los ultimos meses, proyecta mes a mes usando solo la informacion
        previa a cada uno y compara contra lo realmente consumido.

        Se usa error ponderado sobre el total, y no el porcentaje medio clasico,
        porque la demanda de repuestos tiene meses en cero: dividir mes a mes
        entre el valor real produciria divisiones por cero e inflaria el error
        de forma artificial.
    """
    values = np.asarray(values, dtype=float)
    holdout = BACKTEST_MONTHS
    if len(values) < holdout + MIN_PERIODS_SEASONAL:
        return float("nan")

    errors = []
    actuals = []
    for step in range(holdout):
        cutoff = len(values) - holdout + step
        _, prediction, _ = forecast_series(values[:cutoff], pattern)
        errors.append(abs(values[cutoff] - prediction))
        actuals.append(values[cutoff])

    total = float(np.sum(actuals))
    if total == 0:
        return float("nan")
    return float(np.sum(errors) / total)


def adjust_confidence(confidence: float, wmape: float) -> float:
    """Ajusta la confianza segun el error observado del metodo.

    Entrada:
        confidence: confianza derivada del patron de demanda.
        wmape: error ponderado de la validacion retrospectiva.

    Salida:
        Confianza final entre 0 y 1, redondeada a dos decimales.

    Funcionalidad:
        Penaliza la confianza cuando el metodo ya demostro fallar sobre datos
        conocidos. Si no hay validacion disponible, deja la confianza intacta.
    """
    if np.isnan(wmape):
        return round(float(confidence), 2)
    if wmape > WMAPE_HIGH:
        factor = ACCURACY_PENALTY_HIGH
    elif wmape > WMAPE_MEDIUM:
        factor = ACCURACY_PENALTY_MEDIUM
    else:
        factor = 1.0
    return round(float(np.clip(confidence * factor, 0.0, 1.0)), 2)


def build_demand_forecast(demand: pd.DataFrame, patterns: pd.DataFrame,
                          parts: pd.DataFrame, suppliers: pd.DataFrame,
                          override_demand: pd.DataFrame = None) -> pd.DataFrame:
    """Proyecta todas las series y calcula su inventario minimo.

    Entrada:
        demand: historico de demanda mensual por pieza y ciudad.
        patterns: clasificacion de patrones con su confianza.
        parts: maestro de piezas, del que se toma la criticidad.
        suppliers: catalogo de proveedores, del que sale el tiempo de entrega.

    Salida:
        DataFrame con una fila por pieza y ciudad, con las columnas declaradas
        en COLUMNS.

    Funcionalidad:
        Para cada serie proyecta la demanda mensual con su metodo, valida el
        metodo contra los ultimos meses conocidos, ajusta la confianza segun ese
        error y traduce el resultado a la demanda esperada durante el tiempo de
        entrega mas su colchon de seguridad. Marca para revision humana las series
        de baja confianza y las que no admiten proyeccion automatica.
    """
    lead_time, lead_time_std = planning_lead_time(suppliers)
    criticality = dict(zip(parts["sku_id"], parts["criticality"]))
    pattern_by_series = {
        (row["sku_id"], row["city_id"]): (row["pattern"], row["confidence"])
        for _, row in patterns.iterrows()
    }

    overrides = {}
    if override_demand is not None:
        overrides = {
            (row["sku_id"], row["city_id"]): row
            for _, row in override_demand.iterrows()
        }

    ordered = demand.sort_values(["sku_id", "city_id", "period_month"])
    rows = []
    for (sku, city), group in ordered.groupby(["sku_id", "city_id"], sort=True):
        values = group["qty_issued"].to_numpy(dtype=float)
        pattern, base_confidence = pattern_by_series.get(
            (sku, city), (INSUFFICIENT, 0.0)
        )

        q25, q50, q75 = forecast_series(values, pattern)
        wmape = backtest_wmape(values, pattern)
        confidence = adjust_confidence(base_confidence, wmape)

        source = "estadistico"
        model_value = None
        replacement = overrides.get((sku, city))
        if replacement is not None:
            q25 = float(replacement["forecast_q25"])
            q50 = float(replacement["forecast_q50"])
            q75 = float(replacement["forecast_q75"])
            model_value = replacement.get("forecast_model")
            source = replacement.get("forecast_source", "modelo+estadistico")

        z = Z_BY_CRITICALITY[criticality[sku]]
        demand_lead_time, buffer, minimum = inventory_minimum(
            q50, float(np.std(values, ddof=0)), lead_time, lead_time_std, z
        )

        rows.append({
            "sku_id": sku,
            "city_id": city,
            "pattern": pattern,
            "method": RECOMMENDED_MODEL[pattern],
            "n_periods": len(values),
            "forecast_q25": round(q25, 2),
            "forecast_q50": round(q50, 2),
            "forecast_q75": round(q75, 2),
            "wmape_backtest": None if np.isnan(wmape) else round(wmape, 3),
            "confidence_pattern": round(float(base_confidence), 2),
            "confidence_final": confidence,
            "lead_time_days": round(lead_time, 1),
            "demand_lead_time": round(demand_lead_time, 2),
            "safety_stock": round(buffer, 2),
            "inventory_min": minimum,
            "forecast_model": None if model_value is None else round(float(model_value), 2),
            "forecast_source": source,
            "needs_review": int(confidence < 0.5 or pattern == INSUFFICIENT),
        })

    return pd.DataFrame(rows, columns=COLUMNS)
