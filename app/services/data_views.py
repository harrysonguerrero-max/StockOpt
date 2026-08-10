"""Lectura de las tablas del dataset para el explorador de datos.

Funcionalidad:
    Sirve el contenido de las tablas generadas por el pipeline junto con la
    descripcion de cada columna, de modo que la interfaz pueda mostrar el dato
    tal como esta en disco y explicar que significa cada campo.

    Solo se pueden leer las tablas catalogadas en el diccionario de datos. Esa
    lista blanca es lo que impide que el nombre de tabla que llega por la URL se
    use para leer cualquier archivo del disco.

    Las tablas se conservan en memoria una vez leidas, igual que hace la cola de
    recomendaciones, porque el pipeline es por lotes y el contenido no cambia
    mientras la aplicacion corre.
"""

import math

import pandas as pd

from app.core.dataset import OUT_DIR
from app.services.dictionary import describe_table, table_names

_cache = {}


def is_known_table(name: str) -> bool:
    """Indica si el nombre corresponde a una tabla catalogada.

    Entrada:
        name: nombre de archivo de la tabla, tal como llega de la interfaz.

    Salida:
        True si la tabla esta en el diccionario de datos.

    Funcionalidad:
        Es el control que aplica la lista blanca antes de tocar el disco.
    """
    return name in table_names()


def table_path(name: str):
    """Resuelve la ruta en disco de una tabla catalogada.

    Entrada:
        name: nombre de archivo de la tabla.

    Salida:
        Ruta dentro de la carpeta del dataset.

    Funcionalidad:
        Centraliza la resolucion para que ningun llamador componga rutas por su
        cuenta. El nombre ya viene validado contra el catalogo.
    """
    return OUT_DIR / name


def json_safe(value):
    """Convierte un valor de pandas en algo que pueda viajar como JSON.

    Entrada:
        value: celda leida del CSV.

    Salida:
        El mismo valor, o None cuando es nulo o no representable.

    Funcionalidad:
        Los nulos de pandas y los infinitos no tienen equivalente en JSON y
        romperian la serializacion de la respuesta con un error que no dice nada
        util. Se traducen a None para que la interfaz los pinte como celda vacia.

        Los tipos propios de numpy tampoco son serializables, asi que se
        devuelven como el tipo de Python equivalente.
    """
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return None
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def json_safe_record(record):
    """Aplica la conversion a JSON a todos los campos de un registro.

    Entrada:
        record: diccionario proveniente de un DataFrame, o None.

    Salida:
        El mismo diccionario con los valores ya serializables, o None si no
        habia registro.

    Funcionalidad:
        Cualquier respuesta armada a partir de una fila de pandas necesita este
        paso. Tenerlo aqui, junto a la lectura de tablas, evita que cada
        endpoint improvise su propia limpieza y descubra el problema en
        produccion, que es lo que pasa cuando una columna opcional viene vacia.
    """
    if record is None:
        return None
    return {key: json_safe(value) for key, value in record.items()}


def load_table(name: str, refresh: bool = False):
    """Carga una tabla del dataset desde disco.

    Entrada:
        name: nombre de archivo de la tabla, ya validado contra el catalogo.
        refresh: fuerza releer descartando lo cacheado.

    Salida:
        DataFrame con el contenido de la tabla.

    Funcionalidad:
        Mantiene el resultado en memoria entre peticiones y solo vuelve a disco
        cuando se pide expresamente, por ejemplo tras regenerar el dataset.
    """
    if refresh:
        _cache.pop(name, None)
    if name not in _cache:
        _cache[name] = pd.read_csv(table_path(name))
    return _cache[name]


def table_catalog() -> list:
    """Reune la lista de tablas disponibles con su descripcion.

    Entrada:
        Ninguna.

    Salida:
        Lista de diccionarios con el nombre, el titulo, la etapa del pipeline
        que la produce, el resumen, y cuantas filas y columnas tiene. Las tablas
        que aun no se han generado se marcan como no disponibles.

    Funcionalidad:
        Es la unica llamada que necesita el explorador para construir su indice.
        Contar las filas exige leer el archivo, pero las tablas del MVP son
        pequeñas y quedan cacheadas para la lectura posterior.
    """
    catalog = []
    for name in table_names():
        described = describe_table(name)
        available = table_path(name).exists()
        entry = {
            "name": name,
            "title": described["title"],
            "stage": described["stage"],
            "summary": described["summary"],
            "available": available,
            "row_count": 0,
            "column_count": len(described["columns"]),
        }
        if available:
            frame = load_table(name)
            entry["row_count"] = len(frame)
            entry["column_count"] = int(frame.shape[1])
        catalog.append(entry)
    return catalog


def read_table(name: str, refresh: bool = False) -> dict:
    """Devuelve el contenido completo de una tabla con su documentacion.

    Entrada:
        name: nombre de archivo de la tabla, ya validado contra el catalogo.
        refresh: fuerza releer desde disco.

    Salida:
        Diccionario con la descripcion de la tabla, la definicion de cada
        columna presente en el archivo y las filas como listas de valores.

    Funcionalidad:
        Las filas viajan como listas y no como diccionarios porque la tabla mas
        grande tiene casi tres mil filas y repetir el nombre de la columna en
        cada una multiplicaria el tamaño de la respuesta sin aportar nada.

        Las columnas se ordenan segun el archivo, no segun el catalogo, y las que
        no esten documentadas se sirven igual con su nombre a secas. Asi una
        columna nueva aparece en pantalla aunque nadie haya actualizado todavia
        el diccionario.
    """
    described = describe_table(name)
    frame = load_table(name, refresh=refresh)
    documented = {column["name"]: column for column in described["columns"]}

    columns = [
        documented.get(
            column,
            {
                "name": column,
                "type": "",
                "unit": "",
                "origin": "",
                "description": "",
            },
        )
        for column in frame.columns
    ]

    rows = [
        [json_safe(value) for value in record]
        for record in frame.itertuples(index=False, name=None)
    ]

    return {
        "name": name,
        "title": described["title"],
        "stage": described["stage"],
        "summary": described["summary"],
        "notes": described["notes"],
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
    }
