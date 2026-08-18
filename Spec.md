# Spec — MVP de optimización de inventario con IA

---

## 0. Estado actual de la implementación

**Última actualización:** 2026-08-12

### Qué está hecho

| Etapa | Estado | Dónde vive |
|---|---|---|
| **0 · Perfilado y limpieza de fuentes** | ✅ | `app/core/profiling.py`, `app/core/cleaning.py` |
| 1 · Ingesta y preparación | ✅ | `app/core/dataset.py` |
| 1.1 · Validación | ✅ | `app/core/validation.py` |
| 1.2 · Ingesta manual de proveedores | ⬜ | — |
| 1.3 · Clasificación de patrones | ✅ | `app/core/patterns.py` |
| 2 · Proyección de demanda | ✅ | `app/core/forecast.py` |
| 2.b · Modelo ML entrenado | ✅ | `app/core/training.py` |
| **2.c · Historia sintética** | ✅ | `app/core/synthesis.py` |
| 3 · Optimización MILP | ✅ | `app/core/optimization.py` |
| **3.b · Presupuesto y costo de quiebre** | ✅ | mochila en `app/core/optimization.py` |
| 4 · Reglas de negocio | ✅ | dentro del optimizador |
| 5 · Explicación con LLM | ✅ código listo, ⏸️ sin clave | `app/services/llm_agent.py` |
| 6 · Interfaz | ✅ reescrita | `app/api/` + `frontend/` |
| **6.b · Recorrido del pipeline y explorador de datos** | ✅ | `app/services/pipeline_report.py`, `data_views.py` |
| 9 · Feedback y reentrenamiento | ⬜ | — |

**284 tests** en `tests/core/`.

### Lo que cambió desde la versión anterior de este documento

**El presupuesto ya no es una idea pendiente.** El optimizador resuelve una
mochila sobre todas las piezas a la vez: reparte el presupuesto de la corrida
maximizando el beneficio neto —lo que cuesta el quiebre que se evita menos lo
que cuesta evitarlo— y publica una cuarta decisión, `APLAZADO`, para las
reposiciones que procedían y no cupieron. Con ella entran `stockout_cost_usd` y
`net_benefit_usd` por fila. Esto cierra dos puntos que §11 daba por pendientes:
el presupuesto global y el costo de quiebre en la función objetivo.

**La interfaz se reescribió entera** y vive en `frontend/`, fuera de `app/`. Se
compila con Vite —sin framework: sigue siendo HTML y módulos ES— para poder
publicarse en Amplify como sitio estático mientras la API queda en ECS. El
detalle está en la Etapa 6.

### Arquitectura

Tres capas con dependencias en una sola dirección `api → services → core`,
verificado por regla: `core` no importa nada de las otras dos.

| Capa | Responsabilidad |
|---|---|
| `app/core/` | Dominio puro: perfilado, limpieza, síntesis, política de inventario, patrones, proyección, optimización y modelo ML. No toca disco ni red |
| `app/services/` | Casos de uso y adaptadores externos: SQLite, Gemini, MLflow, archivos, y los scripts ejecutables |
| `app/api/` | Único puerto HTTP, con DTOs |
| `app/data/` | Solo CSV, sin código |
| `artifacts/` | Modelo serializado, métricas y gráficas |

Los parámetros viven al inicio del módulo que los usa. No hay archivos de
configuración aparte.

### Cómo se levanta

```
python -m app.services.profile_data           # perfila y limpia las fuentes
python -m app.services.build_dataset          # dataset relacional validado
python -m app.services.build_patterns         # clasificación de patrones
python -m app.services.train_model            # modelo ML + métricas + gráficas
python -m app.services.build_forecast         # proyección e inventario mínimo
python -m app.services.build_recommendations  # decisiones de compra
python -m uvicorn app.main:app --port 8000
```

### Archivos generados en `app/data/mvp/`

| Archivo | Filas | Contenido |
|---|---|---|
| `parts_master.csv` | 20 | Maestro de piezas |
| `inventory_current.csv` | 40 | Inventario por pieza y ciudad |
| `demand_history.csv` | 2.880 | **72 meses** (2020-02 a 2026-01), con `is_synthetic` |
| `suppliers.csv` | 5 | Proveedores con lead time real |
| `supplier_offers.csv` | 52 | Precio, MOQ y capacidad por pieza |
| `supplier_coverage.csv` | 10 | Qué proveedor atiende qué ciudad |
| `cities.csv` | 2 | Nava (Coahuila) y Ciudad Obregón (Sonora) |
| `demand_patterns.csv` | 40 | Patrón y confianza por serie |
| `demand_forecast.csv` | 40 | Proyección, inventario mínimo, confianza |
| `purchase_recommendations.csv` | 40 | **Decisión final con su motivo** |
| `quality/` | — | Informe de calidad y meses de consumo atípico |

### Resultado actual

| Decisión | Casos |
|---|---|
| COMPRAR | 7 · 2.430,89 USD · 317 unidades |
| REVISAR | 7 |
| **APLAZADO** | 3 · 1.116,94 USD sin financiar |
| NO_COMPRAR | 23 |

Presupuesto de la corrida: **2.500 USD**. Evita 12.485,80 USD de quiebre, un
retorno de 5,1×, y deja 3.152,08 USD de riesgo sin cubrir en las tres
reposiciones aplazadas.

Patrones: 26 Estable · 9 Volátil · 5 Estacional.
Modelo: **WMAPE 21,1 %**, mejora 28,2 % sobre repetir el último mes y 3,2 %
sobre el promedio móvil. Sesgo −0,62 unidades/mes.

### Observabilidad con `mlops_sdk`

Instalado desde el GitLab interno (`v0.5.0`). En uso: `BaseModel` en
`DemandModel`, `MLObserver` para Prometheus, y `BaseAgent` con
`llm_provider="gemini"` en `ExplanationAgent`.

**MLflow ya está configurado** con `MLFLOW_TRACKING_URI` apuntando al ALB
interno de MLflow. Ojo: cuando ese servidor no responde —está sujeto al mismo
apagado programado que el resto—, el SDK registra el fallo y sigue, y las
pruebas se llenan de avisos de reintento que tapan el resumen de pytest. No
rompe nada, pero conviene saberlo antes de leer un log y pensar que algo falló.
Sin la variable, el SDK guarda en `./artifacts/<run_id>/`.

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

### Etapa 0. Perfilado y limpieza de fuentes — ✅ COMPLETADA

Etapa que no estaba en el spec original y resultó necesaria: se validaba el
dataset generado pero nunca se limpiaba el crudo.

**Implementación:** `app/core/profiling.py` y `app/core/cleaning.py`,
entrypoint `python -m app.services.profile_data`, salida en
`app/data/mvp/quality/`.

**Perfilado.** Por cada fuente reporta tipos, nulos, cardinalidad, rangos,
duplicados exactos y por llave, y valores atípicos con dos criterios a la vez:
rango intercuartílico y desviación absoluta mediana. Se reportan ambos porque
discrepan de forma informativa — cuando el robusto marca muchos más que el
clásico, la columna tiene cola pesada.

**Problemas reales encontrados y corregidos:**

| Problema | Magnitud | Tratamiento |
|---|---|---|
| **Órdenes canceladas contadas como entregas** | 130 de 689 | Se filtran por `Order_Status`. Era un error nuestro: sesgaba el lead time ~0,2 días a la baja |
| Órdenes sin fecha de pedido o entrega | 87 | Se descartan: sin ambas fechas no hay plazo medible |
| Plazo de entrega ≤ 0 | 1 | Se descarta |
| `Defective_Units` nulo | 136 | Se imputa cero: la ausencia significa que no se reportaron defectos |
| Mes con un solo día registrado (2025-01) | 200 filas | Se descarta: se leería como caída de la demanda |

**Dos cosas que parecen anomalías y no lo son.** El 90 % de filas con consumo
cero es la intermitencia natural del consumo de refacciones, no un defecto, y
se conserva porque la ausencia de consumo es información. El 80 % de nulos en
`wo_type` tampoco: esa columna solo aplica cuando el movimiento nace de una
orden de trabajo, así que se rellena con `SIN_ORDEN` en lugar de descartarla.

**Los atípicos de sensor se marcan, no se eliminan.** Son 44.860 lecturas. Una
vibración o temperatura extrema suele ser justamente la señal de que la máquina
va a fallar, es decir el evento que anticipa el consumo. Borrarlas eliminaría la
información más valiosa del conjunto.

**Los meses de consumo atípico se reportan, no se corrigen.** Son 9, evaluados
contra la propia serie y no contra el conjunto, porque una pieza de 100
unidades al mes y otra de 2 tienen escalas incomparables. Requieren
confirmación de mantenimiento: puede haber sido una parada mayor real.

**Limitación asumida del detector robusto.** Cuando más de la mitad de las
observaciones son idénticas —el caso normal en refacciones— la desviación
mediana vale cero y el criterio se ciega. Se recurre entonces a la desviación
media respecto de la mediana. Con un tercio de valores extremos ningún criterio
univariante debería marcarlos: eso ya es una distribución con dos grupos y el
problema es de segmentación, no de limpieza.

### Etapa 1. Ingesta y preparación de datos — ✅ COMPLETADA
Se consolidan los datos necesarios para la recomendación: inventario actual, historial de consumo, catálogo de piezas, proveedores, ciudades, precios, lead time y vida útil. En el MVP estos datos pueden provenir de archivos CSV o tablas simples para reducir complejidad inicial.

**Tecnologías posibles**
- Python
- Pandas
- CSV / SQLite / Postgres

**Implementación realizada**
- `app/core/dataset.py`: constantes al inicio y un constructor por tabla, todas
  funciones puras.
- Orquestación en `app/services/dataset_builder.py`, entrypoint
  `python -m app.services.build_dataset`.
- Persistencia: **CSV** en `app/data/mvp/`. SQLite/Postgres se pospone hasta que
  haya escritura desde la UI (Etapa 1.2 y 6); mientras el flujo sea de sólo
  lectura, CSV es suficiente y mantiene el dataset versionable y diffeable.
- Decisiones tomadas: **2 ciudades** (Nava, Coahuila y Ciudad Obregón, Sonora),
  montos en **USD** (1 USD = 83 INR), demanda a grano **mensual**.
- Las 3 plantas del dato crudo se consolidan en 2 ciudades: dos van a Nava, que
  es el complejo mayor, y una a Obregón. Así no se descarta historia y el
  desbalance de volumen (Nava mueve 2,3× lo de Obregón) es realista.
- El histórico se **desplaza** para terminar en 2026-01 (`shift_demand_to_horizon`)
  y luego se **amplía hacia atrás** con meses simulados (`extend_history`), lo
  que da 72 meses en total. Ver Etapa 2.c.
- La carga de fuentes aplica las reglas de limpieza de la Etapa 0 antes de
  construir nada.

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

**Implementación realizada** — `app/core/validation.py`

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

**Implementación:** `app/core/patterns.py`, entrypoint
`python -m app.data.build_patterns`, salida `app/data/mvp/demand_patterns.csv`
(60 filas, una por serie `sku_id × city_id`).

**Hallazgo de calibración — importante si se tocan los umbrales.**
La fuerza estacional por sí sola **no sirve** con esta cantidad de historia: con
3 ciclos, `seasonal_decompose` extrae un componente estacional aparente incluso
de ruido puro (fuerza media 0,32; supera 0,40 en el **26 %** de los casos). Con
el umbral original, 26 de 60 series se habrían mandado al modelo estacional sin
motivo (medido sobre el dataset de 3 ciudades vigente entonces).

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
Lo confirman los datos: **8 de 20 piezas cambian de patrón según la ciudad**
(p. ej. MRO-30011 es Estacional en Nava pero Estable en Ciudad Obregón).
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
pieza puede ser estable en una planta y volátil en otra; una etiqueta única por
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

### Etapa 2. Proyección de demanda — ✅ COMPLETADA

**Implementación:** `app/core/forecast.py` y `app/services/inventory_policy.py`,
entrypoint `python -m app.data.build_forecast`, salida `demand_forecast.csv`.

**Se sustituyó Prophet por Holt-Winters** para las series estacionales. Razones:
con 36 observaciones mensuales y 3 ciclos, Prophet está sobredimensionado y
sobreajusta; además exige compilar Stan, que en Windows complica la demo.
Holt-Winters viene en `statsmodels`, ya instalado, y es igual de explicable.
Solo 6 de 40 series ajustan un modelo: el 85 % se resuelve con métodos
estadísticos simples, que es lo correcto para este volumen de datos.

**Métrica de error: WMAPE** (error absoluto sobre el total), no MAPE clásico.
La demanda de repuestos tiene meses en cero y el MAPE dividiría entre cero,
inflando el error artificialmente.

**Política de inventario unificada.** Durante esta etapa se detectó que
convivían dos definiciones de inventario mínimo: el dataset cubría un mes
completo de demanda y la proyección solo el plazo de entrega real (10,8 días).
El umbral del dataset quedaba 1,9× más alto y ambas etapas daban respuestas
opuestas — 18 piezas a reponer según una, 3 según la otra. Ahora ambas usan
`app/services/inventory_policy.py`, que calcula el mínimo como demanda durante
el plazo de entrega más un colchón que absorbe la variabilidad de la demanda
**y** la del propio plazo (σ/μ ≈ 0,53 en estos proveedores).
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

### Etapa 3. Optimización de abastecimiento — ✅ COMPLETADA

**Implementación:** `app/core/optimization.py`, entrypoint
`python -m app.data.build_recommendations`, salida `purchase_recommendations.csv`.

**Solver: PuLP con CBC** (gratuito). Cada pieza-ciudad se resuelve como un
modelo independiente de a lo sumo 3 ofertas: milisegundos por caso. No se
necesita Gurobi.

**Formulación.** Variables por oferta: cantidad entera y binaria de activación.
Objetivo: minimizar precio × cantidad + flete. Restricciones: cubrir el faltante
hasta el mínimo, no pasar del máximo, respetar MOQ solo si se activa el
proveedor, no exceder su capacidad, y un único proveedor por pieza-ciudad para
que la orden sea simple de ejecutar.

**Se añadió un tercer estado de decisión: `REVISAR`.** Al implementar, 9 de 18
casos volvían "no factible". No era un fallo del solver sino una tensión real
de compras: el mínimo de orden del proveedor supera el máximo que la pieza
admite en bodega. Por ejemplo, el O-ring MRO-20032 se vende en lotes de 100 pero
solo caben 48. Devolver "infactible" escondía la decisión; ahora el sistema
resuelve igualmente, informa cuánto costaría y cuántos meses de inventario
dejaría, y lo marca para que decida el comprador.

**Inventario máximo**, que faltaba como dato, se deriva de una cobertura
objetivo de 3 meses sobre la demanda proyectada (`MAX_COVERAGE_MONTHS`), nunca
por debajo del mínimo.

La salida del modelo de demanda alimenta un módulo de optimización que calcula cuánto comprar y a qué proveedor asignar la compra. La técnica recomendada para el MVP es programación lineal entera mixta (MILP), porque permite modelar cantidades, selección de proveedor y restricciones operativas de forma auditable [web:41][web:42].

**Tecnologías posibles**
- OR-Tools
- PuLP
- Pyomo
- Solver CBC / Gurobi (si existe licencia)

**Dimensión real del problema** — 40 combinaciones pieza-ciudad y 52 ofertas de
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
| No comprar si está por encima del mínimo | ✅ Se ejercita | 18 de 40 combinaciones están bajo el inventario mínimo y 22 por encima: el dataset activa **ambas ramas** de la decisión |
| No superar el inventario máximo | ⚠️ Falta el dato | `inventory_current.csv` **no tiene** columna de inventario máximo. Hay que definirlo (p. ej. cobertura objetivo en meses) al implementar la Etapa 3 |
| No exceder la vida útil | ⚠️ Rara vez se activa | La vida útil más corta (180 d, lubricación) supera al peor lead time (20 d) por 160 días. La regla **sólo** se activará por la vía de *cantidad > demanda consumible en la vida útil*, no por la vía del lead time |
| Proveedor debe operar en la ciudad | 🚫 **Bloqueante** | Ver §11.2: dejaría 7 de 40 combinaciones sin proveedor |
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

### Etapa 6. Interfaz de usuario y flujo manual de compra — ✅ COMPLETADA

**Implementación:** FastAPI sirve tanto la API (`app/api/routes.py`) como la
interfaz estática (`app/web/`). Un solo proceso y una sola imagen de contenedor,
en lugar de levantar Streamlit aparte.

**Concepto de pantalla: se abre arriba y se baja al detalle.** La primera
versión abría en el nivel más granular que tenía —cuarenta filas por siete
columnas— y no ofrecía ninguno por encima. De ahí salía todo lo demás: la tabla
completa de entrada, seis filtros antes de saber qué se quiere filtrar, y la
necesidad de explicar con palabras que cada decisión es por pieza y por ciudad.

Ahora hay tres niveles. **El turno** resume el día en una frase con las cifras
dentro del texto y reparte los casos en dos columnas, una por planta: el grano
de la decisión deja de necesitar explicación porque es la estructura de la
página. Dentro de cada planta, tres bandas ordenadas por quién debe actuar, y la
primera dice de forma explícita que ahí hace falta una persona. **El caso** es un
panel propio que cuenta la decisión en el orden en que se forma: qué consume,
qué va a consumir, cuánto necesita en bodega y a quién comprarle. **La tabla**
completa sigue existiendo como destino, no como portada.

**Elemento distintivo: el medidor de existencias.** Una barra que muestra el
stock actual sobre la escala del máximo permitido, con una marca en el punto
mínimo. Codifica de un vistazo la tensión que decide cada caso —si la barra no
llega a la marca, hay que reponer— sin obligar a leer tres números. Era la
tercera columna de una tabla de siete; ahora es el centro de cada tarjeta. Los
colores de estado del spec se usan solo aquí y en las etiquetas de decisión,
nunca como decoración.

**Los casos `REVISAR` no reciben plantilla de recomendación sino de pregunta.**
Son el 39 % de lo accionable y antes se veían igual que una compra, con una
etiqueta ámbar. Ahora enfrentan las dos salidas con su costo —comprar el lote
mínimo con su sobrestock, o no comprar con su riesgo de quiebre— porque ahí el
sistema no decide y fingir que sí lo hace es lo que confundía.

**El dato generado va marcado, no tapado.** Vida útil, lote mínimo, flete y
capacidad los produce el build con semilla fija (§11.3). Llevan un distintivo
donde aparecen, y los meses de histórico simulado se dibujan en trazo
discontinuo. Presentar como observación algo que es un supuesto era la parte
menos defendible de la pantalla anterior.

**Flujo de estados** con transiciones validadas en servidor:
`Pendiente aprobación → Aprobado → Contactado proveedor → Orden confirmada`,
más `Rechazado` desde cualquier punto previo, con motivo obligatorio y texto
libre. Cada cambio queda auditado con autor y fecha en `audit_log`.

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
| 2 ciudades | **2 ciudades** | Nava (Coahuila) y Ciudad Obregón (Sonora). Las 3 plantas del dato crudo se consolidan en 2 sin descartar historia |
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
| 2 | Módulo de validación y limpieza | ✅ Hecho | `app/core/validation.py` |
| 3 | Entrada manual de proveedores | ⏸️ Pendiente | `app/api/` + UI |
| 4 | Clasificador de patrones de demanda | ✅ Hecho | `app/core/patterns.py` |
| 5 | Modelo ML de proyección | ✅ Hecho | `app/core/forecast.py` |
| 6 | Módulo de optimización MILP | ⏭️ Siguiente | `app/core/optimization.py` |
| 7 | Motor de reglas de negocio | ⬜ Pendiente | `app/services/rules_service.py` |
| 8 | Capa LLM de explicación | ⬜ Pendiente | `app/services/explanation_service.py` |
| 9 | Interfaz de usuario | ⬜ Pendiente | Streamlit o FastAPI + front |
| 10 | Feedback y reentrenamiento | ⬜ Pendiente | `app/services/feedback_service.py` |

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


## 11. Qué falta, qué mejorar y qué no se está teniendo en cuenta

### 11.1 Lo que falta para cerrar el alcance del spec

| # | Pendiente | Esfuerzo | Por qué importa |
|---|---|---|---|
| 1 | **Clave de Gemini** (`GEMINI_API_KEY` en `.env`) | minutos | El agente está escrito y probado; sin clave cae a plantilla |
| 2 | **Servidor MLflow** (`MLFLOW_TRACKING_URI`) | minutos | Hoy los runs quedan en disco local y no se comparan entre sí |
| 3 | **Feedback loop** (§9) | alto | Es la mitad del valor del sistema y hoy no existe nada |
| 4 | **Detección de outliers** (§1.1) | bajo | Un consumo atípico hoy entra al modelo sin marcarse |
| 5 | ~~Presupuesto de escenario~~ | — | ✅ **Hecho.** Mochila sobre el presupuesto de la corrida, con decisión `APLAZADO` |
| 6 | **Ingesta manual de proveedores** (§1.2) | medio | Depende de mover la persistencia a base de datos |
| 7 | **Reentrenamiento periódico** | medio | Hoy el modelo se entrena a mano |
| 8 | **Persistencia de aprobaciones fuera de la imagen** | medio | Hoy se pierden cada noche. Ver §11.3 |
| 9 | **Autenticación** | medio | Sin ella la auditoría no prueba nada. Ver §11.3 |

### 11.2 Mejoras sobre lo ya construido

**El modelo apenas supera al promedio móvil (0,8%).** Es el hallazgo más
importante del entrenamiento y conviene no taparlo. Con 36 meses y series
mayormente planas, no hay mucha estructura que aprender. Tres caminos reales:

1. **Más historia o más series.** Un modelo global mejora con volumen. Con 20
   piezas y 3 años está en el límite de lo que puede aprender.
2. **Variables externas.** Hoy el modelo solo mira su propio pasado. Órdenes de
   trabajo programadas, paros de planta, horas de operación de la máquina o
   plan de producción son las variables que de verdad explican el consumo de
   refacciones. Esa es la mejora con mayor retorno esperado.
3. **Aceptar el resultado.** Si el promedio móvil basta, el valor del sistema
   está en la optimización y la trazabilidad, no en el forecast. Es una
   conclusión legítima y vale la pena decirla en la demo.

**Otras mejoras concretas:**

- **Cantidad económica de pedido.** Hoy `TARGET_COVERAGE_MONTHS = 1.5` es un
  parámetro fijo. El óptimo real sale de equilibrar el costo de ordenar contra
  el de mantener inventario (fórmula de Wilson), que además usaría el flete que
  ya está en los datos.
- **Presupuesto global.** Cada pieza se optimiza por separado. Con un
  presupuesto compartido el problema pasa a ser una mochila y habría que
  priorizar por criticidad, lo cual es más realista y más vistoso en la demo.
- **Intervalos del modelo.** El modelo da un valor puntual; los cuartiles
  vienen de la parte estadística. Una regresión cuantílica daría intervalos
  propios y un stock de seguridad mejor fundado.
- **Consolidación de órdenes.** Hoy cada pieza genera su orden y paga su flete.
  Agrupar por proveedor ahorraría dinero real y es una restricción natural del
  MILP.

### 11.3 Lo que no se está teniendo en cuenta

Esto es lo que un revisor externo preguntaría y hoy no tiene respuesta.

**No hay autenticación, y ya no es teórico.** `updated_by` es texto libre que
manda el navegador, así que el `audit_log` registra lo que el cliente diga que
es. Durante el rediseño de la interfaz, un clic automatizado de verificación
aprobó `MRO-20033 / NAVA` y quedó firmado como «comprador»: la traza no
distingue una decisión humana de un accidente de una prueba. Con el despliegue
en Amplify la API queda además tras un endpoint público de API Gateway con
`AllowOrigins: *` y `authorization-type NONE`, de modo que `POST
/recommendations/state` lo alcanza cualquiera que conozca la URL.

**Las aprobaciones no sobreviven a la noche.** `approvals.db` vive en
`app/data/state/`, el `Dockerfile` hace `COPY app ./app` y el archivo no está en
`.dockerignore`: la base se hornea en la imagen. El almacenamiento de Fargate es
efímero y el autoescalado programado apaga el servicio a las 23:00 UTC de lunes
a viernes (`MinCapacity=0`). Cada mañana el sistema arranca con las aprobaciones
que hubiera en la máquina de compilación y el historial de auditoría vacío. Para
un producto cuyo argumento es la trazabilidad, es el fallo más grave que queda.

**El dataset es sintético en sus campos críticos.** Vida útil, stock actual,
MOQ, capacidad y flete no vienen de ningún sistema real: los generó el build con
semilla fija. Las decisiones del optimizador son correctas *dado ese dato*, pero
no son decisiones de compra reales. Conviene decirlo explícitamente en la demo
para que nadie confunda el ejercicio con una recomendación operativa.

**El lead time asume que el pasado se repite.** Se calcula de órdenes
históricas y no contempla aduanas, cierres de planta ni estacionalidad del
proveedor. Con σ/μ ≈ 0,53 la variabilidad ya es alta; un evento excepcional la
rompe.

**~~No hay costo de quiebre.~~** ✅ Resuelto. `stockout_cost_usd` entra en la
función objetivo y la mochila maximiza el beneficio neto. Queda un matiz: el
costo de quiebre se deriva de la criticidad con un parámetro fijo, no de lo que
cuesta de verdad parar una línea en Nava o en Obregón. Esa cifra la tiene
operaciones y cambiaría el orden de prioridades.

**El horizonte es de un mes.** El sistema decide como si cada mes fuera
independiente. No hay noción de que comprar hoy afecta la decisión del mes
siguiente, ni de trayectoria de inventario.

**No se modela el traslado entre plantas, y los datos dicen que importa.** Si
Nava tiene exceso de una pieza y Obregón está por debajo del mínimo, la
respuesta correcta puede ser mover stock, no comprar. El sistema nunca considera
esa opción. Contando sobre el dataset actual hay **11 piezas** en esa situación,
por unos 2.860 USD de compra —más que el presupuesto entero de la corrida—, y
una de ellas, `MRO-90011`, está aplazada por falta de presupuesto mientras
Obregón tiene ocho unidades sobre su mínimo. Un traslado paga flete pero no
precio de compra, así que bajo restricción de presupuesto es estrictamente más
barato que comprar. Ver §11.6.

**Una sola moneda y sin impuestos.** Todo está en USD sin IVA, aranceles ni tipo
de cambio, con proveedores mexicanos. En una compra real eso cambia el ranking
de proveedores.

**No hay pruebas de carga ni de concurrencia.** SQLite con varios compradores
aprobando a la vez no se ha probado. Para un MVP de un usuario está bien; con
diez, hay que revisarlo.

**El pipeline es manual y sin orquestación.** Son cinco comandos en orden y
nada impide correrlos mal. Si alguien entrena el modelo sin regenerar el
dataset, el sistema no avisa.

**No hay versionado del dataset.** Las recomendaciones no guardan contra qué
versión de datos se generaron. Si mañana cambian los datos, no hay forma de
reconstruir por qué se recomendó lo de hoy.

### 11.4 Las cinco mejoras propuestas

Ordenadas por lo que impide hoy, no por lo que sería vistoso.

**1 · Autenticación, y `updated_by` desde el token.** Un autorizador de Cognito
en API Gateway y el usuario tomado del JWT, nunca del cuerpo de la petición.
Sin esto el `audit_log` no prueba nada —lo firmó un clic de prueba durante el
desarrollo— y el endpoint de escritura queda abierto al publicar en Amplify.
Bloquea enseñárselo a un cliente. *Esfuerzo: medio.*

**2 · Sacar las aprobaciones de la imagen.** DynamoDB encaja: la clave es
`sku_id + city_id`, el volumen es de decenas de filas y no hay que administrar
nada. Mientras tanto, `app/data/state/` debería estar en `.dockerignore` para
que al menos no se publique una base con decisiones de la máquina de
compilación. Hoy el apagado nocturno borra cada día las aprobaciones y la
auditoría. *Esfuerzo: medio.*

**3 · Identificador de corrida en cada decisión.** Un `run_id` con el hash de
las entradas, el presupuesto y la fecha, guardado en la recomendación y en la
aprobación. Antes era higiene; con la mochila es necesario: una fila está
`APLAZADO` por lo que consumieron *las demás*, así que sin saber contra qué
corrida se decidió, el motivo no se puede reconstruir. *Esfuerzo: bajo.*

**4 · Cerrar el bucle de feedback (§9).** Sigue sin existir y es la mitad del
valor. Ahora hay un punto de enganche que antes no existía: en los casos
`REVISAR` la interfaz muestra una recomendación explícita del sistema, así que
cada decisión del comprador es un ejemplo etiquetado —coincide o la corrige— sin
pedirle nada extra. De ahí sale el ratio de cumplimiento de §9.2 casi gratis.
*Esfuerzo: alto.*

**5 · Traslado entre plantas antes de comprar.** Añadir el movimiento de stock
como variable del optimizador, con su flete y su tiempo de tránsito, y
resolverlo antes que la compra. Con presupuesto restringido siempre es más
barato mover que comprar. Sobre el dataset actual habría 11 candidatos y
cerraría al menos una reposición aplazada. Advertencia honesta: el excedente
medido es *stock por encima del mínimo*, así que moverlo entero dejaría a la
planta de origen sin colchón; el modelo tiene que respetar el mínimo de las dos.
*Esfuerzo: medio-alto.*

### 11.5 Orden sugerido

1. Configurar `GEMINI_API_KEY` y `MLFLOW_TRACKING_URI` — desbloquea lo ya escrito.
2. Sacar `approvals.db` de la imagen: hoy el sistema pierde su auditoría cada noche.
3. Autenticación antes de publicar en Amplify.
4. `run_id` en cada decisión — es barato y sin él la mochila no es reconstruible.
5. Feedback loop (§9): es lo que convierte el MVP en un sistema que aprende.
6. Traslado entre plantas: el ahorro está medido y supera el presupuesto de la corrida.
7. Variables externas en el modelo: la única vía para que el forecast mejore.

La demo sigue necesitando decir qué dato es sintético y cuál real. La interfaz
ya lo marca por su cuenta (§Etapa 6), pero conviene abrirlo en voz alta.

### 11.6 Deuda técnica registrada

- **Flag de validación global, no por fila** — el spec pide un flag por
  pieza/proveedor/ciudad; hoy la validación es todo o nada.
- **`app/data/__init__,py`** — archivo con coma en vez de punto, remanente del
  scaffold. Inofensivo, conviene borrarlo.
- **Token de GitLab expuesto** — el comando de instalación del SDK lleva el
  deploy token en la URL y quedó en el historial de la conversación. Conviene
  rotarlo.
- **Token de GitHub expuesto** — el remote `origin` sigue con un Personal Access
  Token en texto plano. **Debe revocarse.**
- **`requires-python`** decía 3.12 y el entorno corre 3.10; ya corregido.

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