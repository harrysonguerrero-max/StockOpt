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

Los comandos, en este orden. Cada uno deja su salida en `app/data/mvp/`.

```bash
python -m app.services.profile_data           # 0. perfila y limpia las fuentes
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

**0. Perfilado y limpieza.** Analiza las fuentes crudas (tipos, nulos,
duplicados, rangos, atípicos) y aplica las reglas de limpieza. Publica el
informe en `app/data/mvp/quality/`. Es opcional para el pipeline —la limpieza ya
va incrustada en la carga— pero es el paso que deja evidencia de qué se hizo con
los datos.

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

Tres vistas. La pantalla abre arriba y se baja al detalle, en lugar de empezar
por la tabla completa.

**El turno.** Una frase resume el día —cuántas decisiones hay abiertas, cuánto
suman y cuántas el sistema no pudo resolver— con las cifras dentro del texto:
cada una filtra al pulsarla. Debajo, dos columnas, una por planta. Que la
decisión sea por pieza y por ciudad no hace falta escribirlo: es la estructura
de la página.

Dentro de cada planta, tres bandas ordenadas por quién debe actuar: *el sistema
no puede decidir esto*, *listo para aprobar* y *sin acción*, esta última plegada.
Cada caso es una tarjeta que se lee sola: qué pieza, cómo está el stock —con el
medidor de existencias frente al mínimo—, qué hay que hacer, por qué, y a quién
comprarle.

**El caso.** Al abrir una tarjeta, un panel cuenta la decisión en el orden en
que se forma:

1. *Qué consume* — la serie mensual real, con los meses simulados en trazo
   discontinuo para no presentarlos como observación.
2. *Qué va a consumir* — la proyección con su rango probable, el patrón y la
   confianza.
3. *Cuánto necesita en bodega* — el medidor, y de dónde sale el mínimo.
4. *A quién comprarle* — los proveedores que compitieron, con lo que gana el
   elegido.

Los casos marcados `REVISAR` no reciben plantilla de recomendación sino de
pregunta: las dos salidas enfrentadas con su costo, porque ahí el sistema no
decide.

El flujo `Pendiente → Aprobado → Contactado proveedor → Orden confirmada` se
dibuja como secuencia, con el botón de la acción siguiente pegado a la barra.
El rechazo sale desde cualquier punto previo. Las transiciones se validan en el
servidor, cada cambio queda auditado, y las aprobaciones viven en SQLite y
sobreviven a regenerar el dataset.

La justificación redactada por el modelo de lenguaje queda plegada al final y
solo se pide al abrirla, para una fila. Si falla o tarda, se queda la versión
determinista.

**Todas las piezas.** La tabla leída: nueve columnas con el dato traducido a lo
que significa —el medidor en vez de tres números, la confianza en tramos, el
estado en la palabra que usa una persona—, cualquiera de ellas ordenable y con
la cabecera fija al desplazar. El pie recalcula con el filtro puesto, que es lo
que la convierte en una consulta: al dejar solo criticidad A responde cuántas
compras son y cuánto cuestan.

**Datos en crudo.** Las mismas cuarenta filas con los treinta y siete campos del
registro, tal como salen del pipeline: la cabecera es el nombre del campo y la
celda es su valor, sin traducir ni redondear. `NO_COMPRAR` se lee `NO_COMPRAR`,
la confianza es `0.49` y el plazo `14.5`. Los nulos aparecen como `·` para
distinguirlos de un cero.

Las dos existen a propósito. El turno y la tabla leída interpretan el dato
—eligen qué enseñar, en qué unidad y con qué palabra—, y precisamente por eso
hace falta un sitio donde comprobar contra qué se hizo esa interpretación. Al
crudo solo se le añade lo mecánico: cabecera fija, columna de la pieza fija al
desplazar a lo ancho, ordenar por cualquier campo —con los nulos siempre al
final, en los dos sentidos— y los filtros. El código de pieza abre el caso; el
resto de la fila se deja seleccionar y copiar.

Cada tabla mantiene sus propios filtros: acotar el crudo para inspeccionar un
caso no deja la otra pantalla acotada al volver. Y cada una descarga el recorte
que tiene en pantalla, con sus columnas, a diferencia del enlace de la barra
superior, que baja las cuarenta con las que elige el servidor.

**Modelo.** Las dos gráficas que responden si el modelo aporta algo; el resto
del diagnóstico, detrás de un plegable. Se llega desde el paso 2 de un caso.

> La versión anterior de la interfaz queda congelada en [`app/web_v1/`](app/web_v1/),
> sin servir, para poder comparar.

---

## API

| Endpoint | Qué devuelve |
|---|---|
| `GET /api/v1/health` | Estado del servicio y si el dataset está listo |
| `GET /api/v1/recommendations` | Cola completa con resumen y filtros |
| `POST /api/v1/recommendations/state` | Aplica una decisión del comprador |
| `GET /api/v1/recommendations/{sku}/{ciudad}/explanation` | Justificación de **una** fila, redactada por el LLM |
| `GET /api/v1/recommendations/{sku}/{ciudad}/history` | Serie de consumo marcada por origen, proyección y política |
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

151 pruebas en `tests/core/`. Cubren integridad del dataset, calibración del
clasificador, política de inventario, restricciones del optimizador, flujo de
aprobación y endpoints.

---

## Advertencias antes de una demo

- **El dataset es sintético en campos críticos.** Vida útil, existencias,
  cantidad mínima de orden, capacidad y flete los genera el build con semilla
  fija; no provienen de ningún sistema real.
- **No hay autenticación.** El usuario que aprueba es texto libre.
- **El modelo apenas supera al promedio móvil** (3,2 %). Con series cortas y
  mayormente planas es un resultado esperable, y está a la vista en la interfaz.
- **Parte del histórico es simulado.** Los meses anteriores a 2023-02 se generan
  para dar profundidad al entrenamiento y llevan `is_synthetic = 1`.

El detalle completo de lo que falta, las mejoras posibles y los puntos ciegos
está en [`Spec.md`](Spec.md), sección 11.
