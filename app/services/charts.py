"""Generacion de graficas del entrenamiento.

Funcionalidad:
    Produce las figuras que permiten juzgar si el modelo sirve: cuanto mejora
    frente a las referencias, que tan cerca quedan sus proyecciones de lo
    observado, como se reparte el error y que variables lo sostienen.

    Las figuras se guardan como imagenes en la carpeta de artefactos y la
    interfaz las sirve tal cual, sin necesidad de una libreria de graficas en el
    navegador.
"""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from app.core.training import ARTIFACT_DIR, CHART_FILES

PRIMARY = "#003B70"
SECONDARY = "#0067A0"
LIGHT = "#D9EAF4"
TEXT = "#1F2933"
MUTED = "#667085"
SUCCESS = "#2E7D32"
WARNING = "#C88700"
DANGER = "#C62828"
SURFACE = "#FFFFFF"


def _style(axes) -> None:
    """Aplica la identidad visual del proyecto a unos ejes.

    Entrada:
        axes: ejes de matplotlib a formatear.

    Salida:
        Ninguna. Modifica los ejes recibidos.

    Funcionalidad:
        Retira el marco superior y derecho, atenua la rejilla y alinea colores y
        tamaños con la paleta corporativa que usa la interfaz, para que graficas
        y pantalla se lean como un mismo producto.
    """
    axes.spines["top"].set_visible(False)
    axes.spines["right"].set_visible(False)
    axes.spines["left"].set_color("#CBD5E1")
    axes.spines["bottom"].set_color("#CBD5E1")
    axes.tick_params(colors=MUTED, labelsize=9)
    axes.grid(axis="y", color="#E3E8EF", linewidth=0.8)
    axes.set_axisbelow(True)
    axes.title.set_color(TEXT)
    axes.xaxis.label.set_color(MUTED)
    axes.yaxis.label.set_color(MUTED)


def _save(figure, filename: str):
    """Guarda una figura en la carpeta de artefactos.

    Entrada:
        figure: figura de matplotlib.
        filename: nombre del archivo de salida.

    Salida:
        Ruta del archivo escrito.

    Funcionalidad:
        Crea la carpeta si hace falta, ajusta margenes y cierra la figura para
        no acumular memoria cuando se generan varias seguidas.
    """
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    path = ARTIFACT_DIR / filename
    figure.tight_layout()
    figure.savefig(path, dpi=140, facecolor=SURFACE)
    plt.close(figure)
    return path


def chart_model_vs_baselines(metrics: dict, baselines: dict):
    """Compara el error del modelo contra las referencias.

    Entrada:
        metrics: metricas del modelo entrenado.
        baselines: diccionario de referencias con sus metricas.

    Salida:
        Ruta de la imagen generada.

    Funcionalidad:
        Muestra el error ponderado de cada alternativa en barras horizontales.
        Es la grafica que responde a la pregunta de si el modelo aporta algo
        sobre lo que ya habia.
    """
    labels = ["Modelo global"] + [name.replace("_", " ").capitalize() for name in baselines]
    values = [metrics["wmape"]] + [reference["wmape"] for reference in baselines.values()]
    colors = [SUCCESS if values[0] == min(values) else WARNING] + [MUTED] * len(baselines)

    figure, axes = plt.subplots(figsize=(7.2, 2.6 + 0.4 * len(labels)))
    bars = axes.barh(labels, values, color=colors, height=0.55)
    axes.invert_yaxis()
    axes.set_xlabel("WMAPE en validación (menor es mejor)")
    axes.set_title("Error del modelo frente a las referencias", fontsize=12, fontweight="bold", loc="left")
    axes.xaxis.set_major_formatter(lambda x, _: f"{x:.0%}")

    for bar, value in zip(bars, values):
        axes.text(value + max(values) * 0.015, bar.get_y() + bar.get_height() / 2,
                  f"{value:.1%}", va="center", fontsize=10, color=TEXT, fontweight="600")

    axes.set_xlim(0, max(values) * 1.18)
    _style(axes)
    return _save(figure, CHART_FILES["comparison"])


def chart_predicted_vs_actual(actual, predicted):
    """Contrasta cada proyeccion con lo realmente consumido.

    Entrada:
        actual: valores observados en validacion.
        predicted: proyecciones del modelo.

    Salida:
        Ruta de la imagen generada.

    Funcionalidad:
        Dispersa ambos valores contra la diagonal de acierto perfecto. Los
        puntos por encima de la linea son sobreestimaciones, que producen
        sobrestock, y los de debajo subestimaciones, que producen quiebres.
    """
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    top = max(actual.max(), predicted.max()) * 1.05

    figure, axes = plt.subplots(figsize=(5.6, 5.2))
    axes.plot([0, top], [0, top], color=MUTED, linewidth=1, linestyle="--", zorder=1)
    axes.scatter(actual, predicted, s=26, color=SECONDARY, alpha=0.55,
                 edgecolor=PRIMARY, linewidth=0.4, zorder=2)
    axes.set_xlabel("Consumo real (unidades/mes)")
    axes.set_ylabel("Proyección del modelo")
    axes.set_title("Proyección frente a consumo real", fontsize=12, fontweight="bold", loc="left")
    axes.set_xlim(0, top)
    axes.set_ylim(0, top)
    _style(axes)
    return _save(figure, CHART_FILES["scatter"])


def chart_error_distribution(actual, predicted):
    """Muestra como se reparte el error de proyeccion.

    Entrada:
        actual: valores observados en validacion.
        predicted: proyecciones del modelo.

    Salida:
        Ruta de la imagen generada.

    Funcionalidad:
        Un histograma centrado en cero indica un modelo sin sesgo. Si la masa se
        desplaza a un lado, el modelo compra de mas o de menos de forma
        sistematica, que es un problema distinto a equivocarse mucho.
    """
    error = np.asarray(predicted, dtype=float) - np.asarray(actual, dtype=float)

    figure, axes = plt.subplots(figsize=(7.0, 3.4))
    axes.hist(error, bins=28, color=LIGHT, edgecolor=SECONDARY, linewidth=0.8)
    axes.axvline(0, color=PRIMARY, linewidth=1.4)
    axes.axvline(error.mean(), color=DANGER, linewidth=1.4, linestyle="--",
                 label=f"Sesgo medio {error.mean():+.2f}")
    axes.set_xlabel("Error de proyección (unidades)")
    axes.set_ylabel("Casos")
    axes.set_title("Distribución del error", fontsize=12, fontweight="bold", loc="left")
    axes.legend(frameon=False, fontsize=9, labelcolor=TEXT)
    _style(axes)
    return _save(figure, CHART_FILES["errors"])


def chart_feature_importance(importance, top: int = 12):
    """Ordena las variables por su aporte al modelo.

    Entrada:
        importance: DataFrame con las columnas variable y aporte.
        top: cuantas variables mostrar.

    Salida:
        Ruta de la imagen generada.

    Funcionalidad:
        Hace auditable de que se alimenta la proyeccion. Si el modelo dependiera
        de una variable sin sentido operativo, aqui se veria.
    """
    data = importance.head(top).iloc[::-1]

    figure, axes = plt.subplots(figsize=(7.2, 0.34 * len(data) + 1.9))
    axes.barh(data["variable"], data["aporte"], color=SECONDARY, height=0.6)
    axes.set_xlabel("Deterioro del error al barajar la variable")
    axes.set_title("Qué sostiene la proyección", fontsize=12, fontweight="bold", loc="left")
    _style(axes)
    return _save(figure, CHART_FILES["importance"])


def chart_validation_series(validation, predicted, series_count: int = 4):
    """Dibuja la proyeccion mes a mes de algunas series.

    Entrada:
        validation: partición de validacion con sku_id, city_id, period_month y
            qty_issued.
        predicted: proyecciones del modelo alineadas con la partición.
        series_count: cuantas series mostrar.

    Salida:
        Ruta de la imagen generada.

    Funcionalidad:
        Las metricas agregadas esconden el comportamiento por pieza. Aqui se ve
        si el modelo sigue la forma de la demanda o solo acierta el promedio,
        que es lo que un revisor de negocio quiere comprobar.
    """
    frame = validation.copy()
    frame["prediccion"] = predicted
    volumes = frame.groupby(["sku_id", "city_id"])["qty_issued"].sum()
    chosen = volumes.nlargest(series_count).index

    rows = (len(chosen) + 1) // 2
    figure, grid = plt.subplots(rows, 2, figsize=(11, 2.7 * rows), squeeze=False)

    for position, (sku, city) in enumerate(chosen):
        axes = grid[position // 2][position % 2]
        subset = frame[(frame.sku_id == sku) & (frame.city_id == city)].sort_values("period_month")
        months = [m[-2:] + "/" + m[2:4] for m in subset["period_month"]]
        axes.plot(months, subset["qty_issued"], marker="o", markersize=4,
                  color=PRIMARY, linewidth=1.6, label="Real")
        axes.plot(months, subset["prediccion"], marker="s", markersize=4,
                  color=WARNING, linewidth=1.6, linestyle="--", label="Modelo")
        axes.set_title(f"{sku} · {city}", fontsize=10, fontweight="600", loc="left")
        axes.legend(frameon=False, fontsize=8, labelcolor=TEXT)
        _style(axes)

    for empty in range(len(chosen), rows * 2):
        grid[empty // 2][empty % 2].axis("off")

    figure.suptitle("Proyección mes a mes en validación", fontsize=12,
                    fontweight="bold", color=TEXT, x=0.01, ha="left")
    return _save(figure, CHART_FILES["series"])


def build_all_charts(metrics: dict, baselines: dict, validation, predicted,
                     importance) -> dict:
    """Genera el juego completo de graficas del entrenamiento.

    Entrada:
        metrics: metricas del modelo.
        baselines: metricas de las referencias.
        validation: partición de validacion.
        predicted: proyecciones sobre esa partición.
        importance: aporte de cada variable.

    Salida:
        Diccionario con el nombre logico de cada grafica y su ruta.

    Funcionalidad:
        Centraliza la generacion para que el entrypoint de entrenamiento no
        tenga que conocer cada figura por separado.
    """
    actual = validation["qty_issued"]
    return {
        "comparison": str(chart_model_vs_baselines(metrics, baselines)),
        "scatter": str(chart_predicted_vs_actual(actual, predicted)),
        "errors": str(chart_error_distribution(actual, predicted)),
        "importance": str(chart_feature_importance(importance)),
        "series": str(chart_validation_series(validation, predicted)),
    }
