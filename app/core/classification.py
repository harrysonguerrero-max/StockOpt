"""Clasificacion del catalogo por criticidad, valor y rotacion.

Funcionalidad:
    Situa cada pieza en las tres dimensiones con que la literatura de gestion de
    repuestos decide donde poner el dinero, y las cruza entre si.

    Criticidad viene del maestro y responde a que pasa si la pieza falta. Valor
    es una clasificacion ABC de Pareto sobre el consumo anual proyectado y
    responde a cuanto capital mueve. Rotacion es una clasificacion FSN sobre la
    frecuencia con que la pieza sale de bodega y responde a cada cuanto se mueve,
    que es lo que define el riesgo de obsolescencia.

    Ninguna de las tres basta por si sola, y ese es justo el motivo de cruzarlas.
    Una pieza que rota poco y vale poco es candidata a no reponer segun ABC y
    segun FSN; si ademas es de criticidad A, para una linea cuando falta y la
    conclusion correcta es la contraria. Esa celda solo aparece al cruzar.

    El modulo no decide nada: describe el catalogo. Lo que decide es el
    optimizador, y esta clasificacion es el contexto con que se lee su salida.
"""

import pandas as pd

MONTHS_PER_YEAR = 12

VALUE_CLASS_A_MAX = 0.80
VALUE_CLASS_B_MAX = 0.95

ROTATION_FAST_MIN = 0.50
ROTATION_SLOW_MIN = 0.15

VALUE_CLASSES = ["A", "B", "C"]
ROTATION_CLASSES = ["F", "S", "N"]
CRITICALITY_CLASSES = ["A", "B", "C"]

VALUE_LABELS = {
    "A": "A · top 80% of annual value",
    "B": "B · next 15%",
    "C": "C · last 5%",
}

ROTATION_LABELS = {
    "F": "F · fast, issued on 50%+ of days",
    "S": "S · slow, 15–50% of days",
    "N": "N · non-moving, under 15%",
}

CRITICALITY_LABELS = {
    "A": "A · stops a production line",
    "B": "B · degrades output",
    "C": "C · tolerable until the next run",
}


def value_class(cumulative_share: float) -> str:
    """Asigna la clase ABC de valor segun la participacion acumulada.

    Entrada:
        cumulative_share: fraccion acumulada del valor anual del catalogo hasta
            esta pieza, ordenando de mayor a menor.

    Salida:
        Etiqueta A, B o C.

    Funcionalidad:
        Es el corte de Pareto habitual: el 80 % del valor suele concentrarse en
        una minoria de referencias, y separar esa minoria es lo que permite
        gastar el esfuerzo de control donde esta el dinero.
    """
    if cumulative_share <= VALUE_CLASS_A_MAX:
        return "A"
    if cumulative_share <= VALUE_CLASS_B_MAX:
        return "B"
    return "C"


def rotation_class(issue_rate: float) -> str:
    """Asigna la clase FSN de rotacion segun la frecuencia de salida.

    Entrada:
        issue_rate: proporcion de dias del mes en que la pieza registra consumo.

    Salida:
        Etiqueta F para rapida, S para lenta y N para practicamente inmovil.

    Funcionalidad:
        FSN mide cada cuanto se mueve la pieza, no cuanto vale ni que pasa si
        falta. Es la dimension que gobierna el riesgo de obsolescencia y el ritmo
        al que conviene reponer: un item que sale todos los dias tolera lotes
        grandes, y uno que sale una vez al trimestre no.
    """
    if issue_rate >= ROTATION_FAST_MIN:
        return "F"
    if issue_rate >= ROTATION_SLOW_MIN:
        return "S"
    return "N"


def classify_parts(
    parts: pd.DataFrame, forecast: pd.DataFrame, inventory: pd.DataFrame
) -> pd.DataFrame:
    """Clasifica cada pieza del catalogo en las tres dimensiones.

    Entrada:
        parts: maestro de piezas con criticidad y valor unitario.
        forecast: proyeccion por pieza y ciudad, con la tasa de salida.
        inventory: existencias actuales por pieza y ciudad.

    Salida:
        DataFrame con una fila por pieza y las tres etiquetas, mas las cifras
        con que se calcularon.

    Funcionalidad:
        Agrega las dos plantas antes de clasificar. Una misma refaccion puede
        consumirse a ritmos distintos en Nava y en Obregon, pero la decision de
        que politica de control merece se toma sobre la pieza, no sobre la
        combinacion: es la misma referencia en el mismo catalogo.

        La rotacion en vueltas al año se calcula contra las existencias actuales
        y no contra un inventario medio historico, que no se tiene. Es una
        aproximacion declarada: sirve para ordenar el catalogo, no para auditar
        capital inmovilizado.
    """
    demand = (
        forecast.groupby("sku_id")
        .agg(
            monthly_demand=("forecast_q50", "sum"),
            issue_rate=("issue_rate", "mean"),
        )
        .reset_index()
    )
    stock = inventory.groupby("sku_id")["on_hand_qty"].sum().rename("on_hand_qty").reset_index()

    frame = (
        parts[["sku_id", "description", "category", "criticality", "unit_cost_usd"]]
        .merge(demand, on="sku_id", how="left")
        .merge(stock, on="sku_id", how="left")
        .fillna({"monthly_demand": 0.0, "issue_rate": 0.0, "on_hand_qty": 0})
    )

    frame["annual_units"] = (frame["monthly_demand"] * MONTHS_PER_YEAR).round(1)
    frame["annual_value_usd"] = (frame["annual_units"] * frame["unit_cost_usd"]).round(2)
    frame["stock_value_usd"] = (frame["on_hand_qty"] * frame["unit_cost_usd"]).round(2)
    frame["turns_per_year"] = [
        round(units / stock, 1) if stock > 0 else None
        for units, stock in zip(frame["annual_units"], frame["on_hand_qty"], strict=False)
    ]

    frame = frame.sort_values("annual_value_usd", ascending=False).reset_index(drop=True)
    total = float(frame["annual_value_usd"].sum())

    frame["value_share"] = (frame["annual_value_usd"] / total).round(4) if total else 0.0
    frame["value_cum_share"] = frame["value_share"].cumsum().round(4)
    frame["value_class"] = [value_class(share) for share in frame["value_cum_share"]]
    frame["rotation_class"] = [rotation_class(rate) for rate in frame["issue_rate"]]
    frame["issue_rate"] = frame["issue_rate"].round(4)
    return frame


def cross_matrix(frame: pd.DataFrame, rows: str, columns: str, row_order, column_order) -> list:
    """Cruza dos clasificaciones y cuenta las piezas de cada celda.

    Entrada:
        frame: catalogo ya clasificado.
        rows: columna que va en las filas de la matriz.
        columns: columna que va en las columnas.
        row_order: orden en que deben aparecer las filas.
        column_order: orden en que deben aparecer las columnas.

    Salida:
        Lista de filas, cada una con su etiqueta, el conteo por celda, las piezas
        que caen en ella y el total de la fila.

    Funcionalidad:
        Devuelve las piezas de cada celda y no solo el conteo. Una matriz de
        conteos dice que hay dos piezas en la celda que importa; devolver cuales
        son es lo que permite que la pantalla las nombre, que es donde el cruce
        deja de ser un ejercicio y se vuelve un hallazgo.

        El orden se impone desde fuera para que una clase sin piezas siga
        apareciendo como celda vacia. Si la matriz se encogiera al tamaño de lo
        que hay, dos corridas distintas tendrian formas distintas y no se
        podrian comparar.
    """
    matrix = []
    for row in row_order:
        block = frame[frame[rows] == row]
        cells = []
        for column in column_order:
            members = block[block[columns] == column]
            cells.append(
                {
                    "column": column,
                    "count": len(members),
                    "parts": [
                        {"sku_id": record["sku_id"], "description": record["description"]}
                        for record in members.to_dict(orient="records")
                    ],
                    "annual_value_usd": round(float(members["annual_value_usd"].sum()), 2),
                }
            )
        matrix.append({"row": row, "cells": cells, "total": len(block)})
    return matrix


def class_profile(frame: pd.DataFrame, column: str, order: list, labels: dict) -> list:
    """Resume cuanta variedad y cuanto valor concentra cada clase.

    Entrada:
        frame: catalogo ya clasificado.
        column: columna de clase que se resume.
        order: orden en que deben aparecer las clases.
        labels: texto explicativo de cada clase.

    Salida:
        Lista de diccionarios con el conteo, la participacion en variedad, la
        participacion en valor y la razon entre ambas.

    Funcionalidad:
        La razon entre participacion en valor y participacion en variedad es la
        cifra que hace legible un ABC: un 1,7 significa que esa clase concentra
        casi el doble de valor del que le corresponderia por numero de
        referencias, y es lo que justifica tratarla distinto.
    """
    total_parts = len(frame)
    total_value = float(frame["annual_value_usd"].sum())

    profile = []
    for name in order:
        block = frame[frame[column] == name]
        variety = len(block) / total_parts if total_parts else 0.0
        value = float(block["annual_value_usd"].sum()) / total_value if total_value else 0.0
        profile.append(
            {
                "class": name,
                "label": labels.get(name, name),
                "count": len(block),
                "variety_share": round(variety, 4),
                "value_share": round(value, 4),
                "concentration": round(value / variety, 2) if variety else None,
                "annual_value_usd": round(float(block["annual_value_usd"].sum()), 2),
            }
        )
    return profile


def build_classification(
    parts: pd.DataFrame, forecast: pd.DataFrame, inventory: pd.DataFrame
) -> dict:
    """Compone el analisis completo del catalogo en las tres dimensiones.

    Entrada:
        parts: maestro de piezas.
        forecast: proyeccion por pieza y ciudad.
        inventory: existencias actuales por pieza y ciudad.

    Salida:
        Diccionario con el catalogo clasificado, el perfil de cada dimension,
        los dos cruces y los umbrales aplicados.

    Funcionalidad:
        Es todo lo que la pantalla necesita en una sola llamada. Devolver los
        umbrales junto a los resultados es lo que hace auditable la
        clasificacion: se puede ver que pieza quedo al borde de un corte y por
        cuanto.
    """
    frame = classify_parts(parts, forecast, inventory)

    return {
        "parts": [
            {
                "sku_id": record["sku_id"],
                "description": record["description"],
                "category": record["category"],
                "criticality": record["criticality"],
                "unit_cost_usd": round(float(record["unit_cost_usd"]), 2),
                "annual_units": record["annual_units"],
                "annual_value_usd": record["annual_value_usd"],
                "value_share": record["value_share"],
                "value_cum_share": record["value_cum_share"],
                "value_class": record["value_class"],
                "issue_rate": record["issue_rate"],
                "rotation_class": record["rotation_class"],
                "turns_per_year": record["turns_per_year"],
                "on_hand_qty": int(record["on_hand_qty"]),
                "stock_value_usd": record["stock_value_usd"],
            }
            for record in frame.to_dict(orient="records")
        ],
        "profiles": {
            "criticality": class_profile(
                frame, "criticality", CRITICALITY_CLASSES, CRITICALITY_LABELS
            ),
            "value": class_profile(frame, "value_class", VALUE_CLASSES, VALUE_LABELS),
            "rotation": class_profile(frame, "rotation_class", ROTATION_CLASSES, ROTATION_LABELS),
        },
        "matrices": {
            "value_by_criticality": cross_matrix(
                frame, "value_class", "criticality", VALUE_CLASSES, CRITICALITY_CLASSES
            ),
            "rotation_by_criticality": cross_matrix(
                frame, "rotation_class", "criticality", ROTATION_CLASSES, CRITICALITY_CLASSES
            ),
        },
        "totals": {
            "parts": len(frame),
            "annual_value_usd": round(float(frame["annual_value_usd"].sum()), 2),
            "stock_value_usd": round(float(frame["stock_value_usd"].sum()), 2),
            "annual_units": round(float(frame["annual_units"].sum()), 1),
        },
        "thresholds": {
            "value_class_a_max": VALUE_CLASS_A_MAX,
            "value_class_b_max": VALUE_CLASS_B_MAX,
            "rotation_fast_min": ROTATION_FAST_MIN,
            "rotation_slow_min": ROTATION_SLOW_MIN,
        },
    }
