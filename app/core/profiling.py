"""Perfilado y deteccion de anomalias en datos crudos.

Funcionalidad:
    Describe un conjunto de datos antes de transformarlo: tipos, nulos,
    duplicados, cardinalidad, rangos y valores atipicos. Es el paso previo a
    cualquier limpieza, porque no se puede decidir que corregir sin saber primero
    que hay.

    Todas las funciones son puras y devuelven diccionarios serializables, de modo
    que el informe pueda guardarse, versionarse y compararse entre corridas para
    detectar degradacion de la fuente.
"""

import numpy as np
import pandas as pd

IQR_FACTOR = 1.5
IQR_EXTREME_FACTOR = 3.0

MAD_THRESHOLD = 3.5
MAD_SCALE = 0.6745

HIGH_NULL_RATIO = 0.30
LOW_VARIANCE_RATIO = 0.01


def column_profile(series: pd.Series) -> dict:
    """Describe una columna.

    Entrada:
        series: columna a perfilar.

    Salida:
        Diccionario con tipo, conteo de nulos, cardinalidad y, si es numerica,
        sus estadisticos de posicion y dispersion.

    Funcionalidad:
        Distingue columnas numericas de categoricas para reportar de cada una lo
        que tiene sentido: rangos y cuartiles en las primeras, valores mas
        frecuentes en las segundas.
    """
    profile = {
        "dtype": str(series.dtype),
        "count": int(series.notna().sum()),
        "nulls": int(series.isna().sum()),
        "null_ratio": round(float(series.isna().mean()), 4),
        "unique": int(series.nunique(dropna=True)),
    }

    if pd.api.types.is_numeric_dtype(series):
        clean = series.dropna()
        if len(clean):
            profile.update({
                "mean": round(float(clean.mean()), 4),
                "std": round(float(clean.std()), 4),
                "min": round(float(clean.min()), 4),
                "p25": round(float(clean.quantile(0.25)), 4),
                "p50": round(float(clean.quantile(0.50)), 4),
                "p75": round(float(clean.quantile(0.75)), 4),
                "max": round(float(clean.max()), 4),
                "zeros": int((clean == 0).sum()),
                "negatives": int((clean < 0).sum()),
            })
    else:
        top = series.dropna().value_counts().head(5)
        profile["top_values"] = {str(k): int(v) for k, v in top.items()}

    return profile


def detect_outliers_iqr(series: pd.Series, factor: float = IQR_FACTOR) -> pd.Series:
    """Marca valores atipicos por el criterio del rango intercuartilico.

    Entrada:
        series: columna numerica.
        factor: cuantos rangos intercuartilicos definen el limite.

    Salida:
        Serie booleana del mismo indice, verdadera donde el valor es atipico.

    Funcionalidad:
        Es el criterio clasico de caja y bigotes. No supone normalidad, pero se
        deja arrastrar cuando mas de un cuarto de los datos son extremos.
    """
    clean = series.dropna()
    if len(clean) < 4:
        return pd.Series(False, index=series.index)

    q1, q3 = clean.quantile(0.25), clean.quantile(0.75)
    spread = q3 - q1
    if spread == 0:
        return pd.Series(False, index=series.index)

    lower, upper = q1 - factor * spread, q3 + factor * spread
    return (series < lower) | (series > upper)


def detect_outliers_mad(series: pd.Series, threshold: float = MAD_THRESHOLD) -> pd.Series:
    """Marca valores atipicos por desviacion absoluta mediana.

    Entrada:
        series: columna numerica.
        threshold: puntaje a partir del cual el valor se considera atipico.

    Salida:
        Serie booleana del mismo indice, verdadera donde el valor es atipico.

    Funcionalidad:
        Usa la mediana en lugar de la media, asi que un puñado de valores
        extremos no desplaza el criterio como ocurre con la desviacion tipica.
        Es el metodo adecuado cuando se sospecha contaminacion en los datos.

        Cuando mas de la mitad de las observaciones son identicas, la desviacion
        mediana vale cero y el criterio se ciega por completo. Es el caso normal
        en consumo de refacciones, donde muchos meses repiten el mismo valor. En
        esa situacion se recurre a la desviacion media respecto de la mediana,
        que es la correccion habitual y conserva la robustez frente a la media
        aritmetica.
    """
    clean = series.dropna()
    if len(clean) < 4:
        return pd.Series(False, index=series.index)

    median = clean.median()
    deviation = (clean - median).abs().median()
    scale = MAD_SCALE / deviation if deviation > 0 else None

    if scale is None:
        mean_deviation = (clean - median).abs().mean()
        if mean_deviation == 0:
            return pd.Series(False, index=series.index)
        scale = MEAN_AD_SCALE / mean_deviation

    return scale * (series - median).abs() > threshold


def outlier_summary(frame: pd.DataFrame) -> dict:
    """Cuenta los valores atipicos de cada columna numerica.

    Entrada:
        frame: tabla a analizar.

    Salida:
        Diccionario por columna con el conteo segun ambos criterios y los
        limites del rango intercuartilico.

    Funcionalidad:
        Reporta los dos metodos a la vez porque discrepan de forma informativa:
        cuando el criterio robusto marca muchos mas que el clasico, la columna
        tiene una cola pesada y conviene revisarla antes de modelar.
    """
    summary = {}
    for column in frame.select_dtypes(include=[np.number]).columns:
        series = frame[column]
        clean = series.dropna()
        if len(clean) < 4 or clean.nunique() <= 1:
            continue

        q1, q3 = clean.quantile(0.25), clean.quantile(0.75)
        spread = q3 - q1
        summary[column] = {
            "iqr_outliers": int(detect_outliers_iqr(series).sum()),
            "iqr_extreme": int(detect_outliers_iqr(series, IQR_EXTREME_FACTOR).sum()),
            "mad_outliers": int(detect_outliers_mad(series).sum()),
            "lower_bound": round(float(q1 - IQR_FACTOR * spread), 4),
            "upper_bound": round(float(q3 + IQR_FACTOR * spread), 4),
        }
    return summary


def duplicate_summary(frame: pd.DataFrame, keys: list = None) -> dict:
    """Cuantifica los registros repetidos.

    Entrada:
        frame: tabla a analizar.
        keys: columnas que deberian identificar unicamente cada fila.

    Salida:
        Diccionario con duplicados exactos y, si se indican llaves, duplicados
        por esa combinacion.

    Funcionalidad:
        Separa ambos casos porque significan cosas distintas: una fila repetida
        entera suele ser un error de carga, mientras que una llave repetida con
        valores distintos indica un conflicto de origen que alguien debe
        resolver.
    """
    result = {"exact_duplicates": int(frame.duplicated().sum())}
    if keys and all(key in frame.columns for key in keys):
        result["key_duplicates"] = int(frame.duplicated(subset=keys).sum())
        result["keys"] = keys
    return result


def quality_flags(frame: pd.DataFrame, profile: dict) -> list:
    """Traduce el perfil en advertencias accionables.

    Entrada:
        frame: tabla analizada.
        profile: perfil por columna devuelto por column_profile.

    Salida:
        Lista de advertencias en texto.

    Funcionalidad:
        Convierte los numeros del perfil en frases que indican que hacer:
        columnas con demasiados nulos, columnas constantes que no aportan al
        modelo y columnas numericas con valores negativos donde no deberia
        haberlos.
    """
    flags = []
    for column, stats in profile.items():
        if stats["null_ratio"] > HIGH_NULL_RATIO:
            flags.append(
                f"{column}: {stats['null_ratio']:.0%} de nulos, revisar si la "
                f"columna es opcional o si falta informacion de origen"
            )
        if stats["unique"] <= 1:
            flags.append(f"{column}: valor constante, no aporta informacion")
        if stats.get("negatives", 0) > 0:
            flags.append(f"{column}: {stats['negatives']} valores negativos")
    return flags


def profile_dataset(frame: pd.DataFrame, name: str, keys: list = None) -> dict:
    """Genera el informe completo de una tabla.

    Entrada:
        frame: tabla a perfilar.
        name: nombre con el que aparece en el informe.
        keys: columnas que deberian identificar unicamente cada fila.

    Salida:
        Diccionario con dimensiones, perfil por columna, duplicados, atipicos y
        advertencias.

    Funcionalidad:
        Reune todo el perfilado en una sola estructura serializable, pensada
        para guardarse junto al dataset y comparar corridas entre si.
    """
    profile = {column: column_profile(frame[column]) for column in frame.columns}
    return {
        "name": name,
        "rows": len(frame),
        "columns": len(frame.columns),
        "profile": profile,
        "duplicates": duplicate_summary(frame, keys),
        "outliers": outlier_summary(frame),
        "flags": quality_flags(frame, profile),
    }
