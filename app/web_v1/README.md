# Interfaz anterior (v1)

Copia congelada de `app/web/` tal como estaba el 2026-08-11, antes del rediseño
de la narrativa de pantalla.

**No se sirve.** `app/main.py` monta `/static` sobre `app/web/` únicamente; esta
carpeta queda inerte y existe solo como referencia para comparar.

## Qué era

Una página con dos pestañas hermanas:

- **Cola de compras** — franja de cinco cifras, seis filtros y una tabla de 40
  filas por 7 columnas pintada completa al cargar, con detalle desplegable por
  fila.
- **Modelo de demanda** — otras cinco cifras, un párrafo de veredicto y cinco
  gráficas PNG del entrenamiento.

## Por qué se reemplazó

El feedback fue que la pantalla no se cuenta sola: abre en el nivel más granular
que tiene, sin ningún nivel por encima, así que el comprador recibe la base de
datos entera y no sabe por dónde empezar. Además el grano de la decisión —una
por pieza y por ciudad— había que explicarlo con palabras porque nada en el
espacio lo indicaba.

Para volver a esta versión: copiar los tres archivos sobre `app/web/`.
