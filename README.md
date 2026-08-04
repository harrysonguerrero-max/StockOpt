# StockOpt

Recomienda qué refacciones comprar, cuántas y a qué proveedor, para las plantas
de Nava (Coahuila) y Ciudad Obregón (Sonora). Proyecta la demanda con un modelo
de machine learning, resuelve la compra óptima con programación entera y entrega
cada decisión con su justificación para que un comprador la apruebe o la
rechace.

---

## Arquitectura

Tres capas con dependencias en una sola dirección: `api → services → core`.

| Capa | Responsabilidad | Regla |
|---|---|---|
| **`app/core/`** | Dominio puro: política de inventario, clasificación de patrones, proyección, optimización y modelo ML | No importa nada de `services` ni de `api`, ni toca disco |
| **`app/services/`** | Casos de uso y adaptadores externos: SQLite, Gemini, MLflow, lectura y escritura de archivos, y los scripts ejecutables | Orquesta `core`; una responsabilidad por módulo |
| **`app/api/`** | Único puerto de entrada HTTP: valida con DTOs y formatea respuestas | No contiene lógica de negocio |
| **`app/data/`** | Solo datos: CSV crudos y generados | Sin código |
| **`app/web/`** | Interfaz estática que sirve la propia aplicación | — |
| **`artifacts/`** | Salidas del entrenamiento: modelo, métricas y gráficas | — |

Los parámetros viven al inicio del módulo que los usa, no en archivos de
configuración aparte. Cuando otro módulo los necesita, los importa de ahí.

---

## Instalación

```bash
python -m venv .venv
.venv/Scripts/activate          # Linux/macOS: source .venv/bin/activate
pip install -e .
```

El SDK de observabilidad se instala aparte, desde el GitLab interno:

```bash
pip install "git+https://<usuario>:<token>@gitlab.digitalcoedevops.com/harryson.guerrero/mlops-sdk.git@v0.5.0"
```

Copia `.env.example` a `.env` y completa lo que tengas. Todo es opcional: sin
`GEMINI_API_KEY` las justificaciones usan plantillas, y sin
`MLFLOW_TRACKING_URI` los entrenamientos se guardan en `artifacts/`.

---

## Ejecución

Cinco comandos, en este orden. Cada uno deja su salida en `app/data/mvp/`.

```bash
python -m app.services.build_dataset          # 1. dataset relacional validado
python -m app.services.build_patterns         # 2. patrón de demanda por serie
python -m app.services.train_model            # 3. modelo ML + métricas + gráficas
python -m app.services.build_forecast         # 4. proyección e inventario mínimo
python -m app.services.build_recommendations  # 5. decisiones de compra
```

Después, la interfaz:

```bash
python -m uvicorn app.main:app --port 8000
```

Abre `http://localhost:8000`. Para ver el dataset por consola sin levantar nada:

```bash
python -m app.services.show_dataset
```

Los pasos 1 y 2 son requisito del 3; el 4 usa el modelo si existe y si no cae a
métodos estadísticos. Todos son idempotentes.

---

## Qué hace cada paso

**1. Dataset.** Lee los CSV crudos de `app/data/` (no los modifica) y construye
las cuatro entradas del proyecto: maestro de piezas, inventario, demanda mensual
y proveedores con su catálogo. Valida integridad referencial, rangos, nulos y
duplicados antes de escribir.

**2. Patrones.** Clasifica cada serie de pieza y ciudad en estacional, con
tendencia, estable o volátil, y le asigna un método de proyección y un nivel de
confianza.

**3. Entrenamiento.** Ajusta un modelo global sobre las 40 series con rezagos y
medias móviles. Valida sobre los últimos 6 meses y compara contra dos
referencias. Publica métricas y cinco gráficas en `artifacts/training/`.

**4. Proyección.** Combina el modelo con la proyección estadística y calcula el
inventario mínimo de cada pieza: demanda durante el plazo de entrega más un
colchón que absorbe la variabilidad de la demanda y la del propio plazo.

**5. Recomendaciones.** Resuelve un modelo entero mixto por pieza y ciudad que
minimiza precio más flete, respetando el mínimo de orden del proveedor, su
capacidad, el inventario máximo y la vida útil. Devuelve `COMPRAR`,
`NO_COMPRAR` o `REVISAR`, siempre con el motivo.

---

## La interfaz

**Cola de compras.** Una fila por pieza y ciudad, ordenadas poniendo delante lo
que exige acción. Cada fila lleva un medidor que muestra las existencias frente
al mínimo. Al abrirla aparecen la justificación, los supuestos aplicados, el
contacto del proveedor y los botones de decisión.

El flujo de aprobación es `Pendiente → Aprobado → Contactado proveedor → Orden
confirmada`, con rechazo desde cualquier punto previo. Las transiciones se
validan en el servidor y cada cambio queda auditado. Las aprobaciones viven en
SQLite y sobreviven a regenerar el dataset.

**Modelo de demanda.** Métricas de validación y las gráficas del entrenamiento.

---

## API

| Endpoint | Qué devuelve |
|---|---|
| `GET /api/v1/health` | Estado del servicio y si el dataset está listo |
| `GET /api/v1/recommendations` | Cola completa con resumen y filtros |
| `POST /api/v1/recommendations/state` | Aplica una decisión del comprador |
| `GET /api/v1/recommendations/audit` | Historial de decisiones |
| `GET /api/v1/recommendations/export` | Descarga la cola en CSV |
| `GET /api/v1/training/metrics` | Métricas del último entrenamiento |
| `GET /api/v1/training/charts/{nombre}` | Gráfica del entrenamiento |

Documentación interactiva en `/api/v1/docs`.

---

## Pruebas

```bash
python -m pytest tests/ -q
```

116 pruebas en `tests/core/`. Cubren integridad del dataset, calibración del
clasificador, política de inventario, restricciones del optimizador, flujo de
aprobación y endpoints.

---

## Advertencias antes de una demo

- **El dataset es sintético en campos críticos.** Vida útil, existencias,
  cantidad mínima de orden, capacidad y flete los genera el build con semilla
  fija; no provienen de ningún sistema real.
- **No hay autenticación.** El usuario que aprueba es texto libre.
- **El modelo apenas supera al promedio móvil** (0,8 %). Con series cortas y
  mayormente planas es un resultado esperable, y está a la vista en la interfaz.

El detalle completo de lo que falta, las mejoras posibles y los puntos ciegos
está en [`Spec.md`](Spec.md), sección 11.
