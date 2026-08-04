"""Generacion de historia sintetica de demanda.

Funcionalidad:
    Extiende hacia atras el historico de cada serie simulando desde un proceso
    generativo ajustado a los datos reales, para disponer de mas anos de
    profundidad sin inventar estructura que no existe.

    Un intento previo fallo y conviene entender por que. Remuestrear los meses
    observados, o centrar cada mes generado en la media historica de ese mes,
    parecia razonable pero corrompia la clasificacion de patrones: las series
    detectadas como estacionales pasaban de 6 a 20 sin que la demanda real
    hubiera cambiado. La causa es que esos meses no son evidencia nueva sino
    copias de las mismas observaciones, e inflar asi la muestra fabrica poder
    estadistico donde no lo hay.

    El metodo actual evita ese problema con dos decisiones. Primera, cada mes se
    simula con innovaciones aleatorias propias a partir de una distribucion
    ajustada, no copiando valores. Segunda, el perfil estacional solo se inyecta
    en las series donde la estacionalidad es estadisticamente detectable en el
    dato real; en el resto se simula sin ciclo, de modo que no se fabrica un
    patron que la serie nunca tuvo.

    Se usa una binomial negativa porque la demanda de refacciones son conteos
    con mas dispersion que la que admite una Poisson.
"""

import numpy as np
import pandas as pd

from app.core.patterns import (
    SEASONAL_PERIOD,
    SEASONAL_PVALUE_MAX,
    SEASONAL_STRENGTH_MIN,
    seasonal_strength,
    seasonality_pvalue,
)

SEED = 20260803

MIN_DISPERSION = 1e-6
MAX_SEASONAL_FACTOR = 2.5
MIN_SEASONAL_FACTOR = 0.35

LEVEL_DRIFT = 0.015


def estimate_process(values: np.ndarray) -> dict:
    """Ajusta el proceso generativo de una serie.

    Entrada:
        values: serie mensual observada, ordenada cronologicamente.

    Salida:
        Diccionario con el nivel medio, la varianza, el factor estacional por
        mes del ciclo y si la estacionalidad es real.

    Funcionalidad:
        Estima nivel y dispersion, y decide si la serie tiene ciclo anual usando
        el mismo doble criterio que la clasificacion de patrones: componente
        estacional fuerte y efecto de mes significativo. Solo cuando ambos se
        cumplen se conserva el perfil estacional para la simulacion.
    """
    values = np.asarray(values, dtype=float)
    level = float(values.mean())
    variance = float(values.var(ddof=0))

    has_season = (
        seasonal_strength(values) >= SEASONAL_STRENGTH_MIN
        and seasonality_pvalue(values) < SEASONAL_PVALUE_MAX
    )

    factors = np.ones(SEASONAL_PERIOD)
    if has_season and level > 0:
        for position in range(SEASONAL_PERIOD):
            slice_values = values[position::SEASONAL_PERIOD]
            if len(slice_values):
                factors[position] = np.clip(
                    slice_values.mean() / level, MIN_SEASONAL_FACTOR, MAX_SEASONAL_FACTOR
                )

    return {
        "level": level,
        "variance": variance,
        "seasonal_factors": factors,
        "has_season": bool(has_season),
    }


def negative_binomial_draw(mean: float, variance: float, rng) -> int:
    """Extrae un conteo de una binomial negativa con la media y varianza dadas.

    Entrada:
        mean: media deseada.
        variance: varianza deseada.
        rng: generador aleatorio de numpy.

    Salida:
        Conteo entero no negativo.

    Funcionalidad:
        Reparametriza la binomial negativa a partir de media y varianza, que es
        como se estiman de los datos. Si la varianza no supera a la media, la
        distribucion degenera y se recurre a una Poisson, que es su limite.
    """
    if mean <= 0:
        return 0
    if variance <= mean + MIN_DISPERSION:
        return int(rng.poisson(mean))

    probability = mean / variance
    trials = mean * probability / (1 - probability)
    return int(rng.negative_binomial(max(trials, MIN_DISPERSION), probability))


def simulate_backwards(process: dict, months: int, rng) -> np.ndarray:
    """Simula meses anteriores al inicio de la serie observada.

    Entrada:
        process: parametros devueltos por estimate_process.
        months: cuantos meses generar.
        rng: generador aleatorio de numpy.

    Salida:
        Arreglo de conteos en orden cronologico, el mas antiguo primero.

    Funcionalidad:
        Genera hacia atras para no tocar el presente: el periodo reciente sigue
        siendo dato real y es el que alimenta las decisiones de compra. Aplica
        una deriva suave de nivel, de modo que el pasado lejano no sea una copia
        estadistica del presente, y respeta el perfil estacional solo si la serie
        lo tenia.
    """
    level = process["level"]
    variance = max(process["variance"], level)
    factors = process["seasonal_factors"]

    generated = []
    for step in range(1, months + 1):
        drift = 1.0 - LEVEL_DRIFT * step / 12
        position = (-step) % SEASONAL_PERIOD
        mean = max(0.0, level * drift * factors[position])
        scaled_variance = variance * (mean / level) if level > 0 else variance
        generated.append(negative_binomial_draw(mean, max(scaled_variance, mean), rng))

    return np.array(generated[::-1])


def extend_history(demand: pd.DataFrame, extra_years: int, seed: int = SEED) -> pd.DataFrame:
    """Prolonga hacia atras el historico de todas las series.

    Entrada:
        demand: historico mensual con sku_id, city_id, period_month, qty_issued,
            issue_events y breakdown_events.
        extra_years: anos de historia a generar antes del inicio real.
        seed: semilla para que la generacion sea reproducible.

    Salida:
        DataFrame con la historia ampliada y una columna is_synthetic que
        distingue lo generado de lo observado.

    Funcionalidad:
        Ajusta un proceso por serie sobre el dato real, simula los meses previos
        y los antepone. Las columnas acompanantes se derivan de las proporciones
        observadas en cada serie, de modo que la intermitencia y la frecuencia de
        fallas se mantengan coherentes con el consumo generado.

        La columna is_synthetic no es decorativa: permite entrenar sobre todo el
        historico pero medir y clasificar solo sobre lo real cuando haga falta.
    """
    months = extra_years * SEASONAL_PERIOD
    if months <= 0:
        result = demand.copy()
        result["is_synthetic"] = 0
        return result

    rng = np.random.default_rng(seed)
    first_month = pd.Period(demand["period_month"].min(), freq="M")
    new_periods = [str(first_month - offset) for offset in range(months, 0, -1)]

    rows = []
    for (sku, city), group in demand.groupby(["sku_id", "city_id"], sort=True):
        history = group.sort_values("period_month")
        values = history["qty_issued"].to_numpy(dtype=float)
        process = estimate_process(values)
        simulated = simulate_backwards(process, months, rng)

        total = values.sum()
        events_ratio = history["issue_events"].sum() / total if total else 0.0
        breakdown_mean = float(history["breakdown_events"].mean())

        for period, quantity in zip(new_periods, simulated):
            rows.append({
                "sku_id": sku,
                "city_id": city,
                "period_month": period,
                "qty_issued": int(quantity),
                "issue_events": min(int(quantity), int(round(quantity * events_ratio))),
                "breakdown_events": max(0, int(rng.poisson(max(breakdown_mean, 0.1)))),
                "is_synthetic": 1,
            })

    observed = demand.copy()
    observed["is_synthetic"] = 0
    extended = pd.concat([pd.DataFrame(rows), observed], ignore_index=True)
    return extended.sort_values(["sku_id", "city_id", "period_month"]).reset_index(drop=True)
