# Spec — MVP de optimización de inventario con IA

---

## 0. Estado actual de la implementación

**Última actualización:** 2026-08-03

### Qué está hecho

**Etapas 1, 1.1 (Ingesta y validación) y 1.3 (Clasificación de patrones): COMPLETADAS.**

Existe un dataset relacional y validado que materializa las 4 entradas de datos del
proyecto. Se construye con `python -m app.data.build_mvp_dataset`, que lee los CSV
crudos de `app/data/` (**no los modifica**) y escribe las tablas en `app/data/mvp/`.

| Archivo generado | Filas | Entrada del proyecto |
|---|---|---|
| `parts_master.csv` | 20 | Maestro de piezas: SKU, categoría, criticidad, vida útil |
| `inventory_current.csv` | 60 | Inventario actual por ciudad/bodega |
| `demand_history.csv` | 2.220 | Demanda histórica mensual + señal operativa |
| `suppliers.csv` | 5 | Proveedores: ciudad, lead time (avg/min/max/std) |
| `supplier_offers.csv` | 51 | Proveedores: precio, MOQ, capacidad, flete por pieza |
| `cities.csv` | 3 | Catálogo de ciudades y bodegas |
| `demand_patterns.csv` | 60 | Patrón, confianza y modelo recomendado por serie (Etapa 1.3) |
| `data_dictionary.md` | — | Origen de cada columna (dato real vs. sintético) |

**Llaves:** `sku_id`, `city_id`, `supplier_id`. El join de las 6 tablas produce
153 filas sin nulos ni huérfanos. `supplier_offers` es la tabla puente
muchos-a-muchos que le da al optimizador alternativas de proveedor por pieza.

**Código:**
- `app/dataprep/` (`config`, `builders`, `validate`, `dictionary`) + entrypoint
  `app/data/build_mvp_dataset.py`. Build idempotente, semilla `SEED = 20260803`.
- `app/forecasting/` (`config`, `patterns`) + entrypoint `app/data/build_patterns.py`.

**47 tests** en `tests/dataprep/` y `tests/forecasting/`.

### Origen de los datos

- **Real:** criticidad, familia, costo unitario, descripción, consumo diario y
  fallas de máquina provienen de `synthetic_industrial_machine_data.csv`.
  Los lead times se calculan de `Delivery_Date − Order_Date` en
  `Procurement KPI Analysis Dataset.csv`.
- **Sintético (semilla fija):** vida útil, stock actual, punto de reorden, MOQ,
  capacidad y flete. No existían en ninguna fuente.
- **Fuera de alcance:** `parts.csv`, `manufacturers.csv`, `locations.csv`,
  `reorder_options.csv` (dominio de componentes electrónicos) y `ai4i2020.csv`
  (sensores). Se verificó que **no comparten ninguna llave** con el dataset MVP
  (`SKU-00048` vs `MRO-10045`; `WH-Central` vs `PUN-01`). Unirlos habría producido
  relaciones sin sentido operativo. `inventory-levels.csv` no aportó datos pero sí
  el esquema de columnas de `inventory_current.csv`.

### Qué sigue

**Siguiente paso: Etapa 2 — Proyección de demanda.**
`demand_patterns.csv` ya dice qué modelo usar en cada una de las 60 series.
Ver §11 para el orden completo y los bloqueantes detectados.

**Resultado de la clasificación (Etapa 1.3):**

| Patrón | Series | Modelo a usar en la Etapa 2 |
|---|---|---|
| Estable | 32 (53 %) | media móvil |
| Volátil | 16 (27 %) | mediana móvil + percentiles |
| Estacional | 11 (18 %) | Prophet |
| Tendencia | 1 (2 %) | regresión lineal |
| Insuficiente | 0 | — |

Confianza media 0,80 (rango 0,57–0,90). Ninguna serie quedó sin clasificar.

### Bloqueante conocido antes de la Etapa 3

La regla *"no seleccionar proveedores que no operen para la ciudad requerida"*
(Etapa 4) **no es satisfacible con el modelo de datos actual**: cada proveedor
tiene una sola `city_id` y 15 de las 60 combinaciones pieza-ciudad quedarían sin
ningún proveedor válido, haciendo el MILP infactible. Debe resolverse **antes**
de implementar la Etapa 3. Ver §11.2.

---

## 1. Problema
Se requiere una solución que recomiende decisiones de abastecimiento para piezas o repuestos, calculando inventario mínimo, inventario máximo, cantidad sugerida de compra, cantidad máxima permitida y proveedor recomendado. La recomendación debe considerar demanda futura, ciudad, precio, lead time y vida útil de la pieza, evitando tanto quiebres de inventario como sobrecompra y obsolescencia [web:27][web:31][web:41].

## 2. Objetivo del MVP
Construir un MVP que demuestre, de punta a punta, cómo una proyección de demanda se transforma en una recomendación de compra explicable para negocio. El MVP debe validar la lógica principal sin intentar cubrir toda la complejidad operativa de un sistema productivo enterprise [web:27][web:31].

## 3. Alcance funcional
El MVP debe permitir:
- Cargar datos de inventario, consumo histórico y proveedores.
- Proyectar demanda futura por pieza.
- Calcular inventario mínimo y máximo.
- Recomendar cantidad de compra.
- Seleccionar proveedor según costo y restricciones.
- Validar si la vida útil permite o no realizar la compra.
- Mostrar una explicación en lenguaje natural de la recomendación final [web:14][web:27][web:41][web:64].

## 4. Etapas de la solución

### Etapa 1. Ingesta y preparación de datos — ✅ COMPLETADA
Se consolidan los datos necesarios para la recomendación: inventario actual, historial de consumo, catálogo de piezas, proveedores, ciudades, precios, lead time y vida útil. En el MVP estos datos pueden provenir de archivos CSV o tablas simples para reducir complejidad inicial.

**Tecnologías posibles**
- Python
- Pandas
- CSV / SQLite / Postgres

**Implementación realizada**
- Paquete `app/dataprep/`: `config.py` (constantes y semilla), `builders.py`
  (un constructor por tabla, funciones puras), `validate.py`, `dictionary.py`.
- Entrypoint `app/data/build_mvp_dataset.py` (`python -m app.data.build_mvp_dataset`).
- Persistencia: **CSV** en `app/data/mvp/`. SQLite/Postgres se pospone hasta que
  haya escritura desde la UI (Etapa 1.2 y 6); mientras el flujo sea de sólo
  lectura, CSV es suficiente y mantiene el dataset versionable y diffeable.
- Decisiones tomadas: **3 ciudades** (Pune, Chennai, Dharuhera), montos en **USD**
  (1 USD = 83 INR), demanda a grano **mensual**.

#### 1.1 Validación explícita de datos — ✅ COMPLETADA
Antes de procesar los datos, el sistema debe validar:
- **Tipos de datos**: Verificar que cada campo cumple con su tipo esperado (numérico, texto, fecha, booleano).
- **Rangos y límites**: Validar que valores numéricos estén dentro de rangos operativos (ej: lead time > 0, cantidad > 0, precio ≥ 0).
- **Formatos**: Confirmar que fechas, códigos de ciudad y códigos de pieza cumplen formatos esperados.
- **Integridad referencial**: Asegurar que proveedores, ciudades y piezas referenciadas existen en los catálogos.
- **Datos faltantes**: Detectar y reportar valores NULL o campos vacíos, definiendo si son bloqueantes u opcionales.
- **Duplicados**: Identificar registros duplicados en historial de consumo o inventario.
- **Valores atípicos**: Reportar outliers en demanda histórica, precio o lead time para revisión manual.

**Salida de validación**
- Reporte de errores críticos (impiden procesamiento).
- Reporte de advertencias (no bloquean pero requieren revisión).
- Flag por pieza/proveedor/ciudad indicando si pasó validación.

**Implementación realizada** — `app/dataprep/validate.py`

`validate(tables) -> list[str]` levanta `ValueError` ante error crítico y
devuelve las advertencias. Cubre: integridad referencial de las tres llaves,
rangos (`precio ≥ 0`, `MOQ ≥ 1`, `lead_time > 0`, `cantidad ≥ 0`), nulos,
duplicados de llave, y la regla de negocio *cada pieza debe tener ≥ 2 ofertas*
(sin alternativas el optimizador no tiene nada que decidir).

Corre automáticamente dentro del build, **antes** de escribir los archivos.

*Pendiente de esta subetapa:* detección de **valores atípicos** (outliers de
demanda, precio y lead time). El resto de los chequeos del listado está cubierto.
El "flag por pieza/proveedor/ciudad" hoy es global, no por fila.

#### 1.2 Ingesta manual de datos de proveedores de piezas — ⏸️ PENDIENTE

Depende de la UI (Etapa 6) y de mover la persistencia a SQLite. No bloquea las
Etapas 1.3 a 5: el dataset actual ya trae los 5 proveedores necesarios.

Para casos donde los datos de proveedores no están en sistema centralizado, se propone un entorno de entrada manual con forma y validaciones:

**Campos requeridos en forma manual**
- Código de proveedor (único)
- Nombre del proveedor
- Ciudad donde opera
- Código de pieza que suministra
- Precio unitario
- Lead time promedio (días)
- Cantidad mínima de orden
- Disponibilidad (activo/inactivo)
- Email o contacto para órdenes

**Mecanismo de captura**
- Interfaz web simple (Streamlit o formulario HTML) donde el usuario ingresa los datos.
- Validación en tiempo real: alertas si precio < 0, lead time = 0, etc.
- Opción de descargar plantilla CSV para entrada bulk.
- Almacenamiento en base de datos local (SQLite o Postgres) con timestamp de creación.

**Aprobación y persistencia**
- Datos ingresados manualmente requieren aprobación de administrador antes de usarse en optimización.
- Se mantiene auditoría de quién, cuándo y qué modificó.

### Etapa 1.3 Clasificación de patrones de demanda — ✅ COMPLETADA

**Implementación:** `app/forecasting/patterns.py`, entrypoint
`python -m app.data.build_patterns`, salida `app/data/mvp/demand_patterns.csv`
(60 filas, una por serie `sku_id × city_id`).

**Hallazgo de calibración — importante si se tocan los umbrales.**
La fuerza estacional por sí sola **no sirve** con esta cantidad de historia: con
3 ciclos, `seasonal_decompose` extrae un componente estacional aparente incluso
de ruido puro (fuerza media 0,32; supera 0,40 en el **26 %** de los casos). Con
el umbral original, 26 de 60 series se habrían mandado a Prophet sin motivo.

La regla final exige **dos** condiciones: fuerza ≥ 0,45 **y** efecto de mes
significativo (Kruskal-Wallis, p < 0,05). Medido sobre 400 simulaciones:

| Serie | Detectada como estacional |
|---|---|
| Ruido tipo demanda MRO | 2 % (falso positivo aceptable) |
| Estacional amplitud ≈ ruido | 47 % (caso genuinamente ambiguo) |
| Estacional amplitud 2× ruido | 100 % |

El test `test_noise_is_rarely_labelled_seasonal` blinda esta calibración.

**Decisión de precedencia** (el spec no la definía): `Insuficiente → Estacional
→ Tendencia → Volátil → Estable`. Los patrones explicables ganan sobre
"Volátil", que es un cajón de sastre. Sin este orden, ninguna serie estacional
se detectaría jamás, porque tiene CV alto por definición.

**Decisión de grano:** se clasifica por `sku_id × city_id`, no sólo por pieza.
Lo confirman los datos: **11 de 20 piezas cambian de patrón según la ciudad**
(p. ej. MRO-10045 es Estable en Pune y Chennai, pero Estacional en Dharuhera).
Una etiqueta única por pieza habría ocultado esa diferencia.

Antes de hacer la proyección, se analiza el historial de consumo para clasificar el patrón de demanda de cada pieza, informando qué modelo y qué nivel de confianza esperar:

**Lo que el dataset ya permite (medido sobre `demand_history.csv`)**

| Hecho | Valor | Implicación |
|---|---|---|
| Historia disponible | **37 meses** (2022-01 a 2025-01) | Supera los 2 años que exige la categoría *Estacional*: la estacionalidad **sí es detectable** |
| Series a clasificar | **60** (20 piezas × 3 ciudades) | La clasificación es **por pieza y ciudad**, no sólo por pieza |
| Meses con demanda cero | **6,5 %** | La agregación mensual ya absorbió la intermitencia del dato diario (donde ~90 % de los días son cero) |
| CV mediano (σ/μ) | **0,42** | La mayoría de las series cae en *Estable* con el umbral de 0,5 del spec |
| Series con CV > 0,5 | **30 %** | Se clasificarán como *Volátil* |
| Series con CV > 1,0 | **3 %** | Sólo ~2 series necesitarán revisión humana frecuente |
| Categoría *Insuficiente* | **0 series** | Ninguna pieza tiene menos de 30 días de historial |

**Decisión de grano:** clasificar por combinación `sku_id + city_id`. Una misma
pieza puede ser estable en Pune y volátil en Chennai; una etiqueta única por
pieza ocultaría esa diferencia y degradaría el forecast de la Etapa 2.

**Nota sobre el umbral de volatilidad:** con CV mediano 0,42, el umbral de 0,5
del spec deja el 70 % de las series en *Estable*. Es un reparto razonable, pero
conviene revisarlo contra el error real del forecast en la Etapa 2 antes de
darlo por bueno.


**Categorías de patrón**
- **Estacional**: Demanda fluctúa con ciclo predecible (ej: mayor en verano, menor en invierno). Requiere al menos 2 años de datos. Confianza alta si ciclo es regular.
- **Tendencia**: Demanda crece o decrece sostenidamente. Requiere al menos 6 meses. Confianza media; riesgo si la tendencia invierte.
- **Estable**: Demanda promedio plana sin variación significativa. Requiere estadística de media y desviación estándar. Confianza alta.
- **Volátil**: Demanda fluctúa sin patrón claro. Requiere métodos robustos. Confianza baja; requiere revisión humana más frecuente.
- **Insuficiente**: Menos de 30 días de historial. No se hace proyección automática; se requiere entrada manual.

**Algoritmo de clasificación**
- Calcular autocorrelación y estacionalidad con `seasonal_decompose` (statsmodels).
- Aplicar test de tendencia (Mann-Kendall).
- Calcular coeficiente de variación (σ/μ) para evaluar volatilidad.
- Asignar categoría según criterios predefinidos.

**Salida**
- Etiqueta de patrón por pieza.
- Confianza inicial (0–1) según estabilidad del patrón.
- Recomendación de modelo a usar (Prophet para estacional, regresión lineal para tendencia, media móvil para estable, métodos robustos para volátil).

### Etapa 2. Proyección de demanda
Un modelo de ML estima la demanda futura por pieza y horizonte de tiempo. Para el MVP se recomienda usar un modelo sencillo y explicable como Prophet, XGBoost o un baseline de series de tiempo, priorizando rapidez de implementación y comparación de resultados [web:14][web:27].

El modelo se selecciona según el patrón de demanda clasificado en Etapa 1.3:
- **Estacional**: Prophet (maneja ciclos automáticamente).
- **Tendencia / Estable**: Regresión lineal simple o media móvil.
- **Volátil**: Métodos robustos (p.ej., mediana móvil, percentiles) con intervalos de confianza amplios.

**Tecnologías posibles**
- Prophet
- XGBoost
- scikit-learn
- statsmodels

**Consideración sobre el dato disponible**

El consumo diario es fuertemente intermitente (~90 % de días en cero, y el 86 %
de los eventos son de 1 unidad). **La agregación mensual ya resolvió esto**: a
grano mensual sólo el 6,5 % de las observaciones son cero. Por eso el forecast
debe trabajar sobre `demand_history.csv` (mensual) y **no** sobre el consumo
diario crudo — sobre el diario, Prophet y la regresión lineal fallarían y habría
que recurrir a métodos de demanda intermitente (Croston, SBA).

#### 2.1 Tiempos variables de proveedores
El lead time no es fijo. El sistema debe considerar:
- **Lead time promedio**: Valor esperado en condiciones normales.
- **Lead time mínimo**: Mejor caso (pieza siempre disponible).
- **Lead time máximo**: Peor caso (retrasos, aduanas, etc.).
- **Varianza histórica**: Desviación estándar de lead time registrados.

**Uso en proyección**
- Proyectar demanda para horizon = min(lead_time_max, horizonte_solicitado).
- Aumentar buffer de inventario mínimo según varianza de lead time.
- Si lead time máximo > horizonte de demanda, alertar riesgo de quiebre.

**Dato disponible en `suppliers.csv`** — las 4 métricas ya están calculadas a
partir de órdenes reales (`Delivery_Date − Order_Date`):

| Métrica | Rango observado |
|---|---|
| `lead_time_avg_days` | 10,2 a 11,3 días |
| `lead_time_min_days` | 1 día |
| `lead_time_max_days` | 20 días |
| `lead_time_std_days` | 5,46 a 6,01 días |

La variabilidad es **alta**: σ/μ ≈ 0,53. El peor caso (20 días) casi duplica el
promedio, así que el buffer por varianza de lead time no es un detalle cosmético
— es determinante para el stock de seguridad y debe implementarse, no omitirse.

#### 2.2 Confiabilidad de predicción según datos históricos
La confianza en la proyección se ajusta por:
- **Volumen de datos**: Menos de 30 días → confianza baja; 30–90 días → media; > 90 días → alta.
- **Volatilidad del patrón**: σ/μ > 0.5 → confianza media; σ/μ > 1.0 → confianza baja.
- **Cambios recientes**: Si últimos 7 días muestran cambio de patrón → reducir confianza.
- **Exactitud histórica del modelo**: Comparar predicciones previas con demanda real (MAPE, MAE). Si error promedio > 30% → confianza media; > 50% → baja.

**Score de confianza final**
Combinar factores: Confianza = f(volumen_datos, volatilidad, estabilidad_reciente, error_histórico)
Escala 0–1; mostrar siempre al usuario.

**Intervalo de confianza**
- Proyectar no solo punto central sino intervalo [Q25, Q50, Q75] o [IC_95_inf, IC_95_sup].
- Usar intervalo más amplio para demanda volátil o low-confidence.
- En optimización, considerar scenarios múltiples (pesimista, base, optimista).

### Etapa 3. Optimización de abastecimiento
La salida del modelo de demanda alimenta un módulo de optimización que calcula cuánto comprar y a qué proveedor asignar la compra. La técnica recomendada para el MVP es programación lineal entera mixta (MILP), porque permite modelar cantidades, selección de proveedor y restricciones operativas de forma auditable [web:41][web:42].

**Tecnologías posibles**
- OR-Tools
- PuLP
- Pyomo
- Solver CBC / Gurobi (si existe licencia)

**Dimensión real del problema** — 60 combinaciones pieza-ciudad y 51 ofertas de
proveedor (2 o 3 por pieza). Es un MILP **pequeño**: **PuLP con el solver CBC
(gratuito, incluido) resuelve esto en milisegundos**. No hace falta Gurobi ni su
licencia; introducirlo sería complejidad sin beneficio.

**Datos que el optimizador ya tiene disponibles por oferta** (`supplier_offers.csv`):
`unit_price_usd`, `moq`, `capacity_per_month`, `freight_cost_usd`; y por proveedor
(`suppliers.csv`): las 4 métricas de lead time y la ciudad donde opera.

> ⚠️ **Antes de implementar esta etapa hay que resolver el bloqueante de
> cobertura proveedor-ciudad descrito en §11.2**, o el modelo será infactible
> para el 25 % de las combinaciones.

### Etapa 4. Reglas de negocio y restricciones operativas
Antes de emitir la recomendación final, la solución debe aplicar reglas operativas. Estas reglas limitan lo que el optimizador puede recomendar y garantizan alineación con la operación real.

**Restricciones mínimas del MVP**
- No comprar si el inventario proyectado permanece por encima del mínimo.
- No superar el inventario máximo definido.
- No recomendar cantidades que excedan la demanda consumible dentro de la vida útil.
- No seleccionar proveedores que no operen para la ciudad requerida.
- No exceder capacidad máxima de compra o presupuesto del escenario.
- Permitir marcación de casos que requieran revisión humana.

**Cómo se comporta cada regla con el dataset actual**

| Regla | Estado | Observación |
|---|---|---|
| No comprar si está por encima del mínimo | ✅ Se ejercita | 22 de 60 combinaciones están bajo el punto de reorden y 38 por encima: el dataset activa **ambas ramas** de la decisión |
| No superar el inventario máximo | ⚠️ Falta el dato | `inventory_current.csv` **no tiene** columna de inventario máximo. Hay que definirlo (p. ej. cobertura objetivo en meses) al implementar la Etapa 3 |
| No exceder la vida útil | ⚠️ Rara vez se activa | La vida útil más corta (180 d, lubricación) supera al peor lead time (20 d) por 160 días. La regla **sólo** se activará por la vía de *cantidad > demanda consumible en la vida útil*, no por la vía del lead time |
| Proveedor debe operar en la ciudad | 🚫 **Bloqueante** | Ver §11.2: dejaría 15 de 60 combinaciones sin proveedor |
| No exceder capacidad / presupuesto | ✅ Dato disponible | `capacity_per_month` existe por oferta. El presupuesto del escenario aún no está definido: es un parámetro de entrada a definir |
| Marcar casos para revisión humana | ✅ Insumo disponible | La clasificación de patrón y el score de confianza (Etapas 1.3 y 2.2) alimentan este flag |

### Etapa 5. Explicación con LLM y comunicación de supuestos
Una vez generada la recomendación estructurada, un LLM produce una explicación en lenguaje natural para negocio o compras. El LLM no toma la decisión; solo explica con base en evidencia del forecast, del optimizador y de las reglas aplicadas [web:60][web:64].

**Explicación de supuestos**
El LLM debe comunicar explícitamente:
- **Patrón de demanda detectado** (ej: "demanda estacional con ciclo anual").
- **Confianza en proyección** (ej: "baja confianza por datos limitados").
- **Lead time asumido** (ej: "lead time promedio 15 días, máximo 25 días en casos de retraso").
- **Restricciones aplicadas** (ej: "no se compró porque inventario proyectado está por encima del mínimo").
- **Alternativas consideradas** (ej: "se evaluaron 3 proveedores; se seleccionó el de menor costo por cumplir restricciones").

**Prompt template**
```
Contexto:
- Pieza: {codigo_pieza}
- Demanda proyectada: {demanda_mes}
- Patrón: {patron_clasificado}
- Confianza: {score_confianza}
- Lead time: {lead_time_promedio} a {lead_time_maximo} días
- Inventario actual: {inv_actual}
- Inventario mínimo: {inv_min}
- Inventario máximo: {inv_max}
- Recomendación: {cantidad_compra} unidades de proveedor {proveedor_id}
- Razón de rechazo (si aplica): {razon_no_compra}

Genera una explicación clara, breve y orientada a compras que:
1. Justifique la recomendación con datos.
2. Comunique supuestos y confianza.
3. Alerte si confianza es baja o si hay excepciones.
```

**Tecnologías posibles**
- OpenAI / Azure OpenAI / modelo open source
- Prompt template con entrada JSON
- FastAPI para exponer la explicación

### Etapa 6. Interfaz de usuario y flujo manual de compra
El MVP debe incluir una interfaz simple donde se visualicen inputs, resultado del forecast, recomendación final, proveedor elegido y justificación textual. También puede incluir una acción de aprobación o rechazo humano.

**Flujo operativo actual (MVP)**
1. **Sistema genera recomendación**: El MVP entrega tabla con columnas [Pieza, Demanda proyectada, Inventario mínimo/máximo, Cantidad recomendada, Proveedor, Confianza, Motivo].
2. **Cliente revisa y aprueba**: El usuario (comprador) revisa la recomendación en la interfaz y decide si aprueba la cantidad y proveedor sugeridos.
3. **Cliente contacta al proveedor manualmente**: Una vez aprobada, el cliente usa la información (cantidad, especificaciones, lead time) para contactar al proveedor por teléfono, email o portal y confirmar la orden.
4. **Confirmación de compra**: El cliente registra en la interfaz que la orden fue confirmada, incluyendo número de orden del proveedor y fecha esperada de entrega.

**Elementos de UI necesarios**
- Tabla de recomendaciones con capacidad de filtrado (ciudad, pieza, estado).
- Botón "Aprobar" y "Rechazar" por fila.
- Si rechaza: campo de "motivo del rechazo" (dropdown + texto libre).
- Columna de "estado de compra" (Pendiente aprobación → Aprobado → Contactado proveedor → Orden confirmada).
- Detalles del proveedor: nombre, email, teléfono, lead time.
- Capacidad de descargar recomendación como CSV o PDF.

**Tecnologías posibles**
- Streamlit
- Gradio
- React + FastAPI

## 5. Qué hace la IA y qué hace el humano

### IA / Automatización
- Proyecta demanda futura.
- Calcula recomendación de compra.
- Evalúa proveedor óptimo bajo restricciones.
- Genera explicación de la recomendación.

### Humano
- Revisa excepciones.
- Aprueba compras sensibles o fuera de patrón.
- Ajusta reglas de negocio.
- Valida calidad de datos y criterios operativos [web:60][web:69].

## 6. Restricciones operativas del MVP
Para mantener el MVP controlado y demostrable, se propone limitar el alcance inicial a:

| Restricción propuesta | Realizado | Nota |
|---|---|---|
| 10 a 20 piezas | **20 piezas** | En el tope del rango |
| 2 ciudades | **3 ciudades** | Se subió a 3 porque el dato crudo trae 3 plantas naturales (Pune, Chennai, Dharuhera); recortar a 2 habría sido descartar datos reales |
| 3 a 5 proveedores | **5 proveedores** | En el tope del rango |
| 6 a 12 meses de histórico | **37 meses** | Muy por encima de lo pedido. Habilita detectar estacionalidad, que con 12 meses sería imposible |

- Un único flujo de recomendación por corrida.
- Datos batch, no streaming.
- Sin integración directa con ERP en la primera versión.
- Persistencia en CSV; sin base de datos hasta que exista escritura desde la UI.

## 7. Salida esperada
Por cada pieza, el sistema debe entregar:
- Demanda proyectada.
- Inventario mínimo.
- Inventario máximo.
- Cantidad recomendada.
- Cantidad máxima permitida.
- Proveedor sugerido.
- Motivo de la recomendación.
- Flag de revisión humana, si aplica.

## 8. Arquitectura general propuesta

| # | Componente | Estado | Ubicación prevista |
|---|---|---|---|
| 1 | Fuente de datos de inventario y proveedores | ✅ Hecho | `app/data/mvp/` |
| 2 | Módulo de validación y limpieza | ✅ Hecho | `app/dataprep/validate.py` |
| 3 | Entrada manual de proveedores | ⏸️ Pendiente | `app/api/` + UI |
| 4 | Clasificador de patrones de demanda | ✅ Hecho | `app/forecasting/patterns.py` |
| 5 | Modelo ML de proyección | ⏭️ Siguiente | `app/forecasting/models.py` |
| 6 | Módulo de optimización MILP | ⬜ Pendiente | `app/optimization/` |
| 7 | Motor de reglas de negocio | ⬜ Pendiente | `app/rules/` |
| 8 | Capa LLM de explicación | ⬜ Pendiente | `app/explain/` |
| 9 | Interfaz de usuario | ⬜ Pendiente | Streamlit o FastAPI + front |
| 10 | Feedback y reentrenamiento | ⬜ Pendiente | `app/feedback/` |

**Convención establecida en la Etapa 1** (conviene mantenerla en los módulos
siguientes): cada módulo expone **funciones puras** que reciben y devuelven
DataFrames, con la configuración en un `config.py` propio y la aleatoriedad
siempre derivada de una semilla explícita. Esto es lo que hace el build
idempotente y los tests deterministas.

El proyecto ya tiene un esqueleto FastAPI (`app/main.py`, `app/api/routes.py`,
`app/core/config.py`) y un `Dockerfile`, aún no conectados al flujo de datos.

## 9. Feedback loop y mejora continua

### 9.1 Captura de feedback del usuario
Una vez que la compra es confirmada y se recibe la pieza:
- **Compra confirmada vs. real**: ¿Se compró exactamente lo recomendado o el cliente ajustó cantidad/proveedor? Registrar desviación.
- **Demanda real vs. proyectada**: Registrar demanda real en período siguiente (p.ej., próximos 30 días) vs. predicción del modelo.
- **Satisfacción con proveedor**: ¿Lead time cumplió expectativa? ¿Calidad fue conforme? ¿Precio estuvo acorde?
- **Comentarios del usuario**: Captura opcional de texto libre para explicar cambios o problemas.

**Campos de captura**
- Pieza, período de recomendación.
- Cantidad comprada vs. recomendada.
- Proveedor utilizado vs. recomendado.
- Demanda observada.
- Lead time real.
- Observación cualitativa.

### 9.2 Métricas de precisión y desempeño
Calcular regularmente:
- **MAPE (Mean Absolute Percentage Error)**: Exactitud del forecast por pieza y período.
- **Ratio de cumplimiento**: Porcentaje de recomendaciones que el cliente siguió sin ajustes.
- **Tasa de quiebres**: Casos donde el inventario no alcanzó para la demanda.
- **Tasa de sobrestock**: Casos donde el inventario terminó muy por encima de lo consumido.
- **Confianza promedio**: Score promedio de confianza de predicciones aceptadas vs. rechazadas.

### 9.3 Reentrenamiento del modelo
Cada período (p.ej., cada mes):
- Incorporar datos reales observados (demanda, lead time) al histórico.
- Re-clasificar patrones si distribución cambió significativamente.
- Re-entrenar el modelo ML con los nuevos datos.
- Comparar precisión nueva vs. anterior; reportar mejora o degradación.
- Si MAPE aumenta > 10%, activar alerta para revisión manual de datos o cambios operativos.

### 9.4 Iteración y mejora de reglas
- Monitorear reglas de negocio que causaron más rechazos.
- Si una regla resulta contraproducente (ej: muchos quiebres por regla conservadora), proponer ajuste.
- Documentar cambios de regla y su impacto en siguientes períodos.

## 10. Criterio de éxito del MVP
El MVP se considera exitoso si logra demostrar que, para un conjunto acotado de piezas, puede transformar datos operativos en una recomendación explicable de compra, con trazabilidad suficiente para revisión de negocio y validación humana [web:27][web:41][web:64]. Además, debe capturar suficiente feedback del usuario y de resultados reales para permitir reentrenamiento y mejora continua del modelo.


## 11. Plan de trabajo y próximos pasos

### 11.1 Orden de ejecución

| Paso | Etapa | Depende de | Bloqueado por |
|---|---|---|---|
| ✅ 1 | Ingesta, preparación y validación (1, 1.1) | — | — |
| ✅ 2 | Clasificación de patrones de demanda (1.3) | Paso 1 | — |
| ⏭️ 3 | Proyección de demanda y confianza (2, 2.1, 2.2) | Paso 2 | Nada — **listo para empezar** |
| 4 | Optimización MILP (3) | Paso 3 | **§11.2 y §11.3** |
| 5 | Motor de reglas de negocio (4) | Paso 4 | **§11.3** |
| 6 | Explicación con LLM (5) | Paso 5 | Nada |
| 7 | Interfaz de usuario (6) | Paso 6 | Nada |
| 8 | Ingesta manual de proveedores (1.2) | Paso 7 | Requiere SQLite |
| 9 | Feedback y reentrenamiento (9) | Paso 7 | Nada |

Los pasos 2 y 3 pueden avanzar de inmediato. Los bloqueantes §11.2 y §11.3 sólo
afectan del paso 4 en adelante, pero **conviene resolverlos ya** porque ambos son
cambios en el dataset, no en el modelo.

### 11.2 Bloqueante: cobertura proveedor-ciudad

**El problema.** El modelo actual asigna a cada proveedor **una sola** `city_id`
(la ciudad donde opera):

| Ciudad | Proveedores que operan ahí |
|---|---|
| Pune | SUP-01, SUP-04 |
| Chennai | SUP-02, SUP-05 |
| Dharuhera | SUP-03 |

Las ofertas de `supplier_offers.csv`, en cambio, se asignaron por pieza sin mirar
la ciudad. Al cruzar ambas cosas con la regla *"no seleccionar proveedores que no
operen para la ciudad requerida"*, el resultado es:

- Pune: 3 piezas sin proveedor válido
- Chennai: 5 piezas sin proveedor válido
- Dharuhera: 7 piezas sin proveedor válido
- **Total: 15 de 60 combinaciones pieza-ciudad quedarían sin ninguna opción de compra**, y el MILP sería infactible para ellas.

**Opciones de solución** (recomendada primero):

1. **Modelar la cobertura como muchos-a-muchos** — nueva tabla
   `supplier_coverage(supplier_id, city_id, freight_cost_usd, lead_time_extra_days)`.
   Un proveedor puede despachar a varias ciudades, pero fuera de su sede cuesta
   más flete y tarda más. Es lo más fiel a la operación real y convierte la
   restricción dura en un trade-off económico, que es justamente lo que un MILP
   sabe resolver bien.
2. **Reinterpretar `suppliers.city_id` como "ciudad sede"**, no como restricción
   dura, penalizando el envío a otras ciudades vía flete. Más simple, menos
   explícito.
3. **Garantizar en el build ≥ 1 oferta por pieza y ciudad.** Resuelve la
   factibilidad pero fuerza los datos para que encajen con la regla, en vez de
   modelar la realidad.

### 11.3 Datos que aún faltan definir

Estos campos no existen en el dataset y son necesarios para las Etapas 3 y 4:

- **Inventario máximo por pieza/ciudad.** La regla *"no superar el inventario
  máximo"* no se puede evaluar hoy. Propuesta: derivarlo de una cobertura
  objetivo en meses de demanda proyectada, en vez de fijar un número por pieza.
- **Presupuesto del escenario.** Parámetro de entrada de la corrida; hoy no está
  definido ni como dato ni como constante.
- **Horizonte de proyección.** Cuántos meses proyectar (sugerido: 1 a 3 meses,
  coherente con un lead time máximo de 20 días).

### 11.4 Deuda técnica registrada

- **Outliers sin detectar** (Etapa 1.1): falta el chequeo de valores atípicos en
  demanda, precio y lead time.
- **Flag de validación global, no por fila**: el spec pide un flag por
  pieza/proveedor/ciudad; hoy la validación es todo-o-nada.
- **`app/data/__init__,py`**: archivo con una coma en lugar de punto, remanente
  del scaffold inicial. Inofensivo pero conviene borrarlo.
- **Token de GitHub expuesto**: el remote `origin` tiene un Personal Access Token
  en texto plano en la URL. **Debe revocarse y rotarse.**

---

## 12. Colores de MVP

Rol de interfaz	Color	Hex	Uso recomendado
Azul corporativo	Azul profundo	#003B70	Header, navegación, botones primarios, títulos clave
Azul secundario	Azul medio	#0067A0	Estados activos, enlaces, gráficos principales
Azul claro	Azul suave	#D9EAF4	Fondos informativos, filtros activos, tarjetas destacadas
Negro carbón	Texto oscuro	#1F2933	Texto principal y etiquetas
Gris medio	Texto secundario	#667085	Descripciones, metadatos y campos no prioritarios
Gris claro	Fondo neutro	#F5F7FA	Fondo general de pantalla y tablas
Blanco	Superficie	#FFFFFF	Tarjetas, formularios y paneles
Verde operativo	Éxito	#2E7D32	Compra aprobada, inventario saludable, proveedor recomendado
Ámbar preventivo	Advertencia	#C88700	Stock cercano al mínimo, lead time alto, revisión requerida
Rojo crítico	Riesgo	#C62828	Riesgo de quiebre, vencimiento, restricción incumplida
La interfaz debe priorizar azul y neutros; verde, ámbar y rojo deben usarse únicamente como estados operativos, no como colores decorativos. El azul es coherente con la identidad visual corporativa observada en la marca Constellation Brands.

css
:root {
  --primary: #003B70;
  --secondary: #0067A0;
  --primary-light: #D9EAF4;

  --text-primary: #1F2933;
  --text-secondary: #667085;
  --background: #F5F7FA;
  --surface: #FFFFFF;

  --success: #2E7D32;
  --warning: #C88700;
  --danger: #C62828;
}