"""Generacion de graficas del entrenamiento.

Funcionalidad:
    Produce las figuras que permiten juzgar si el modelo sirve: cuanto mejora
    frente a las referencias, que tan cerca quedan sus proyecciones de lo
    observado, como se reparte el error y que variables lo sostienen.

    Las figuras se guardan como imagenes en la carpeta de artefactos y la
    interfaz las sirve tal cual, sin necesidad de una libreria de graficas en el
    navegador.
"""

import textwrap

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from app.core.pipeline import (
    ARTIFACT_DIR as PIPELINE_DIR,
)
from app.core.pipeline import (
    CHART_FILES as PIPELINE_CHART_FILES,
)
from app.core.pipeline import (
    KIND_DISCARD,
)
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


def _save(figure, filename: str, directory=None):
    """Guarda una figura en una carpeta de artefactos.

    Entrada:
        figure: figura de matplotlib.
        filename: nombre del archivo de salida.
        directory: carpeta destino. Si no se indica, la del entrenamiento.

    Salida:
        Ruta del archivo escrito.

    Funcionalidad:
        Crea la carpeta si hace falta, ajusta margenes y cierra la figura para
        no acumular memoria cuando se generan varias seguidas.

        El destino es un parametro porque las graficas del entrenamiento y las
        del recorrido del pipeline se publican por separado, pero comparten
        estilo y no tendria sentido duplicar el guardado.
    """
    target = directory or ARTIFACT_DIR
    target.mkdir(parents=True, exist_ok=True)
    path = target / filename
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
    axes.set_title(
        "Error del modelo frente a las referencias", fontsize=12, fontweight="bold", loc="left"
    )
    axes.xaxis.set_major_formatter(lambda x, _: f"{x:.0%}")

    for bar, value in zip(bars, values, strict=False):
        axes.text(
            value + max(values) * 0.015,
            bar.get_y() + bar.get_height() / 2,
            f"{value:.1%}",
            va="center",
            fontsize=10,
            color=TEXT,
            fontweight="600",
        )

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
        exceso de existencias, y los de debajo subestimaciones, que producen
        quiebres.
    """
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    top = max(actual.max(), predicted.max()) * 1.05

    figure, axes = plt.subplots(figsize=(5.6, 5.2))
    axes.plot([0, top], [0, top], color=MUTED, linewidth=1, linestyle="--", zorder=1)
    axes.scatter(
        actual,
        predicted,
        s=26,
        color=SECONDARY,
        alpha=0.55,
        edgecolor=PRIMARY,
        linewidth=0.4,
        zorder=2,
    )
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
    axes.axvline(
        error.mean(),
        color=DANGER,
        linewidth=1.4,
        linestyle="--",
        label=f"Sesgo medio {error.mean():+.2f}",
    )
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
        axes.plot(
            months,
            subset["qty_issued"],
            marker="o",
            markersize=4,
            color=PRIMARY,
            linewidth=1.6,
            label="Real",
        )
        axes.plot(
            months,
            subset["prediccion"],
            marker="s",
            markersize=4,
            color=WARNING,
            linewidth=1.6,
            linestyle="--",
            label="Modelo",
        )
        axes.set_title(f"{sku} · {city}", fontsize=10, fontweight="600", loc="left")
        axes.legend(frameon=False, fontsize=8, labelcolor=TEXT)
        _style(axes)

    for empty in range(len(chosen), rows * 2):
        grid[empty // 2][empty % 2].axis("off")

    figure.suptitle(
        "Proyección mes a mes en validación",
        fontsize=12,
        fontweight="bold",
        color=TEXT,
        x=0.01,
        ha="left",
    )
    return _save(figure, CHART_FILES["series"])


def _wrap(text: str, width: int) -> str:
    """Parte un texto largo en varias lineas para usarlo como etiqueta.

    Entrada:
        text: texto a repartir.
        width: ancho maximo de cada linea en caracteres.

    Salida:
        El mismo texto con saltos de linea entre palabras.

    Funcionalidad:
        Las etiquetas de categoria de las graficas horizontales son frases
        completas. Cortarlas por longitud dejaria palabras partidas y perderia el
        final del motivo, que suele ser la parte que explica la decision.
    """
    return "\n".join(textwrap.wrap(text, width=width)) or text


def _headline(figure, text: str) -> None:
    """Coloca el titulo alineado al borde izquierdo de la figura.

    Entrada:
        figure: figura de matplotlib.
        text: titulo a mostrar.

    Salida:
        Ninguna. Modifica la figura recibida.

    Funcionalidad:
        En las graficas de barras horizontales las etiquetas de categoria son
        largas y empujan los ejes hacia la derecha, con lo que un titulo alineado
        al eje termina descolgado en mitad de la imagen. Anclarlo a la figura lo
        deja siempre donde empieza a leerse.
    """
    figure.suptitle(text, fontsize=12, fontweight="bold", color=TEXT, x=0.01, ha="left")


def chart_cleaning_funnel(cleaning: dict):
    """Muestra cuantas filas descarto cada regla de limpieza.

    Entrada:
        cleaning: resumen de la etapa de limpieza, con sus fuentes y reglas.

    Salida:
        Ruta de la imagen generada.

    Funcionalidad:
        Solo dibuja las reglas que eliminan filas. Las que rellenan un nulo o
        marcan una lectura atipica tocan decenas de miles de filas sin quitar
        ninguna, y mezclarlas daria la impresion falsa de que se tiro medio
        dataset.

        Cada barra lleva el enunciado de la regla, porque el numero sin el motivo
        no permite juzgar si el descarte estuvo bien hecho.
    """
    rows = [
        (f"{_wrap(rule['rule'], 44)}\n{source['name']}", rule["rows"])
        for source in cleaning["sources"]
        for rule in source["rules"]
        if rule["kind"] == KIND_DISCARD
    ]
    rows.sort(key=lambda item: item[1])

    figure, axes = plt.subplots(figsize=(8.4, 1.3 + 0.82 * max(len(rows), 1)))

    if rows:
        labels = [label for label, _ in rows]
        values = [value for _, value in rows]
        bars = axes.barh(labels, values, color=WARNING, height=0.55)
        for bar, value in zip(bars, values, strict=False):
            axes.text(
                value + max(values) * 0.02,
                bar.get_y() + bar.get_height() / 2,
                f"{value:,}".replace(",", "."),
                va="center",
                fontsize=9,
                color=TEXT,
                fontweight="600",
            )
        axes.set_xlim(0, max(values) * 1.2)
    else:
        axes.text(
            0.5,
            0.5,
            "Ninguna regla descarto filas",
            ha="center",
            va="center",
            color=MUTED,
            transform=axes.transAxes,
        )

    axes.set_xlabel("Filas descartadas")
    axes.tick_params(axis="y", labelsize=8)
    _style(axes)
    _headline(
        figure,
        f"De {cleaning['rows_before']:,} filas crudas quedan {cleaning['rows_after']:,}".replace(
            ",", "."
        ),
    )
    return _save(figure, PIPELINE_CHART_FILES["limpieza"], PIPELINE_DIR)


def chart_demand_history(dataset: dict):
    """Dibuja la demanda mensual distinguiendo lo real de lo simulado.

    Entrada:
        dataset: resumen de la etapa de dataset, con la serie mensual agregada.

    Salida:
        Ruta de la imagen generada.

    Funcionalidad:
        Es la grafica que impide confundir el ejercicio con un historico real. La
        mitad de los meses se simularon para alcanzar los 72 que exige detectar
        estacionalidad, y aqui se ve exactamente cuales y donde empieza el dato
        observado.
    """
    monthly = dataset["monthly"]
    months = [row["period_month"] for row in monthly]
    values = [row["qty_issued"] for row in monthly]
    synthetic = [row["is_synthetic"] for row in monthly]

    figure, axes = plt.subplots(figsize=(11, 3.4))
    axes.plot(months, values, color=PRIMARY, linewidth=1.6)
    axes.fill_between(months, values, color=LIGHT, alpha=0.7)

    boundary = next((index for index, flag in enumerate(synthetic) if not flag), None)
    if boundary:
        axes.axvspan(months[0], months[boundary - 1], color=WARNING, alpha=0.10)
        axes.axvline(months[boundary - 1], color=WARNING, linewidth=1.2, linestyle="--")
        axes.text(
            months[0],
            max(values) * 0.95,
            " Meses simulados",
            color=WARNING,
            fontsize=9,
            fontweight="600",
            va="top",
        )
        axes.text(
            months[boundary],
            max(values) * 0.95,
            " Meses observados",
            color=PRIMARY,
            fontsize=9,
            fontweight="600",
            va="top",
        )

    step = max(1, len(months) // 12)
    axes.set_xticks(months[::step])
    axes.set_xticklabels(months[::step], rotation=45, ha="right", fontsize=8)
    axes.set_ylabel("Unidades consumidas")
    axes.set_title(
        f"{dataset['months']} meses de demanda · {dataset['series']} series",
        fontsize=12,
        fontweight="bold",
        loc="left",
    )
    _style(axes)
    return _save(figure, PIPELINE_CHART_FILES["dataset"], PIPELINE_DIR)


def chart_pattern_map(patterns: dict):
    """Sitúa cada serie frente a los umbrales que deciden su patron.

    Entrada:
        patterns: resumen de la etapa de patrones, con un punto por serie y los
            umbrales aplicados.

    Salida:
        Ruta de la imagen generada.

    Funcionalidad:
        Hace auditable la clasificacion. Con los dos umbrales dibujados se ve que
        serie quedo al filo y por cual de las dos condiciones no paso, que es
        justo lo que hay que revisar antes de tocar un umbral.
    """
    colors = {
        "Estable": SECONDARY,
        "Volatil": WARNING,
        "Estacional": SUCCESS,
        "Tendencia": PRIMARY,
        "Insuficiente": DANGER,
    }

    figure, axes = plt.subplots(figsize=(7.6, 4.8))

    for label in sorted({point["pattern"] for point in patterns["points"]}):
        subset = [point for point in patterns["points"] if point["pattern"] == label]
        axes.scatter(
            [point["cv"] for point in subset],
            [point["seasonal_strength"] for point in subset],
            s=44,
            alpha=0.75,
            label=f"{label} ({len(subset)})",
            color=colors.get(label, MUTED),
            edgecolor=SURFACE,
            linewidth=0.6,
        )

    thresholds = patterns["thresholds"]
    axes.axvline(thresholds["cv_volatile"], color=MUTED, linewidth=1, linestyle="--")
    axes.axhline(thresholds["seasonal_strength"], color=MUTED, linewidth=1, linestyle="--")
    axes.text(
        thresholds["cv_volatile"],
        axes.get_ylim()[1],
        f" volatil si CV > {thresholds['cv_volatile']}",
        color=MUTED,
        fontsize=8,
        va="top",
    )
    axes.text(
        axes.get_xlim()[0],
        thresholds["seasonal_strength"],
        f" estacional si fuerza ≥ {thresholds['seasonal_strength']} y p < "
        f"{thresholds['seasonal_pvalue']}",
        color=MUTED,
        fontsize=8,
        va="bottom",
    )

    axes.set_xlabel("Coeficiente de variacion (σ/μ)")
    axes.set_ylabel("Fuerza estacional")
    axes.set_title(
        "Por que cada serie cayo en su patron", fontsize=12, fontweight="bold", loc="left"
    )
    axes.legend(frameon=False, fontsize=8, labelcolor=TEXT, loc="upper right")
    _style(axes)
    return _save(figure, PIPELINE_CHART_FILES["patrones"], PIPELINE_DIR)


def chart_decision_breakdown(optimization: dict):
    """Desglosa las decisiones de compra por su motivo.

    Entrada:
        optimization: resumen de la etapa de optimizacion, con el reparto por
            decision y por motivo.

    Salida:
        Ruta de la imagen generada.

    Funcionalidad:
        El reparto por decision se queda corto: saber que hay 22 no compras no
        dice nada, saber que todas lo son por estar por encima del minimo si.
        Cada barra es un motivo, coloreado segun la decision a la que lleva.
    """
    colors = {"COMPRAR": SUCCESS, "REVISAR": WARNING, "APLAZADO": DANGER, "NO_COMPRAR": MUTED}
    reasons = list(reversed(optimization["reasons"]))

    labels = [f"{_wrap(item['reason'], 46)}\n{item['decision']}" for item in reasons]
    values = [item["count"] for item in reasons]
    bar_colors = [colors.get(item["decision"], MUTED) for item in reasons]

    figure, axes = plt.subplots(figsize=(9.0, 1.4 + 0.92 * max(len(reasons), 1)))
    bars = axes.barh(labels, values, color=bar_colors, height=0.6)

    for bar, value in zip(bars, values, strict=False):
        axes.text(
            value + max(values) * 0.02,
            bar.get_y() + bar.get_height() / 2,
            str(value),
            va="center",
            fontsize=10,
            color=TEXT,
            fontweight="600",
        )

    total = sum(optimization["counts"].values())
    axes.set_xlim(0, max(values) * 1.15)
    axes.set_xlabel("Combinaciones pieza-ciudad")
    axes.tick_params(axis="y", labelsize=8)
    _style(axes)
    _headline(figure, f"De donde salen las {total} decisiones")
    return _save(figure, PIPELINE_CHART_FILES["decisiones"], PIPELINE_DIR)


def chart_optimizer_saving(optimization: dict):
    """Compara lo que costo cada compra con la peor oferta disponible.

    Entrada:
        optimization: resumen de la etapa de optimizacion, con el ahorro por
            caso.

    Salida:
        Ruta de la imagen generada.

    Funcionalidad:
        Es la lectura honesta de que aporta el optimizador. La referencia no es
        no comprar nada, sino haber elegido mal entre las ofertas que si podian
        surtir el caso, que es el error que el sistema evita.
    """
    savings = optimization["savings"]

    figure, axes = plt.subplots(figsize=(8.6, 1.2 + 0.5 * max(len(savings), 1)))

    if savings:
        labels = [f"{item['sku_id']} · {item['city_id']}" for item in savings]
        chosen = [item["chosen_cost_usd"] for item in savings]
        worst = [item["worst_cost_usd"] for item in savings]
        positions = range(len(savings))

        axes.barh(list(positions), worst, color=LIGHT, height=0.62, label="Peor oferta aplicable")
        axes.barh(list(positions), chosen, color=SECONDARY, height=0.62, label="Oferta elegida")
        axes.set_yticks(list(positions))
        axes.set_yticklabels(labels, fontsize=8)
        axes.invert_yaxis()

        for position, item in zip(positions, savings, strict=False):
            if item["saving_usd"] > 0:
                axes.text(
                    item["worst_cost_usd"] * 1.01,
                    position,
                    f"−{item['saving_usd']:,.0f} USD".replace(",", "."),
                    va="center",
                    fontsize=8,
                    color=SUCCESS,
                    fontweight="600",
                )

        axes.set_xlim(0, max(worst) * 1.22)
        axes.legend(frameon=False, fontsize=9, labelcolor=TEXT, loc="lower right")
    else:
        axes.text(
            0.5,
            0.5,
            "Ninguna compra tuvo mas de una oferta aplicable",
            ha="center",
            va="center",
            color=MUTED,
            transform=axes.transAxes,
        )

    axes.set_xlabel("Costo total de la orden (USD)")
    axes.set_title(
        f"El optimizador evita {optimization['saving_usd']:,.0f} USD de sobrecosto".replace(
            ",", "."
        ),
        fontsize=12,
        fontweight="bold",
        loc="left",
    )
    _style(axes)
    return _save(figure, PIPELINE_CHART_FILES["ahorro"], PIPELINE_DIR)


def build_pipeline_charts(stages: list) -> dict:
    """Genera las graficas del recorrido del pipeline.

    Entrada:
        stages: lista de resumenes de etapa, en el orden del pipeline.

    Salida:
        Diccionario con el nombre logico de cada grafica y su ruta.

    Funcionalidad:
        Centraliza la generacion para que el entrypoint no tenga que conocer que
        grafica corresponde a que etapa. Las del modelo no se generan aqui: las
        produce el entrenamiento y se sirven desde su propia carpeta.
    """
    by_id = {stage["id"]: stage for stage in stages}
    return {
        "limpieza": str(chart_cleaning_funnel(by_id["limpieza"])),
        "dataset": str(chart_demand_history(by_id["dataset"])),
        "patrones": str(chart_pattern_map(by_id["patrones"])),
        "decisiones": str(chart_decision_breakdown(by_id["optimizacion"])),
        "ahorro": str(chart_optimizer_saving(by_id["optimizacion"])),
    }


def build_all_charts(metrics: dict, baselines: dict, validation, predicted, importance) -> dict:
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
