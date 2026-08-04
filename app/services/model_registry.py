"""Proyeccion de demanda con el modelo entrenado.

Funcionalidad:
    Aplica el modelo global de demanda al ultimo mes disponible de cada serie
    para obtener la proyeccion del periodo siguiente, y la combina con la
    proyeccion estadistica.

    La combinacion no es un capricho. El modelo global mejora claramente a la
    referencia trivial pero apenas supera al promedio movil, porque dos tercios
    de las series son planas y ahi no hay estructura que aprender. Promediar
    ambas proyecciones reduce la varianza sin apostar todo a un metodo, que es
    la practica habitual cuando dos estimadores tienen error parecido y errores
    poco correlacionados.
"""

from pathlib import Path

import numpy as np
import pandas as pd

from app.core.training import build_features, feature_columns

ARTIFACT_ROOT = Path(__file__).resolve().parents[2] / "artifacts"

MODEL_WEIGHT = 0.5


def latest_feature_rows(demand: pd.DataFrame, parts: pd.DataFrame) -> pd.DataFrame:
    """Extrae la fila de variables mas reciente de cada serie.

    Entrada:
        demand: historico mensual de demanda.
        parts: maestro de piezas.

    Salida:
        DataFrame con una fila por combinacion de pieza y ciudad, la del ultimo
        mes disponible, con todas las variables ya calculadas.

    Funcionalidad:
        El modelo proyecta el mes siguiente a partir del estado actual de la
        serie, de modo que solo hace falta la ultima observacion de cada una.
    """
    frame = build_features(demand, parts)
    latest = frame.sort_values("period_month").groupby(["sku_id", "city_id"]).tail(1)
    return latest.reset_index(drop=True)


def model_projection(demand: pd.DataFrame, parts: pd.DataFrame, model) -> pd.DataFrame:
    """Proyecta la demanda del proximo mes con el modelo entrenado.

    Entrada:
        demand: historico mensual de demanda.
        parts: maestro de piezas.
        model: estimador ya entrenado.

    Salida:
        DataFrame con sku_id, city_id y forecast_model.

    Funcionalidad:
        Aplica el modelo a la ultima fila de cada serie y recorta en cero, ya
        que una demanda negativa no tiene sentido operativo.
    """
    latest = latest_feature_rows(demand, parts)
    columns = feature_columns(latest)
    predictions = np.clip(model.predict(latest[columns]), 0, None)
    return pd.DataFrame({
        "sku_id": latest["sku_id"],
        "city_id": latest["city_id"],
        "forecast_model": np.round(predictions, 2),
    })


def blend_forecasts(statistical: pd.DataFrame, model_based: pd.DataFrame,
                    weight: float = MODEL_WEIGHT) -> pd.DataFrame:
    """Combina la proyeccion estadistica con la del modelo.

    Entrada:
        statistical: proyeccion por metodos estadisticos, con forecast_q50.
        model_based: proyeccion del modelo, con forecast_model.
        weight: peso que se asigna al modelo entre 0 y 1.

    Salida:
        DataFrame de la proyeccion estadistica con las columnas forecast_model,
        forecast_blend y forecast_source añadidas, y forecast_q50 reemplazado
        por la combinacion.

    Funcionalidad:
        Promedia ambas proyecciones y desplaza los cuartiles en la misma
        proporcion, de modo que el intervalo siga centrado en la nueva
        estimacion. Las series sin proyeccion del modelo conservan la
        estadistica intacta.
    """
    base = statistical.drop(columns=["forecast_model", "forecast_source"], errors="ignore")
    merged = base.merge(model_based, on=["sku_id", "city_id"], how="left")
    has_model = merged["forecast_model"].notna()

    blended = np.where(
        has_model,
        weight * merged["forecast_model"].fillna(0) + (1 - weight) * merged["forecast_q50"],
        merged["forecast_q50"],
    )
    shift = blended - merged["forecast_q50"]

    merged["forecast_blend"] = np.round(blended, 2)
    merged["forecast_q25"] = np.round(np.clip(merged["forecast_q25"] + shift, 0, None), 2)
    merged["forecast_q75"] = np.round(np.clip(merged["forecast_q75"] + shift, 0, None), 2)
    merged["forecast_q50"] = merged["forecast_blend"]
    merged["forecast_source"] = np.where(has_model, "modelo+estadistico", "estadistico")
    return merged


def load_trained_model():
    """Recupera el ultimo modelo entrenado desde los artefactos del SDK.

    Entrada:
        Ninguna.

    Salida:
        Tupla (modelo, run_id) o (None, None) si aun no se ha entrenado.

    Funcionalidad:
        El SDK serializa cada entrenamiento en artifacts/<run_id>/model.pkl.
        Se toma el mas reciente por fecha de escritura. Devolver None en lugar
        de fallar permite que la proyeccion siga funcionando con los metodos
        estadisticos cuando nunca se ha entrenado, de modo que el pipeline no
        dependa del modelo para arrancar.
    """
    import pickle

    candidates = sorted(
        ARTIFACT_ROOT.glob("*/model.pkl"), key=lambda path: path.stat().st_mtime
    )
    if not candidates:
        return None, None

    latest = candidates[-1]
    with latest.open("rb") as handle:
        return pickle.load(handle), latest.parent.name
