"""Tests de las convenciones de escritura del codigo.

Funcionalidad:
    El proyecto explica el codigo en docstrings y no en comentarios sueltos. Un
    comentario se pierde al refactorizar y no se lee desde fuera; un docstring
    viaja con la funcion y aparece en la ayuda. Estos tests hacen que la regla no
    dependa de acordarse en cada revision.
"""

import ast
import io
import tokenize
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[2] / "app"

SOURCES = sorted(APP_DIR.rglob("*.py"))


def python_files():
    """Enumera los modulos de la aplicacion.

    Entrada:
        Ninguna.

    Salida:
        Lista de rutas relativas a la raiz del proyecto, como texto.

    Funcionalidad:
        Da nombres legibles a los casos de prueba parametrizados, para que un
        fallo diga que archivo revisar sin tener que leer la ruta completa.
    """
    return [str(path.relative_to(APP_DIR.parent)) for path in SOURCES]


@pytest.mark.parametrize("path", SOURCES, ids=python_files())
def test_no_hay_comentarios_de_almohadilla(path):
    source = path.read_text(encoding="utf-8")
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    comments = [
        (token.start[0], token.string.strip())
        for token in tokens if token.type == tokenize.COMMENT
    ]

    assert not comments, (
        f"{path.name} tiene comentarios; la explicacion va en el docstring: "
        f"{comments}"
    )


@pytest.mark.parametrize("path", SOURCES, ids=python_files())
def test_todo_modulo_funcion_y_clase_lleva_docstring(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    missing = []

    if ast.get_docstring(tree) is None and path.name != "__init__.py":
        missing.append(f"modulo {path.name}")

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if node.name.startswith("__"):
            continue
        if ast.get_docstring(node) is None:
            missing.append(f"{node.name} (linea {node.lineno})")

    assert not missing, f"{path.name} sin docstring en: {missing}"
