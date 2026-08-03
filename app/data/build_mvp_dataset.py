"""Punto de entrada para construir el dataset MVP.

Funcionalidad:
    Ejecuta el build completo y reporta por consola las tablas generadas y las
    advertencias de validacion. Los CSV crudos nunca se modifican.

    Uso: python -m app.data.build_mvp_dataset
"""

from app.core import dataset_config as config
from app.services.dataset_builder import FILE_NAMES, build_all, publish


def main() -> None:
    """Construye, valida y publica el dataset MVP.

    Entrada:
        Ninguna.

    Salida:
        Ninguna. Escribe los CSV en la carpeta de salida e imprime el resumen.

    Funcionalidad:
        Delega la construccion y la publicacion en la capa de servicios y se
        limita a presentar el resultado al operador.
    """
    tables = build_all()
    warnings = publish(tables)

    print(f"Dataset MVP generado en {config.OUT_DIR}")
    for key, filename in FILE_NAMES.items():
        print(f"  {filename:<24} {len(tables[key]):>5} filas")
    print("  data_dictionary.md")

    print("\nValidacion: sin errores criticos.")
    if warnings:
        print("Advertencias (no bloquean, requieren revision):")
        for warning in warnings:
            print(f"  - {warning}")


if __name__ == "__main__":
    main()
