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

from app.core.optimization import DECISION_LABELS
from app.core.patterns import PATTERN_LABELS
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


BASELINE_NAMES = {
    "ultimo_mes": "Repeat last month",
    "promedio_movil": "Moving average, 6 months",
}


def chart_model_vs_baselines(metrics: dict, baselines: dict):
    """Compara el modelo contra las referencias en las metricas que deciden.

    Entrada:
        metrics: metricas del modelo entrenado.
        baselines: diccionario de referencias con sus metricas.

    Salida:
        Ruta de la imagen generada.

    Funcionalidad:
        Dibuja dos paneles porque una sola cifra aqui enganaria.

        El de la izquierda es el error cuadratico, que se minimiza con la media
        —y la media es exactamente lo que consume la politica de inventario,
        porque la demanda durante el plazo se construye con ella—.

        El de la derecha es el sesgo acumulado, que dice en unidades cuanto
        quedaria de mas o de menos en bodega al cabo de la validacion. Es la
        cifra con consecuencia operativa directa y la unica que distingue un
        metodo que se equivoca en las dos direcciones de uno que se equivoca
        siempre hacia el mismo lado.

        La version anterior mostraba el error ponderado, y sobre demanda
        intermitente ese ranking esta invertido: el error absoluto se minimiza
        con la mediana, que aqui es cero, asi que premia al metodo que proyecta
        menos. Un pronosticador que dijera que nada se consume nunca ganaba esa
        grafica, y dejaria las dos plantas sin refacciones.
    """
    labels = ["Global model"] + [
        BASELINE_NAMES.get(name, name.replace("_", " ").capitalize()) for name in baselines
    ]
    rmse = [metrics["rmse"]] + [reference["rmse"] for reference in baselines.values()]
    drift = [metrics.get("cumulative_bias", 0.0)] + [
        reference.get("cumulative_bias", 0.0) for reference in baselines.values()
    ]

    figure, (left, right) = plt.subplots(
        1, 2, figsize=(10.4, 2.4 + 0.5 * len(labels)), gridspec_kw={"width_ratios": [1, 1]}
    )

    best = min(rmse)
    bars = left.barh(
        labels,
        rmse,
        color=[SUCCESS if value == best else MUTED for value in rmse],
        height=0.55,
    )
    left.invert_yaxis()
    left.set_xlabel("RMSE on validation (lower is better)")
    left.set_title("Squared error", fontsize=11, fontweight="bold", loc="left")
    for bar, value in zip(bars, rmse, strict=False):
        left.text(
            value + max(rmse) * 0.02,
            bar.get_y() + bar.get_height() / 2,
            f"{value:.2f}",
            va="center",
            fontsize=10,
            color=TEXT,
            fontweight="600",
        )
    left.set_xlim(0, max(rmse) * 1.2)
    _style(left)

    span = max(abs(value) for value in drift) or 1.0
    best = min(abs(value) for value in drift)

    def drift_color(value):
        """Colorea el sesgo por su magnitud y no por su signo.

        Entrada:
            value: sesgo acumulado del metodo, en unidades.

        Salida:
            Color de la barra.

        Funcionalidad:
            Lo que importa aqui es cuanto se desvia, no hacia donde. Colorear
            por signo pintaria de rojo al metodo mejor calibrado solo por
            quedarse ligeramente largo, que es lo contrario de lo que la
            grafica tiene que decir.
        """
        if abs(value) == span and span > best:
            return DANGER
        if abs(value) == best:
            return SUCCESS
        return MUTED

    bars = right.barh(
        labels,
        drift,
        color=[drift_color(value) for value in drift],
        height=0.55,
    )
    right.invert_yaxis()
    right.axvline(0, color=TEXT, linewidth=1)
    right.set_xlabel("Cumulative bias over the validation (units)")
    right.set_title("Where the stock would end up", fontsize=11, fontweight="bold", loc="left")
    for bar, value in zip(bars, drift, strict=False):
        offset = span * 0.03
        right.text(
            value + (offset if value >= 0 else -offset),
            bar.get_y() + bar.get_height() / 2,
            f"{value:+,.0f}",
            va="center",
            ha="left" if value >= 0 else "right",
            fontsize=10,
            color=TEXT,
            fontweight="600",
        )
    right.set_xlim(-span * 1.35, span * 1.35)
    right.tick_params(axis="y", labelleft=False)
    _style(right)

    figure.suptitle(
        "The model against the baselines, on the two metrics that decide",
        fontsize=12,
        fontweight="bold",
        x=0.008,
        ha="left",
        color=TEXT,
    )
    figure.tight_layout(rect=(0, 0, 1, 0.93))
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

        Los dos ejes van en escala logaritmica. En escala lineal un pico de 860
        unidades estira el eje entero y el 99 % de los puntos se apila contra el
        origen en una mancha de la que no se lee nada: la grafica anterior
        parecia decir que el modelo no acierta nunca, cuando lo que decia es que
        habia un valor extremo. Con escala logaritmica se ve donde vive la masa,
        que es entre una y treinta unidades al mes.

        Los ceros no caben en escala logaritmica y son la mayoria de los meses,
        asi que se cuentan aparte en el pie en vez de descartarse en silencio.
    """
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)

    drawable = (actual > 0) & (predicted > 0)
    hidden = int(len(actual) - drawable.sum())
    top = max(actual.max(), predicted.max()) * 1.3
    floor = 0.08

    figure, axes = plt.subplots(figsize=(5.8, 5.4))
    axes.plot([floor, top], [floor, top], color=MUTED, linewidth=1, linestyle="--", zorder=1)
    axes.scatter(
        actual[drawable],
        predicted[drawable],
        s=20,
        color=SECONDARY,
        alpha=0.4,
        edgecolor="none",
        zorder=2,
    )
    axes.set_xscale("log")
    axes.set_yscale("log")
    axes.set_xlim(floor, top)
    axes.set_ylim(floor, top)
    axes.set_xlabel("Actual consumption (units/month, log scale)")
    axes.set_ylabel("Model forecast (log scale)")
    axes.set_title("Forecast against actual consumption", fontsize=12, fontweight="bold", loc="left")
    axes.text(
        0.5,
        -0.16,
        f"{hidden:,} of {len(actual):,} months are not shown: one of the two values is zero, "
        "which has no place on a log axis",
        transform=axes.transAxes,
        ha="center",
        fontsize=8,
        color=MUTED,
    )
    _style(axes)
    figure.tight_layout()
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

        El eje se recorta al 1 % y 99 % de los errores. Sin recortar, un pico de
        demanda de 860 unidades que el modelo no vio llegar estira el eje hasta
        −860 y deja las 7.600 observaciones restantes dentro de una sola barra:
        el histograma dejaba de ser un histograma. Lo que queda fuera del
        recorte se anota en el pie, porque es justo la cola que interesa.
    """
    error = np.asarray(predicted, dtype=float) - np.asarray(actual, dtype=float)
    low, high = np.percentile(error, [1, 99])
    span = max(abs(low), abs(high))
    clipped = int((np.abs(error) > span).sum())

    figure, axes = plt.subplots(figsize=(8.0, 4.0))
    axes.hist(
        error[np.abs(error) <= span],
        bins=41,
        color=LIGHT,
        edgecolor=SECONDARY,
        linewidth=0.8,
        log=True,
    )
    axes.axvline(0, color=PRIMARY, linewidth=1.4)
    axes.axvline(
        error.mean(),
        color=DANGER,
        linewidth=1.4,
        linestyle="--",
        label=f"Mean bias {error.mean():+.2f} units/month",
    )
    axes.set_xlim(-span, span)
    axes.set_xlabel("Forecast error (units) — over-forecast to the right, short to the left")
    axes.set_ylabel("Months (log scale)")
    axes.set_title("Error distribution", fontsize=12, fontweight="bold", loc="left")
    axes.legend(frameon=False, fontsize=9, labelcolor=TEXT, loc="upper left")
    axes.text(
        0.0,
        -0.30,
        f"{clipped:,} of {len(error):,} months fall outside ±{span:,.0f} units and are not drawn:"
        "\nthe demand spikes no method anticipates, which is what the safety stock exists for",
        transform=axes.transAxes,
        ha="left",
        fontsize=8,
        color=MUTED,
    )
    _style(axes)
    figure.subplots_adjust(left=0.10, right=0.98, top=0.90, bottom=0.26)
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
    axes.set_xlabel("Error increase when the feature is shuffled")
    axes.set_title("What holds the forecast up", fontsize=12, fontweight="bold", loc="left")
    _style(axes)
    return _save(figure, CHART_FILES["importance"])


MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def month_label(period: str) -> str:
    """Convierte un periodo AAAA-MM en una etiqueta que no se confunda con fecha.

    Entrada:
        period: periodo mensual en formato AAAA-MM.

    Salida:
        Etiqueta corta con el mes en letras y el ano.

    Funcionalidad:
        La forma anterior era MM/AA, que sobre un eje de tiempo se lee como un
        dia: "07/29" parecia el 7 de 29 y no julio de 2029. El mes en letras no
        admite esa lectura.
    """
    year, _, month = period.partition("-")
    index = int(month) - 1 if month.isdigit() and 1 <= int(month) <= 12 else 0
    return f"{MONTH_NAMES[index]} {year}"


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

        Se reparten entre las dos plantas. Ordenando solo por volumen los cuatro
        paneles salian de Obregon y con la misma forma —un pico aislado sobre
        una linea plana—, de modo que la figura repetia cuatro veces la misma
        observacion. Alternando planta se ve al menos que el comportamiento es
        el mismo en las dos, que es una observacion distinta.
    """
    frame = validation.copy()
    frame["prediccion"] = predicted
    volumes = frame.groupby(["sku_id", "city_id"])["qty_issued"].sum().sort_values(ascending=False)

    quota = max(series_count // 2, 1)
    taken = {}
    chosen = []
    for sku, city in volumes.index:
        if taken.get(city, 0) >= quota and len(chosen) < series_count:
            continue
        chosen.append((sku, city))
        taken[city] = taken.get(city, 0) + 1
        if len(chosen) == series_count:
            break
    if len(chosen) < series_count:
        chosen = list(volumes.nlargest(series_count).index)

    rows = (len(chosen) + 1) // 2
    figure, grid = plt.subplots(rows, 2, figsize=(11, 2.7 * rows), squeeze=False)

    for position, (sku, city) in enumerate(chosen):
        axes = grid[position // 2][position % 2]
        subset = frame[(frame.sku_id == sku) & (frame.city_id == city)].sort_values("period_month")
        months = [month_label(m) for m in subset["period_month"]]
        axes.plot(
            months,
            subset["qty_issued"],
            marker="o",
            markersize=4,
            color=PRIMARY,
            linewidth=1.6,
            label="Actual",
        )
        axes.plot(
            months,
            subset["prediccion"],
            marker="s",
            markersize=4,
            color=WARNING,
            linewidth=1.6,
            linestyle="--",
            label="Model",
        )
        axes.set_title(f"{sku} · {city}", fontsize=10, fontweight="600", loc="left")
        axes.legend(frameon=False, fontsize=8, labelcolor=TEXT)
        _style(axes)

    for empty in range(len(chosen), rows * 2):
        grid[empty // 2][empty % 2].axis("off")

    figure.suptitle(
        "Month by month forecast on validation",
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

        El titular dice la proporcion y no solo el saldo. Este recorte se lleva
        buena parte de las lineas de la fuente —son referencias reales, pedidas
        una sola vez en seis anos— y esa proporcion es justamente lo que hay que
        poder defender en una revision. Un titular que dijera solo cuantas
        quedan la escondería.
    """
    rows = [
        (_wrap(rule["rule"], 46), rule["rows"])
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
                f"{value:,}",
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
            "No rule discarded any rows",
            ha="center",
            va="center",
            color=MUTED,
            transform=axes.transAxes,
        )

    axes.set_xlabel("Order lines discarded")
    axes.tick_params(axis="y", labelsize=8)
    _style(axes)

    before = cleaning["rows_before"]
    after = cleaning["rows_after"]
    share = (before - after) / before if before else 0.0
    _headline(
        figure,
        f"{before:,} raw order lines become {after:,} — {share:.0%} discarded",
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
            " Simulated months",
            color=WARNING,
            fontsize=9,
            fontweight="600",
            va="top",
        )
        axes.text(
            months[boundary],
            max(values) * 0.95,
            " Observed months",
            color=PRIMARY,
            fontsize=9,
            fontweight="600",
            va="top",
        )

    step = max(1, len(months) // 12)
    axes.set_xticks(months[::step])
    axes.set_xticklabels(months[::step], rotation=45, ha="right", fontsize=8)
    axes.set_ylabel("Units consumed")
    axes.set_title(
        f"{dataset['months']} months of demand · {dataset['series']} series",
        fontsize=12,
        fontweight="bold",
        loc="left",
    )
    _style(axes)
    return _save(figure, PIPELINE_CHART_FILES["dataset"], PIPELINE_DIR)


def chart_pattern_map(patterns: dict):
    """Sitúa cada serie en el cuadrante que decidio su patron.

    Entrada:
        patterns: resumen de la etapa de patrones, con un punto por serie y los
            umbrales aplicados.

    Salida:
        Ruta de la imagen generada.

    Funcionalidad:
        Los ejes son los dos que de verdad deciden: el intervalo medio entre
        consumos y la dispersion del tamano del evento. Son las dos cifras de la
        regla de Syntetos, Boylan y Croston, y con sus umbrales trazados el mapa
        se lee como lo que es —cuatro cuadrantes— en vez de como una nube.

        La version anterior dibujaba coeficiente de variacion contra fuerza
        estacional. Eran los ejes correctos para el catalogo anterior, donde las
        series se movian todos los meses y la pregunta era si ademas tenian
        ciclo. Sobre este catalogo no describian nada: ninguna serie se
        clasifica por esos umbrales, asi que el mapa mostraba dos lineas que no
        cortaban a nadie y todos los puntos del mismo color.

        El intervalo va en escala logaritmica porque va de moverse todos los
        meses a moverse una vez cada dos anos, y en escala lineal la mitad del
        catalogo se apila contra el eje.
    """
    colors = {
        "Intermitente": SECONDARY,
        "Irregular": WARNING,
        "Estable": SUCCESS,
        "Volatil": DANGER,
        "Estacional": PRIMARY,
        "Tendencia": "#7B4EA8",
        "Insuficiente": MUTED,
    }

    markers = {"Intermitente": "o", "Irregular": "^"}

    figure, axes = plt.subplots(figsize=(7.8, 5.0))
    thresholds = patterns["thresholds"]
    adi_cut = thresholds["adi_intermittent"]
    cv2_cut = thresholds["cv2_lumpy"]

    points = patterns["points"]
    for label in sorted({point["pattern"] for point in points}):
        subset = [point for point in points if point["pattern"] == label]
        axes.scatter(
            [max(point["adi"], 1.0) for point in subset],
            [point["cv_squared"] for point in subset],
            s=30,
            alpha=0.62,
            label=f"{PATTERN_LABELS.get(label, label)} ({len(subset)})",
            color=colors.get(label, MUTED),
            marker=markers.get(label, "o"),
            edgecolor=SURFACE,
            linewidth=0.4,
        )

    axes.set_xscale("log")
    axes.axvline(adi_cut, color=TEXT, linewidth=1.1, linestyle="--")
    axes.axhline(cv2_cut, color=TEXT, linewidth=1.1, linestyle="--")

    top = max((point["cv_squared"] for point in points), default=1.0)
    right = max((point["adi"] for point in points), default=2.0)
    axes.set_ylim(0, top * 1.18)
    axes.set_xlim(0.9, right * 1.15)

    corners = [
        (0.015, 0.03, "Smooth", "classical estimators", "left", "bottom"),
        (0.015, 0.99, "Erratic", "size unpredictable", "left", "top"),
        (0.985, 0.03, "Intermittent", "Croston", "right", "bottom"),
        (0.985, 0.99, "Lumpy", "Croston-SBA", "right", "top"),
    ]
    for x, y, name, method, ha, va in corners:
        axes.text(
            x,
            y,
            f"{name}\n{method}",
            transform=axes.transAxes,
            ha=ha,
            va=va,
            fontsize=8,
            color=MUTED,
            linespacing=1.4,
        )

    axes.text(
        adi_cut * 1.06,
        top * 0.62,
        f"ADI {adi_cut}",
        color=TEXT,
        fontsize=8,
        rotation=90,
        va="center",
        fontweight="600",
    )
    axes.text(
        right * 1.1,
        cv2_cut,
        f"CV² {cv2_cut} ",
        color=TEXT,
        fontsize=8,
        ha="right",
        va="bottom",
        fontweight="600",
    )

    axes.set_xlabel("Average demand interval — months between consumptions (log scale)")
    axes.set_ylabel("CV² of the event size")
    axes.set_title(
        "Why each series landed in its pattern", fontsize=12, fontweight="bold", loc="left"
    )
    axes.legend(
        frameon=False,
        fontsize=9,
        labelcolor=TEXT,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.16),
        ncol=len({point["pattern"] for point in points}) or 1,
    )
    _style(axes)
    figure.tight_layout()
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
    colors = {
        "COMPRAR": SUCCESS,
        "REVISAR": WARNING,
        "APLAZADO": DANGER,
        "ESCALAR": PRIMARY,
        "NO_COMPRAR": MUTED,
    }
    reasons = list(reversed(optimization["reasons"]))

    labels = [
        f"{_wrap(item['reason'], 46)}\n{DECISION_LABELS.get(item['decision'], item['decision'])}"
        for item in reasons
    ]
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
    axes.set_xlabel("Part-city combinations")
    axes.tick_params(axis="y", labelsize=8)
    _style(axes)
    _headline(figure, f"Where the {total} decisions come from")
    return _save(figure, PIPELINE_CHART_FILES["decisiones"], PIPELINE_DIR)


def chart_optimizer_saving(optimization: dict):
    """Resume lo que aporta elegir proveedor, por planta y por caso destacado.

    Entrada:
        optimization: resumen de la etapa de optimizacion, con el ahorro por
            caso.

    Salida:
        Ruta de la imagen generada.

    Funcionalidad:
        Es la lectura honesta de que aporta el optimizador. La referencia no es
        no comprar nada, sino haber elegido mal entre las ofertas que si podian
        surtir el caso, que es el error que el sistema evita.

        Dos paneles, porque la pregunta tiene dos alturas. El de la izquierda
        responde cuanto y donde: una barra por planta con lo comprometido frente
        a lo que habria costado la peor oferta aplicable. El de la derecha
        responde en que casos concretos se gano mas, que es lo unico del detalle
        por pieza que sirve para algo.

        La version anterior dibujaba una barra por compra. Con setenta y tres
        compras la figura media cinco mil doscientos pixeles de alto: habia que
        desplazarse por ella como por un listado, ninguna barra se podia comparar
        con otra porque nunca estaban en pantalla a la vez, y el total —lo unico
        que se queria saber— no aparecia por ningun lado. Un grafico que solo se
        puede leer una fila cada vez es una tabla mal impresa.
    """
    savings = optimization["savings"]
    figure, (left, right) = plt.subplots(
        1, 2, figsize=(11.2, 4.2), gridspec_kw={"width_ratios": [1, 1.25]}
    )

    if not savings:
        for axes in (left, right):
            axes.text(
                0.5,
                0.5,
                "No purchase had more than one applicable offer",
                ha="center",
                va="center",
                color=MUTED,
                transform=axes.transAxes,
            )
            axes.set_axis_off()
        figure.suptitle(
            "Supplier choice avoids nothing this run",
            fontsize=12, fontweight="bold", x=0.008, ha="left", color=TEXT,
        )
        return _save(figure, PIPELINE_CHART_FILES["ahorro"], PIPELINE_DIR)

    plants = {}
    for item in savings:
        plant = plants.setdefault(item["city_id"], {"chosen": 0.0, "worst": 0.0, "orders": 0})
        plant["chosen"] += item["chosen_cost_usd"]
        plant["worst"] += item["worst_cost_usd"]
        plant["orders"] += 1

    names = sorted(plants)
    spots = range(len(names))
    worst = [plants[name]["worst"] for name in names]
    chosen = [plants[name]["chosen"] for name in names]

    left.barh(list(spots), worst, color=LIGHT, height=0.5, label="Worst applicable offer")
    left.barh(list(spots), chosen, color=SECONDARY, height=0.5, label="What was committed")
    left.set_yticks(list(spots))
    left.set_yticklabels(
        [f"{name}\n{plants[name]['orders']} purchases" for name in names], fontsize=9
    )
    left.invert_yaxis()

    for spot, name in zip(spots, names, strict=False):
        gap = plants[name]["worst"] - plants[name]["chosen"]
        share = gap / plants[name]["worst"] if plants[name]["worst"] else 0.0
        left.text(
            plants[name]["worst"] * 1.02,
            spot,
            f"−{gap:,.0f} USD  ({share:.0%})",
            va="center",
            fontsize=9,
            color=SUCCESS,
            fontweight="700",
        )

    left.set_xlim(0, max(worst) * 1.42)
    left.set_xlabel("Total order cost (USD)")
    left.set_title("Where the saving is", fontsize=11, fontweight="bold", loc="left")
    left.legend(frameon=False, fontsize=8, labelcolor=TEXT, loc="lower right")
    _style(left)

    top = sorted(savings, key=lambda item: -item["saving_usd"])[:12]
    spots = range(len(top))
    right.barh(
        list(spots),
        [item["saving_usd"] for item in top],
        color=SUCCESS,
        height=0.6,
    )
    right.set_yticks(list(spots))
    right.set_yticklabels(
        [f"{item['sku_id']} · {item['city_id']}" for item in top], fontsize=8
    )
    right.invert_yaxis()

    for spot, item in zip(spots, top, strict=False):
        right.text(
            item["saving_usd"] * 1.02,
            spot,
            f"{item['saving_usd']:,.0f}",
            va="center",
            fontsize=8,
            color=TEXT,
            fontweight="600",
        )

    right.set_xlim(0, max(item["saving_usd"] for item in top) * 1.18)
    right.set_xlabel("Saved against the worst applicable offer (USD)")
    right.set_title(
        f"The 12 that saved most, of {len(savings)}", fontsize=11, fontweight="bold", loc="left"
    )
    _style(right)

    figure.suptitle(
        f"Supplier choice avoids {optimization['saving_usd']:,.0f} USD of overspend",
        fontsize=12,
        fontweight="bold",
        x=0.008,
        ha="left",
        color=TEXT,
    )
    figure.tight_layout(rect=(0, 0, 1, 0.93))
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
