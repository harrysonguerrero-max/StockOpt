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

import math

import pandas as pd

MONTHS_PER_YEAR = 12

VALUE_CLASS_A_MAX = 0.80
VALUE_CLASS_B_MAX = 0.95

ROTATION_FAST_MIN = 0.25
ROTATION_SLOW_MIN = 0.08

VALUE_CLASSES = ["A", "B", "C"]
ROTATION_CLASSES = ["F", "S", "N"]
CRITICALITY_CLASSES = ["A", "B", "C"]

VALUE_LABELS = {
    "A": "A · top 80% of annual value",
    "B": "B · next 15%",
    "C": "C · last 5%",
}

ROTATION_LABELS = {
    "F": "F · fast, moves in 25%+ of months",
    "S": "S · slow, moves in 8–25% of months",
    "N": "N · non-moving, under 8% of months",
}

CRITICALITY_LABELS = {
    "A": "A · stops a production line",
    "B": "B · degrades output",
    "C": "C · tolerable until the next run",
}


def defined_number(value) -> float:
    """Convierte a nulo explicito cualquier numero que no exista.

    Entrada:
        value: numero que puede venir ausente o indefinido.

    Salida:
        El numero como flotante, o None si no esta definido.

    Funcionalidad:
        Hay razones que no existen. Las vueltas al año de una pieza sin
        existencias no valen cero ni valen infinito: no estan definidas, porque
        dividir el consumo entre un inventario vacio no responde a nada.

        El problema es que una columna de pandas con numeros no sabe guardar esa
        ausencia. Al mezclar None con flotantes convierte el None en NaN, que es
        un flotante mas, y el catalogo sale con dieciseis NaN camuflados entre
        las cifras. JSON no admite NaN —no esta en la norma— asi que la pantalla
        recibia un error del servidor en lugar del catalogo, y las graficas de
        criticidad, valor y rotacion aparecian vacias.

        Esta funcion devuelve la ausencia a su forma explicita justo antes de
        publicar, que es el unico punto donde vuelve a caber.
    """
    if value is None:
        return None
    number = float(value)
    return None if not math.isfinite(number) else number


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


def rotation_class(movement_share: float) -> str:
    """Asigna la clase FSN de rotacion segun la frecuencia de salida.

    Entrada:
        movement_share: fraccion de meses en que la pieza registra consumo.

    Salida:
        Etiqueta F para rapida, S para lenta y N para practicamente inmovil.

    Funcionalidad:
        FSN mide cada cuanto se mueve la pieza, no cuanto vale ni que pasa si
        falta. Es la dimension que gobierna el riesgo de obsolescencia y el ritmo
        al que conviene reponer: un item que se mueve casi todos los meses tolera
        lotes grandes, y uno que se mueve una vez al año no.
    """
    if movement_share >= ROTATION_FAST_MIN:
        return "F"
    if movement_share >= ROTATION_SLOW_MIN:
        return "S"
    return "N"


def classify_parts(
    parts: pd.DataFrame,
    forecast: pd.DataFrame,
    inventory: pd.DataFrame,
    patterns: pd.DataFrame = None,
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

        La clase FSN se mide en meses con movimiento y no en dias con salida. La
        version anterior usaba la proporcion de dias del mes en que la pieza se
        pide, que con consumo continuo separa bien y con refacciones no separa
        nada: en este catalogo vale entre 0,003 y 0,08 para todas, de modo que
        los umbrales clasicos dejaban las 876 piezas en clase N y la
        clasificacion no distinguia nada de nada.

        La fraccion de meses en que la pieza se mueve —el inverso del intervalo
        entre demandas— si separa: hay referencias que se mueven un mes de cada
        dos y otras uno de cada veinte, y esa diferencia es exactamente el riesgo
        de obsolescencia que FSN existe para detectar.
    """
    demand = (
        forecast.groupby("sku_id")
        .agg(
            monthly_demand=("forecast_q50", "sum"),
            issue_rate=("issue_rate", "mean"),
        )
        .reset_index()
    )

    if patterns is not None and "adi" in patterns:
        movement = (
            patterns.groupby("sku_id")["adi"]
            .mean()
            .rdiv(1.0)
            .clip(upper=1.0)
            .rename("movement_share")
            .reset_index()
        )
    else:
        movement = demand[["sku_id"]].assign(movement_share=demand["issue_rate"])
    stock = inventory.groupby("sku_id")["on_hand_qty"].sum().rename("on_hand_qty").reset_index()

    frame = (
        parts[["sku_id", "description", "category", "criticality", "unit_cost_usd"]]
        .merge(demand, on="sku_id", how="left")
        .merge(movement, on="sku_id", how="left")
        .merge(stock, on="sku_id", how="left")
        .fillna(
            {
                "monthly_demand": 0.0,
                "issue_rate": 0.0,
                "movement_share": 0.0,
                "on_hand_qty": 0,
            }
        )
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
    frame["rotation_class"] = [rotation_class(share) for share in frame["movement_share"]]
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
    parts: pd.DataFrame,
    forecast: pd.DataFrame,
    inventory: pd.DataFrame,
    patterns: pd.DataFrame = None,
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
    frame = classify_parts(parts, forecast, inventory, patterns)

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
                "movement_share": round(float(record["movement_share"]), 4),
                "rotation_class": record["rotation_class"],
                "turns_per_year": defined_number(record["turns_per_year"]),
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
