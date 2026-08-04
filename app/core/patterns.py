"""Clasificacion de patrones de demanda por serie.

Funcionalidad:
    Analiza cada serie mensual de consumo y determina si su comportamiento es
    estacional, con tendencia, estable o volatil, cuanta confianza merece la
    proyeccion y que modelo conviene aplicarle en la etapa de forecast. Todas
    las funciones son puras.

    Los umbrales viven al inicio del archivo. Sobre la estacionalidad: con tres
    ciclos de historia, seasonal_decompose extrae un componente aparente incluso
    de ruido puro (fuerza media 0.32, supera 0.40 en el 26 por ciento de los
    casos). Por eso no basta la fuerza y se exige ademas significancia del efecto
    de mes. Con ambas condiciones el falso positivo baja al 2 por ciento.

    Sobre PRECEDENCE: los patrones explicables se evaluan antes que volatil. Una
    serie estacional tiene coeficiente de variacion alto por definicion, asi que
    si volatil ganara, ninguna estacionalidad se detectaria.
"""

import warnings as warning_control

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.tsa.seasonal import seasonal_decompose

MIN_PERIODS = 6
SEASONAL_PERIOD = 12
MIN_PERIODS_SEASONAL = 2 * SEASONAL_PERIOD

SEASONAL_STRENGTH_MIN = 0.45
SEASONAL_PVALUE_MAX = 0.05
TREND_PVALUE_MAX = 0.05
CV_VOLATILE = 0.50

SEASONAL = "Estacional"
TREND = "Tendencia"
STABLE = "Estable"
VOLATILE = "Volatil"
INSUFFICIENT = "Insuficiente"

PRECEDENCE = [INSUFFICIENT, SEASONAL, TREND, VOLATILE, STABLE]

RECOMMENDED_MODEL = {
    SEASONAL: "holt_winters",
    TREND: "linear_regression",
    STABLE: "moving_average",
    VOLATILE: "moving_median",
    INSUFFICIENT: "manual_input",
}

W_VOLUME = 0.30
W_VOLATILITY = 0.45
W_RECENT = 0.25

RECENT_WINDOW = 3

COLUMNS = [
    "sku_id", "city_id", "n_periods", "mean_monthly", "std_monthly", "cv",
    "zero_ratio", "seasonal_strength", "seasonal_pvalue", "trend_tau",
    "trend_pvalue", "pattern", "confidence", "recommended_model",
]


def seasonal_strength(values: np.ndarray) -> float:
    """Mide que parte de la variacion explica el componente estacional.

    Entrada:
        values: serie mensual ordenada cronologicamente.

    Salida:
        Valor entre 0 y 1. Devuelve 0 si la serie es demasiado corta o no varia.

    Funcionalidad:
        Descompone la serie y calcula la proporcion de varianza atribuible al
        componente estacional frente a la suma de estacional y residuo.
    """
    if len(values) < MIN_PERIODS_SEASONAL:
        return 0.0
    if np.std(values) == 0:
        return 0.0

    with warning_control.catch_warnings():
        warning_control.simplefilter("ignore")
        try:
            decomposed = seasonal_decompose(
                values, model="additive", period=SEASONAL_PERIOD,
                extrapolate_trend="freq",
            )
        except ValueError:
            return 0.0

    seasonal = np.asarray(decomposed.seasonal, dtype=float)
    resid = np.asarray(decomposed.resid, dtype=float)
    mask = ~np.isnan(resid)
    if mask.sum() < 2:
        return 0.0

    total_variance = np.var(seasonal[mask] + resid[mask])
    if total_variance == 0:
        return 0.0
    return float(np.clip(1 - np.var(resid[mask]) / total_variance, 0.0, 1.0))


def seasonality_pvalue(values: np.ndarray) -> float:
    """Evalua si el mes del año influye significativamente en la demanda.

    Entrada:
        values: serie mensual ordenada cronologicamente.

    Salida:
        p-valor del contraste. Devuelve 1.0 cuando no hay datos suficientes.

    Funcionalidad:
        Agrupa las observaciones por posicion dentro del ciclo anual y aplica
        Kruskal-Wallis. Al ser no parametrico aguanta la distribucion sesgada
        tipica del consumo de repuestos. Complementa a seasonal_strength, que
        por si sola produce falsos positivos cuando hay pocos ciclos.
    """
    if len(values) < MIN_PERIODS_SEASONAL or np.std(values) == 0:
        return 1.0

    groups = [values[i::SEASONAL_PERIOD] for i in range(SEASONAL_PERIOD)]
    groups = [g for g in groups if len(g) >= 2]
    if len(groups) < 3:
        return 1.0

    with warning_control.catch_warnings():
        warning_control.simplefilter("ignore")
        try:
            pvalue = float(stats.kruskal(*groups).pvalue)
        except ValueError:
            return 1.0
    return 1.0 if np.isnan(pvalue) else pvalue


def trend_test(values: np.ndarray) -> tuple:
    """Detecta si la serie crece o decrece de forma sostenida.

    Entrada:
        values: serie mensual ordenada cronologicamente.

    Salida:
        Tupla (tau, p_valor). Tau positivo indica crecimiento y negativo caida.

    Funcionalidad:
        Aplica el contraste de Mann-Kendall mediante el tau de Kendall entre la
        serie y el orden temporal, que es el mismo estadistico.
    """
    if len(values) < 3 or np.std(values) == 0:
        return 0.0, 1.0
    with warning_control.catch_warnings():
        warning_control.simplefilter("ignore")
        result = stats.kendalltau(np.arange(len(values)), values)
    tau = 0.0 if np.isnan(result.statistic) else float(result.statistic)
    pvalue = 1.0 if np.isnan(result.pvalue) else float(result.pvalue)
    return tau, pvalue


def confidence_score(n_periods: int, cv: float, values: np.ndarray) -> float:
    """Calcula la confianza que merece la proyeccion de una serie.

    Entrada:
        n_periods: numero de meses observados.
        cv: coeficiente de variacion de la serie.
        values: serie mensual ordenada cronologicamente.

    Salida:
        Score entre 0 y 1 redondeado a dos decimales.

    Funcionalidad:
        Combina tres factores: cuanta historia hay, cuanta dispersion tiene la
        demanda y si los ultimos meses se despegan del comportamiento historico,
        lo que sugeriria un cambio de patron reciente. La dispersion pesa mas
        porque es lo que mas degrada la precision del forecast.
    """
    if n_periods < MIN_PERIODS:
        volume_factor = 0.20
    elif n_periods < SEASONAL_PERIOD:
        volume_factor = 0.55
    elif n_periods < MIN_PERIODS_SEASONAL:
        volume_factor = 0.80
    else:
        volume_factor = 1.00

    if cv <= 0.25:
        volatility_factor = 1.00
    elif cv <= CV_VOLATILE:
        volatility_factor = 0.80
    elif cv <= 1.00:
        volatility_factor = 0.50
    else:
        volatility_factor = 0.25

    recent_factor = 1.00
    if len(values) >= RECENT_WINDOW * 2:
        recent = float(np.mean(values[-RECENT_WINDOW:]))
        historical = float(np.mean(values[:-RECENT_WINDOW]))
        if historical > 0:
            shift = abs(recent - historical) / historical
            recent_factor = float(np.clip(1.0 - shift, 0.0, 1.0))

    score = (
        W_VOLUME * volume_factor
        + W_VOLATILITY * volatility_factor
        + W_RECENT * recent_factor
    )
    return round(float(np.clip(score, 0.0, 1.0)), 2)


def classify_series(values) -> dict:
    """Clasifica una serie de demanda mensual.

    Entrada:
        values: secuencia de cantidades mensuales en orden cronologico.

    Salida:
        Diccionario con las metricas descriptivas, la etiqueta de patron, el
        score de confianza y el modelo de proyeccion recomendado.

    Funcionalidad:
        Evalua las reglas en el orden de precedencia definido en la
        configuracion. Una serie sin historia suficiente o sin consumo alguno se
        marca como insuficiente y no recibe confianza. La estacionalidad exige
        dos condiciones a la vez, componente fuerte y efecto de mes
        significativo, para no confundir ruido con ciclo.
    """
    values = np.asarray(values, dtype=float)
    n_periods = len(values)
    mean = float(np.mean(values)) if n_periods else 0.0
    std = float(np.std(values, ddof=0)) if n_periods else 0.0
    cv = float(std / mean) if mean > 0 else 0.0
    zero_ratio = float(np.mean(values == 0)) if n_periods else 1.0

    strength = seasonal_strength(values)
    seasonal_p = seasonality_pvalue(values)
    tau, trend_p = trend_test(values)

    if n_periods < MIN_PERIODS or mean == 0:
        pattern = INSUFFICIENT
    elif strength >= SEASONAL_STRENGTH_MIN and seasonal_p < SEASONAL_PVALUE_MAX:
        pattern = SEASONAL
    elif trend_p < TREND_PVALUE_MAX:
        pattern = TREND
    elif cv > CV_VOLATILE:
        pattern = VOLATILE
    else:
        pattern = STABLE

    confidence = confidence_score(n_periods, cv, values)
    if pattern == INSUFFICIENT:
        confidence = 0.0

    return {
        "n_periods": n_periods,
        "mean_monthly": round(mean, 2),
        "std_monthly": round(std, 2),
        "cv": round(cv, 3),
        "zero_ratio": round(zero_ratio, 3),
        "seasonal_strength": round(strength, 3),
        "seasonal_pvalue": round(seasonal_p, 4),
        "trend_tau": round(tau, 3),
        "trend_pvalue": round(trend_p, 4),
        "pattern": pattern,
        "confidence": confidence,
        "recommended_model": RECOMMENDED_MODEL[pattern],
    }


def build_demand_patterns(demand: pd.DataFrame) -> pd.DataFrame:
    """Clasifica todas las series del historico de demanda.

    Entrada:
        demand: DataFrame de demanda mensual con sku_id, city_id, period_month y
            qty_issued.

    Salida:
        DataFrame con una fila por combinacion de pieza y ciudad, con las
        columnas declaradas en COLUMNS.

    Funcionalidad:
        Recorre cada serie por separado. La clasificacion se hace por pieza y
        ciudad, no solo por pieza, porque una misma referencia puede comportarse
        de forma distinta en cada planta y una etiqueta unica ocultaria esa
        diferencia.
    """
    ordered = demand.sort_values(["sku_id", "city_id", "period_month"])
    rows = []
    for (sku, city), group in ordered.groupby(["sku_id", "city_id"], sort=True):
        result = classify_series(group["qty_issued"].to_numpy())
        rows.append({"sku_id": sku, "city_id": city, **result})
    return pd.DataFrame(rows, columns=COLUMNS)
