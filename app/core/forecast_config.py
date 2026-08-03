"""Umbrales de clasificacion de patrones de demanda.

Funcionalidad:
    Reune los cortes que deciden si una serie de demanda es estacional, con
    tendencia, estable o volatil, junto con los pesos del score de confianza y
    el modelo de proyeccion asignado a cada patron.

    Sobre SEASONAL_STRENGTH_MIN y SEASONAL_PVALUE_MAX: con tres ciclos de
    historia, seasonal_decompose extrae un componente estacional aparente
    incluso de ruido puro (fuerza media 0.32, supera 0.40 en el 26 por ciento de
    los casos). Por eso la fuerza no basta y se exige ademas que el mes del año
    explique la variacion de forma significativa. Con ambas condiciones el falso
    positivo sobre ruido baja al 2 por ciento y se sigue detectando el 100 por
    ciento de la estacionalidad real moderada.

    Sobre PRECEDENCE: los patrones explicables se evaluan antes que volatil. Una
    serie estacional tiene coeficiente de variacion alto por definicion, asi que
    si volatil ganara la precedencia, ninguna estacionalidad se detectaria.
"""

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
    SEASONAL: "prophet",
    TREND: "linear_regression",
    STABLE: "moving_average",
    VOLATILE: "moving_median",
    INSUFFICIENT: "manual_input",
}

W_VOLUME = 0.30
W_VOLATILITY = 0.45
W_RECENT = 0.25

RECENT_WINDOW = 3
