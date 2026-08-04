"""Entrenamiento del modelo de proyeccion de demanda.

Funcionalidad:
    Entrena un modelo unico sobre todas las series de consumo en lugar de un
    modelo por pieza. Con 36 observaciones mensuales por serie, ajustar un
    modelo independiente a cada una sobreajusta; un modelo global aprende de las
    40 series a la vez y aprovecha lo que tienen en comun, que es la practica
    habitual cuando hay muchas series cortas.

    El estimador es un arbol con refuerzo de gradiente que recibe rezagos de la
    propia serie, medias moviles, el mes del año y atributos de la pieza. La
    validacion es temporal: se entrena con los primeros meses y se mide sobre
    los ultimos, nunca al reves, para que la metrica refleje lo que el modelo
    haria en produccion.

    La clase hereda de BaseModel del SDK de MLOps, de modo que cada
    entrenamiento queda registrado en MLflow con sus parametros, sus metricas y
    sus artefactos sin escribir codigo de seguimiento.
"""
import dotenv
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
from mlops_sdk import BaseModel
from sklearn.ensemble import HistGradientBoostingRegressor

PROJECT = "stockopt-demanda"

ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "artifacts" / "training"

LAGS = [1, 2, 3, 6, 12]
ROLLING_WINDOWS = [3, 6]

VALIDATION_MONTHS = 6

MODEL_PARAMS = {
    "max_iter": 300,
    "learning_rate": 0.06,
    "max_depth": 5,
    "min_samples_leaf": 12,
    "l2_regularization": 1.0,
    "random_state": 20260803,
}

CRITICALITY_RANK = {"A": 3, "B": 2, "C": 1}

METRICS_FILE = "training_metrics.json"
PREDICTIONS_FILE = "validation_predictions.csv"

CHART_FILES = {
    "comparison": "modelo_vs_baseline.png",
    "scatter": "prediccion_vs_real.png",
    "errors": "distribucion_error.png",
    "importance": "importancia_variables.png",
    "series": "series_validacion.png",
}


def build_features(demand: pd.DataFrame, parts: pd.DataFrame) -> pd.DataFrame:
    """Construye la tabla de variables a partir del historico de demanda.

    Entrada:
        demand: historico mensual con sku_id, city_id, period_month, qty_issued,
            issue_events y breakdown_events.
        parts: maestro de piezas, del que se toman categoria y criticidad.

    Salida:
        DataFrame con una fila por serie y mes, las variables derivadas y la
        columna objetivo qty_issued. Descarta las filas iniciales que no tienen
        historia suficiente para calcular los rezagos.

    Funcionalidad:
        Genera rezagos de la propia serie, medias y desviaciones moviles, el mes
        del año en forma ciclica y los atributos de la pieza. Todos los calculos
        se hacen dentro de cada combinacion de pieza y ciudad, de modo que
        ninguna serie contamine a otra. Los rezagos usan solo informacion
        anterior a cada mes, lo que evita filtrar el futuro al modelo.
    """
    frame = demand.sort_values(["sku_id", "city_id", "period_month"]).copy()
    grouped = frame.groupby(["sku_id", "city_id"], sort=False)["qty_issued"]

    for lag in LAGS:
        frame[f"lag_{lag}"] = grouped.shift(lag)

    for window in ROLLING_WINDOWS:
        shifted = grouped.shift(1)
        frame[f"roll_mean_{window}"] = shifted.rolling(window, min_periods=2).mean()
        frame[f"roll_std_{window}"] = shifted.rolling(window, min_periods=2).std()

    events = frame.groupby(["sku_id", "city_id"], sort=False)["issue_events"]
    frame["issue_events_lag_1"] = events.shift(1)
    breakdowns = frame.groupby(["sku_id", "city_id"], sort=False)["breakdown_events"]
    frame["breakdown_lag_1"] = breakdowns.shift(1)

    month = frame["period_month"].str[-2:].astype(int)
    frame["month_sin"] = np.sin(2 * np.pi * month / 12)
    frame["month_cos"] = np.cos(2 * np.pi * month / 12)

    attributes = parts[["sku_id", "criticality", "unit_cost_usd", "shelf_life_days"]]
    frame = frame.merge(attributes, on="sku_id", how="left")
    frame["criticality_rank"] = frame["criticality"].map(CRITICALITY_RANK)
    frame["is_nava"] = (frame["city_id"] == "NAVA").astype(int)

    required = [f"lag_{lag}" for lag in LAGS]
    return frame.dropna(subset=required).reset_index(drop=True)


def feature_columns(frame: pd.DataFrame) -> list:
    """Enumera las columnas que entran al modelo.

    Entrada:
        frame: tabla de variables construida por build_features.

    Salida:
        Lista de nombres de columna en orden estable.

    Funcionalidad:
        Deja fuera identificadores, fechas y la propia columna objetivo, para
        que el modelo no aprenda de la pieza concreta sino de su comportamiento.
    """
    excluded = {
        "sku_id", "city_id", "period_month", "qty_issued", "issue_events",
        "breakdown_events", "criticality",
    }
    return [column for column in frame.columns if column not in excluded]


def temporal_split(frame: pd.DataFrame, validation_months: int) -> tuple:
    """Parte la tabla en entrenamiento y validacion respetando el tiempo.

    Entrada:
        frame: tabla de variables con la columna period_month.
        validation_months: cuantos meses finales se reservan para validar.

    Salida:
        Tupla (entrenamiento, validacion) de DataFrames.

    Funcionalidad:
        Corta por fecha y no al azar. Una particion aleatoria dejaria meses
        futuros dentro del entrenamiento y produciria una metrica optimista que
        no se sostiene en produccion.
    """
    months = sorted(frame["period_month"].unique())
    cutoff = months[-validation_months]
    return (frame[frame["period_month"] < cutoff].copy(),
            frame[frame["period_month"] >= cutoff].copy())


def regression_metrics(actual: np.ndarray, predicted: np.ndarray) -> dict:
    """Calcula el error de una proyeccion.

    Entrada:
        actual: valores realmente observados.
        predicted: valores proyectados por el modelo.

    Salida:
        Diccionario con mae, rmse, mape, smape, wmape y bias.

    Funcionalidad:
        El porcentaje clasico se calcula solo sobre los meses con consumo, ya
        que la demanda de repuestos tiene meses en cero y dividir entre cero lo
        volveria infinito. La metrica de cabecera es el error ponderado sobre el
        total consumido, que si admite ceros y es la que refleja el impacto real
        sobre el inventario.
    """
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    error = predicted - actual
    absolute = np.abs(error)

    total = actual.sum()
    non_zero = actual > 0
    mape = float(np.mean(absolute[non_zero] / actual[non_zero])) if non_zero.any() else 0.0
    denominator = np.abs(actual) + np.abs(predicted)
    smape_terms = np.where(denominator > 0, 2 * absolute / np.where(denominator > 0, denominator, 1), 0.0)

    return {
        "mae": float(absolute.mean()),
        "rmse": float(np.sqrt((error ** 2).mean())),
        "mape": mape,
        "smape": float(smape_terms.mean()),
        "wmape": float(absolute.sum() / total) if total > 0 else 0.0,
        "bias": float(error.mean()),
    }


def naive_baseline(validation: pd.DataFrame) -> dict:
    """Mide el error de la referencia mas simple posible.

    Entrada:
        validation: partición de validacion con la columna lag_1.

    Salida:
        Diccionario de metricas de la referencia.

    Funcionalidad:
        Proyecta que cada mes repite el consumo del mes anterior. Es el listón
        que cualquier modelo debe superar para justificar su existencia.
    """
    return regression_metrics(validation["qty_issued"], validation["lag_1"])


def moving_average_baseline(validation: pd.DataFrame) -> dict:
    """Mide el error del promedio movil que usa la proyeccion estadistica.

    Entrada:
        validation: partición de validacion con la columna roll_mean_6.

    Salida:
        Diccionario de metricas de la referencia.

    Funcionalidad:
        Reproduce el metodo que hoy aplica el servicio de proyeccion a la
        mayoria de las series, para poder comparar el modelo contra lo que ya
        esta en produccion y no solo contra la referencia trivial.
    """
    return regression_metrics(validation["qty_issued"], validation["roll_mean_6"])


# Load environment from .env and prefer configured tracking URI when available
try:
    dotenv.load_dotenv()
except Exception:
    pass

try:
    from app.core.config import settings
    if getattr(settings, "MLFLOW_TRACKING_URI", None):
        os.environ.setdefault("MLFLOW_TRACKING_URI", str(settings.MLFLOW_TRACKING_URI))
except Exception:
    # If importing settings fails or value missing, continue — environment may be set externally
    pass


class DemandModel(BaseModel):
    """Modelo global de proyeccion de demanda de refacciones.

    Funcionalidad:
        Ajusta un unico estimador sobre todas las series y expone las metricas
        de validacion junto con la comparacion contra las referencias. Al
        heredar de BaseModel, fit_and_save registra en MLflow los parametros,
        las metricas y los artefactos de cada entrenamiento.
    """

    project = PROJECT

    def train(self, X, y, **params) -> dict:
        """Ajusta el modelo y devuelve sus metricas de validacion.

        Entrada:
            X: diccionario con las particiones train y val de variables.
            y: diccionario con las particiones train y val del objetivo.
            params: hiperparametros que sobreescriben los de configuracion.

        Salida:
            Diccionario de metricas con mape, mae, rmse y seconds, ademas de
            wmape, smape, bias y la mejora frente a las referencias.

        Funcionalidad:
            Entrena sobre la particion historica, proyecta la particion reciente
            y compara el error contra la repeticion del ultimo mes y contra el
            promedio movil. Guarda las predicciones de validacion para poder
            graficarlas despues.
        """
        started = time.perf_counter()
        settings = {**MODEL_PARAMS, **params}

        self.model = HistGradientBoostingRegressor(**settings)
        self.model.fit(X["train"], y["train"])

        predicted = np.clip(self.model.predict(X["val"]), 0, None)
        metrics = regression_metrics(y["val"], predicted)

        self.validation_predictions = predicted
        self.feature_names = list(X["train"].columns)

        baselines = getattr(self, "baselines", {})
        for name, reference in baselines.items():
            metrics[f"wmape_{name}"] = reference["wmape"]
            if reference["wmape"] > 0:
                improvement = 1 - metrics["wmape"] / reference["wmape"]
                metrics[f"mejora_vs_{name}"] = round(float(improvement), 4)

        metrics["seconds"] = round(time.perf_counter() - started, 3)
        metrics["n_train"] = len(X["train"])
        metrics["n_val"] = len(X["val"])
        self.metrics = metrics
        return metrics

    def predict(self, X):
        """Proyecta la demanda de las filas indicadas.

        Entrada:
            X: DataFrame de variables con las mismas columnas del entrenamiento.

        Salida:
            Arreglo de proyecciones no negativas.

        Funcionalidad:
            Recorta en cero porque una demanda negativa no tiene sentido
            operativo y confundiria al optimizador.
        """
        return np.clip(self.model.predict(X), 0, None)


def permutation_importance(model, X, y, repeats: int = 5) -> pd.DataFrame:
    """Mide cuanto aporta cada variable al modelo.

    Entrada:
        model: modelo ya entrenado.
        X: variables de validacion.
        y: objetivo de validacion.
        repeats: cuantas veces se baraja cada variable.

    Salida:
        DataFrame con la variable y el deterioro medio del error al barajarla,
        ordenado de mayor a menor aporte.

    Funcionalidad:
        Baraja cada columna por separado y mide cuanto empeora el error. Si
        barajarla no cambia nada, esa variable no estaba aportando. Es una
        lectura directa de que informacion sostiene la proyeccion.
    """
    rng = np.random.default_rng(MODEL_PARAMS["random_state"])
    baseline = regression_metrics(y, np.clip(model.predict(X), 0, None))["wmape"]

    rows = []
    for column in X.columns:
        damaged = []
        for _ in range(repeats):
            shuffled = X.copy()
            shuffled[column] = rng.permutation(shuffled[column].to_numpy())
            score = regression_metrics(y, np.clip(model.predict(shuffled), 0, None))["wmape"]
            damaged.append(score - baseline)
        rows.append({"variable": column, "aporte": float(np.mean(damaged))})

    return pd.DataFrame(rows).sort_values("aporte", ascending=False).reset_index(drop=True)
