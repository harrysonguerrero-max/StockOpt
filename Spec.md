# Spec — MVP de optimización de inventario con IA

> **Si eres un agente y necesitas entender qué hace el sistema, empieza por
> [§13 · Formulación matemática del sistema](#13-formulación-matemática-del-sistema).**
> Documenta el modelo formal que el código implementa *hoy* —cada fórmula con el
> glosario de sus símbolos y unidades—, el mapa fórmula → archivo → función
> (§13.11), el inventario de supuestos y sus límites (§13.12) y el diagnóstico
> del dato de entrada (§13.13). Las secciones 1 a 12 son el spec original de
> producto: describen lo que se quería construir, no siempre lo que quedó.

---

## 0. Estado actual de la implementación

**Última actualización:** 2026-08-20

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
| **3.c · Continuidad como restricción dura (§14)** | ✅ | `allocate_budget` en `app/core/optimization.py` |
| **3.d · Lote económico (EOQ) para las cotas** | ✅ | `replenishment_level` en `app/core/optimization.py` |
| 4 · Reglas de negocio | ✅ | dentro del optimizador |
| 5 · Explicación con LLM | ✅ código listo, ⏸️ sin clave | `app/services/llm_agent.py` |
| 6 · Interfaz | ✅ reescrita | `app/api/` + `frontend/` |
| **6.b · Recorrido del pipeline y explorador de datos** | ✅ | `app/services/pipeline_report.py`, `data_views.py` |
| **6.c · Fórmulas y teoría por etapa en la interfaz** | ✅ | `frontend/js/formulas.js` |
| **6.d · Clasificación Criticidad-Valor-Rotación** | ✅ | `app/core/classification.py`, `frontend/js/clasificacion.js` |
| 9 · Feedback y reentrenamiento | ⬜ | — |

**303 tests** en `tests/core/`.

### Lo que cambió desde la versión anterior de este documento

**La continuidad de producción dejó de ser una idea y es una restricción dura.**
El diseño de §14 está implementado: las reposiciones de criticidad A se financian
antes de que compita nada discrecional, el presupuesto se vuelve elástico hasta un
excedente autorizado (`BUDGET_OVERRUN_MAX_USD = 1 500`) para conseguirlo, y lo que no
cabe ni así sale con un quinto estado, `ESCALAR`, en vez de aplazarse en silencio.
Sobre esa base se imponen pisos de servicio por clase (`SERVICE_FLOOR_BY_CRITICALITY`:
A 1,00 · B 0,80 · C 0,50) que se sueltan de menos exigente a más exigente cuando el
dinero no llega, y el nivel realmente alcanzado se publica junto al declarado.

**Las cotas de inventario ya no son constantes de cobertura.** `Imax` y `Itgt` salen
de la cantidad económica de pedido de Wilson, que equilibra el flete contra el costo
de mantener. Con eso desaparecen los `3,0` y `1,5` meses fijados a dedo que §13.5
señalaba como no derivados, y entran tres columnas nuevas —`order_cost_usd`,
`holding_cost_usd`, `eoq_units`— que hacen la cifra auditable.

**La interfaz declara la teoría de cada paso.** Cada etapa del recorrido publica sus
fórmulas en MathML con el glosario de todos sus símbolos, su unidad y la referencia
bibliográfica de la que sale. Los valores de los parámetros llegan del informe, que
los lee del código, de modo que pantalla y código no puedan discrepar.

**La pantalla está en inglés** y el producto pasó a llamarse *MRO Spare Parts
Optimizer*. Los códigos internos —`COMPRAR`, `Estable`, `Pendiente aprobacion`— siguen
en español porque viajan en los CSV y en la base de aprobaciones; se traducen en la
capa de presentación.


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

### El pipeline y la fórmula de cada paso

Referencia rápida para presentación. Cada fórmula está desarrollada con su
glosario completo de símbolos en §13; aquí va la declaración y el enlace.

| # | Paso | Qué decide | Fórmula que aplica | Detalle |
|---|---|---|---|---|
| **0** | Perfilado y limpieza | Qué filas entran | Atípicos por doble criterio: `IQR: [Q1 − 1,5·RIC , Q3 + 1,5·RIC]` y `MAD: |x − mediana| / (1,4826·MAD) > 3` | §Etapa 0 |
| **1** | Ingesta y validación | Integridad del dataset | Reglas duras: `precio ≥ 0`, `MOQ ≥ 1`, `lead_time > 0`, `cantidad ≥ 0`, `∀ pieza: |ofertas| ≥ 2` | §1.1 |
| **1.3** | Clasificación de patrón | Qué método usar | Fuerza estacional `F_s = 1 − Var(R)/Var(S+R)` · Kruskal-Wallis `p_est` · Kendall `tau` · `CV = sigma/mu`. Precedencia: `Insuf → Estacional → Tendencia → Volátil → Estable` | [§13.1](#131-etapa-13--clasificación-de-patrones-de-demanda) |
| **1.3** | Confianza del patrón | Si necesita humano | `gamma = 0,30·V(n) + 0,45·W(CV) + 0,25·R(y)` | [§13.1.6](#1316-score-de-confianza-del-patrón) |
| **2** | Proyección de demanda | Cuánto se va a consumir | Uno de cuatro según patrón:<br>· Estable → `D50 = (1/6)·Σ y[t]`<br>· Volátil → `D50 = P50(ventana)`<br>· Tendencia → `D50 = a·n + b` (OLS)<br>· Estacional → `D50 = l[n] + s[n−11]` (Holt-Winters) | [§13.2.1](#1321-los-cuatro-estimadores) |
| **2** | Intervalo | Rango plausible | `D25/D75 = max(0, D50 ∓ 0,674·S)` | [§13.2.2](#1322-construcción-del-intervalo) |
| **2** | Validación del método | Si el método sirve | `WMAPE = Σ|e_j| / Σ y_j` con origen móvil, 6 meses reservados | [§13.2.3](#1323-validación-retrospectiva-wmape-con-origen-móvil) |
| **2.b** | Modelo ML | Corrección del punto central | `g* = argmin Σ (y − g(X))²`, gradient boosting sobre rezagos 1/2/3/6/12 + ventanas + mes cíclico + atributos | [§13.3.2](#1332-estimador-y-objetivo) |
| **2.b** | Combinación | Proyección final | `D50_final = 0,5·M + 0,5·D50` (Bates & Granger, 1969) | [§13.3.4](#1334-combinación-con-la-proyección-estadística) |
| **3** | **Inventario mínimo** | **Cuándo reponer** | `Imin = ceil( d·L + z(k)·sqrt( L·sigma_d² + d²·sigma_L² ) )` | [§13.4](#134-etapa-23--política-de-inventario-el-inventario-mínimo) |
| **3** | **Lote económico** | Cuánto pedir de una vez | `Q* = sqrt( 2·K·D / h )` con `h = i·c` | [§13.5](#135-etapa-3--niveles-derivados-y-cotas) |
| **3** | Nivel de reposición | Techo y objetivo, que son el mismo | `S = Imin + Q` · `Imax = Itgt = S` | [§13.5](#135-etapa-3--niveles-derivados-y-cotas) |
| **3** | Tope por vida útil | Antiobsolescencia | `Ivida = max( 0 , floor( d·0,80·V ) − q )` | [§13.5](#135-etapa-3--niveles-derivados-y-cotas) |
| **3** | Selección de proveedor | A quién comprar | `min Σ (p_o·x_o + f_o·u_o)` s.a. cobertura, techo, `Σu ≤ 1`, `x_o ≥ m_o·u_o`, `x_o ≤ U_o·u_o` | [§13.6](#136-etapa-3--milp-de-selección-de-proveedor) |
| **3.b** | Costo de quiebre | Cuánto vale no tenerla | `Cq = dias_expuestos · r · c_dia(k)` | [§13.7](#137-etapa-3b--valoración-del-quiebre) |
| **3.b** | Reparto de presupuesto | Qué se financia | `max Σ_flex b_s·v_s` s.a. `v_s = 1 ∀ s crítico`, `Σ Ctot_s·v_s ≤ B + E`, `E ≤ E_max` | [§13.8](#138-etapa-3b--mochila-de-presupuesto) |
| **3.b** | Piso de servicio | Coherencia con los `z` | `Σ_{Clase_k} v_s ≥ ceil( θ_k·|Clase_k| )` | [§13.8](#138-etapa-3b--mochila-de-presupuesto) |
| **4** | Decisión final | ESCALAR / REVISAR / COMPRAR / APLAZADO / NO_COMPRAR | Árbol de 8 reglas en orden estricto | [§13.9](#139-árbol-de-decisión-completo) |

**Las tres fórmulas que hay que saber defender en una presentación:**

```
1)  Imin = ceil( d·L  +  z(k)·sqrt( L·sigma_d²  +  d²·sigma_L² ) )
             └──┬──┘     └──────────────┬──────────────────────┘
          lo que consumo         colchón que absorbe que la demanda
          mientras espero        suba Y que el proveedor se retrase

2)  Q* = sqrt( 2·K·D / h )   con  h = i·c      ← flete contra costo de mantener
    S  = Imin + Q*                             ← hasta aquí se repone, y este
                                                  es también el techo de la pieza

3)  min Σ_o ( p_o·x_o  +  f_o·u_o )      ← precio por unidad + flete por activar
        con  x_o ≥ m_o·u_o                 ← el MOQ solo aplica si le compro

4)  max Σ_flex ( Cq_s − Ctot_s )·v_s     ← beneficio neto de lo discrecional
        s.a. v_s = 1   ∀ s de criticidad A ← lo que para una línea no compite
             Σ_s Ctot_s·v_s ≤ B + E        ← presupuesto elástico
             E ≤ E_max                     ← con el excedente acotado y visible
```

| Símbolo | Qué es | Unidad |
|---|---|---|
| `d` | Demanda media diaria proyectada | unidades/día |
| `L` | Plazo de entrega medio | días (≈ 10,6) |
| `sigma_d` | Desviación de la demanda diaria | unidades/día |
| `sigma_L` | Desviación del plazo de entrega | días (≈ 5,45) |
| `z(k)` | Factor de servicio por criticidad | A = 1,65 (95 %) · B = 1,28 (90 %) · C = 0,84 (80 %) |
| `p_o`, `f_o`, `m_o` | Precio unitario, flete fijo y MOQ de la oferta | USD/u, USD, unidades |
| `x_o`, `u_o` | Cantidad a comprar y binaria de activación | unidades enteras, 0/1 |
| `Cq_s` | Costo del quiebre que se evita | USD |
| `Ctot_s` | Costo total de la reposición | USD |
| `v_s` | Si la compra se financia esta corrida | 0/1 |
| `K`, `D`, `h`, `i`, `c` | Flete por pedido, demanda anual, costo de mantener, tasa anual de posesión y valor unitario | USD/pedido, u/año, USD/u/año, fracción, USD/u |
| `B`, `E`, `E_max` | Presupuesto nominal, excedente consumido y excedente máximo autorizado | USD (hoy 2 500 y 1 500) |
| `θ_k` | Fracción mínima de la clase `k` que debe financiarse | A 1,00 · B 0,80 · C 0,50 |

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
| COMPRAR | 5 · 3.725,16 USD · 201 unidades |
| REVISAR | 3 |
| **APLAZADO** | 7 · 5.169,89 USD sin financiar |
| **ESCALAR** | 0 |
| NO_COMPRAR | 25 |

Presupuesto nominal: **2.500 USD**, más **1.225,16 USD** de los 1.500 USD de
excedente autorizado. Es lo que costó no dejar sin reponer ninguna pieza de
criticidad A. Evita 10.090 USD de quiebre, un retorno de 2,7×, y deja 9.387,86
USD de riesgo sin cubrir en las siete reposiciones aplazadas.

Nivel de servicio alcanzado frente al declarado: **A 5/5 (100 % contra un piso
de 100 %)** · B 0/6 (0 % contra 80 %) · C 0/1 (0 % contra 50 %). Los dos pisos
discrecionales se soltaron porque el dinero no llegaba, y la pantalla lo dice.

**Cómo se lee el cambio frente a la corrida anterior.** Hay menos compras y más
aplazadas, y las dos cosas tienen la misma causa: el lote económico pide más
unidades por pedido que la cobertura de mes y medio que había antes, así que cada
compra cuesta más y caben menos en la corrida. A cambio se paga menos flete al
año y ninguna pieza crítica queda esperando dinero.

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
| 4.b | ~~Derivar el inventario máximo de un costo~~ | — | ✅ **Hecho.** Cantidad económica de pedido en §13.5.1 |
| 4.c | ~~Continuidad de producción como restricción dura~~ | — | ✅ **Hecho.** §13.8, con estado `ESCALAR` |
| 4.d | **Validar `i_h` y `c_dia(k)` con mantenimiento y finanzas** | bajo | Son los dos parámetros que más mueven la decisión y ninguno está medido |
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

**6 · ~~Invertir la jerarquía: continuidad de producción primero, presupuesto
después.~~** ✅ **Hecho el 2026-08-20.** Ver
[§13.8](#138-etapa-3b--reparto-con-la-continuidad-como-restricción-dura) para la
formulación y [§14](#14-diseño--continuidad-de-producción-como-restricción-dura)
para el registro de por qué se hizo.

**7 · Chat con LLM sobre el estado del sistema.** Ver
[§15](#15-diseño--chat-de-explicabilidad-y-trazabilidad). *Esfuerzo: medio.*

### 11.5 Orden sugerido

1. Configurar `GEMINI_API_KEY` y `MLFLOW_TRACKING_URI` — desbloquea lo ya escrito.
2. Sacar `approvals.db` de la imagen: hoy el sistema pierde su auditoría cada noche.
3. Autenticación antes de publicar en Amplify.
4. `run_id` en cada decisión — es barato y sin él el reparto no es reconstruible.
4.b Validar con negocio `i_h` (25 %) y `c_dia(k)` (400/80/10): son los dos números
   que más mueven la decisión y hoy ninguno está medido sobre esta operación.
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
---

## 13. Formulación matemática del sistema

Esta sección documenta el **modelo formal que el código implementa hoy**, no el
que se pretendía implementar. Cada fórmula lleva debajo el glosario de todos sus
símbolos con sus unidades, y al final hay un mapa fórmula → archivo → función
para que un agente pueda ir del planteamiento al código sin leerlo entero.

Notación en ASCII (`sigma`, `sqrt`, `sum`) porque el documento se lee tanto en
terminal como en navegador.

### 13.0 Notación, conjuntos e índices

```
i  in  I     piezas (SKU)                      |I| = 20
c  in  C     ciudades                          |C| = 2   (NAVA, OBRE)
s  =  (i,c)  serie pieza-ciudad                |S| = 40
t  in  T     periodos mensuales                |T| = 72  (2020-02 .. 2026-01)
o  in  O(s)  ofertas aplicables a la serie s   |O(s)| in {2,3}
```

| Símbolo | Qué es | Unidad | Origen |
|---|---|---|---|
| `y[s,t]` | Demanda observada de la serie `s` en el mes `t` (`qty_issued`) | unidades | `demand_history.csv` |
| `n[s]` | Número de meses observados de la serie `s` | conteo | Derivado |
| `q[s]` | Existencias actuales (`on_hand_qty`) | unidades | `inventory_current.csv` |
| `k[i]` | Criticidad de la pieza: A, B o C | categoría | `parts_master.csv` |
| `V[i]` | Vida útil de la pieza (`shelf_life_days`) | días | `parts_master.csv` |
| `p[o]` | Precio unitario de la oferta `o` | USD/unidad | `supplier_offers.csv` |
| `f[o]` | Costo fijo de flete de la oferta `o` | USD | `supplier_offers.csv` |
| `m[o]` | Cantidad mínima de orden (MOQ) de la oferta `o` | unidades | `supplier_offers.csv` |
| `K[o]` | Capacidad mensual de la oferta `o` | unidades/mes | `supplier_offers.csv` |
| `B` | Presupuesto de la corrida (`SCENARIO_BUDGET_USD`) | USD | Parámetro, hoy 2 500 |

**Supuesto estructural del sistema entero:** el horizonte de decisión es de **un
periodo** (`PLANNING_PERIOD_DAYS = 30`). No existe variable de estado que enlace
la decisión de este mes con la del siguiente; cada corrida resuelve un problema
estático. Es una simplificación deliberada frente a la formulación dinámica de
Scarf (1960), y es la limitación teórica más importante del modelo actual.

---

### 13.1 Etapa 1.3 — Clasificación de patrones de demanda

Función `phi: R^n -> {Insuficiente, Estacional, Tendencia, Volatil, Estable}`,
evaluada por reglas en orden estricto de precedencia.

#### 13.1.1 Estadísticos descriptivos

```
mu[s]    = (1/n) * sum_t  y[s,t]

sigma[s] = sqrt( (1/n) * sum_t ( y[s,t] - mu[s] )^2 )          [ddof = 0]

CV[s]    = sigma[s] / mu[s]        si mu[s] > 0,  else 0

z0[s]    = (1/n) * sum_t  1{ y[s,t] = 0 }
```

| Símbolo | Qué es | Unidad | Nota |
|---|---|---|---|
| `mu[s]` | Demanda media mensual de la serie | unidades/mes | — |
| `sigma[s]` | Desviación estándar poblacional (`ddof=0`, no muestral) | unidades/mes | Elección deliberada: la serie se trata como población, no como muestra |
| `CV[s]` | Coeficiente de variación | adimensional | Criterio de volatilidad |
| `z0[s]` | Proporción de meses con demanda cero | fracción 0–1 | Diagnóstico de intermitencia |
| `1{·}` | Función indicadora: 1 si la condición se cumple, 0 si no | — | — |

#### 13.1.2 Fuerza estacional

Descomposición aditiva clásica por medias móviles
(`statsmodels.seasonal_decompose`, periodo 12):

```
y[s,t] = T[s,t] + S[s,t] + R[s,t]

F_s[s] = clip( 1 - Var(R) / Var(S + R) ,  0 , 1 )
```

| Símbolo | Qué es | Unidad | Nota |
|---|---|---|---|
| `T[s,t]` | Componente de tendencia | unidades | Media móvil centrada de orden 12 |
| `S[s,t]` | Componente estacional | unidades | Promedio de residuos por posición del ciclo |
| `R[s,t]` | Residuo | unidades | Lo no explicado por tendencia ni estación |
| `F_s[s]` | Fuerza estacional | adimensional 0–1 | Fracción de la varianza no-tendencial atribuible al ciclo |
| `Var(·)` | Varianza sobre los índices donde el residuo no es NaN | unidades² | Los extremos se pierden por la media móvil |
| `clip(x,a,b)` | Recorte al intervalo `[a,b]` | — | — |

`F_s` devuelve 0 si `n < 24` o si la serie es constante.

#### 13.1.3 Contraste de efecto de mes (Kruskal-Wallis)

Se agrupan las observaciones por posición dentro del ciclo anual —los 12 grupos
`G_j = { y[s,t] : t ≡ j (mod 12) }`— y se contrasta:

```
H0 :  todos los G_j provienen de la misma distribución
H1 :  al menos un mes difiere

p_est[s] = p-valor del estadístico H de Kruskal-Wallis
```

| Símbolo | Qué es | Unidad | Nota |
|---|---|---|---|
| `G_j` | Observaciones del mes `j` del ciclo | unidades | 12 grupos, ~6 observaciones cada uno con 72 meses |
| `p_est[s]` | p-valor del contraste | fracción 0–1 | Devuelve 1.0 si `n < 24`, si `sigma = 0`, o si quedan menos de 3 grupos con ≥2 observaciones |

**Por qué no-paramétrico:** la demanda de refacciones es un conteo sesgado a la
derecha; ANOVA supondría normalidad y homocedasticidad que la serie no cumple.

#### 13.1.4 Contraste de tendencia (Mann-Kendall vía tau de Kendall)

```
tau[s]   = tau_b( (1,2,...,n) , (y[s,1],...,y[s,n]) )

p_ten[s] = p-valor asociado a tau
```

| Símbolo | Qué es | Unidad | Nota |
|---|---|---|---|
| `tau[s]` | Tau-b de Kendall entre el orden temporal y la serie | adimensional −1…1 | Positivo = crecimiento monótono; es el estadístico de Mann-Kendall |
| `p_ten[s]` | p-valor del contraste de tendencia | fracción 0–1 | Devuelve `(0, 1)` si `n < 3` o `sigma = 0` |

**Por qué tau y no la pendiente OLS:** tau mide monotonía por concordancia de
pares, sin suponer linealidad ni normalidad de los residuos.

#### 13.1.5 Regla de decisión (precedencia estricta)

```
phi[s] =
    Insuficiente   si  n[s] < 6   or   mu[s] = 0
    Estacional     si  F_s[s] >= 0.45   and   p_est[s] < 0.05
    Tendencia      si  p_ten[s] < 0.05
    Volatil        si  CV[s] > 0.50
    Estable        en otro caso
```

| Umbral | Valor | Constante | Justificación |
|---|---|---|---|
| Mínimo de periodos | 6 | `MIN_PERIODS` | Debajo no hay estadística |
| Fuerza estacional | 0,45 | `SEASONAL_STRENGTH_MIN` | Calibrado: con 3 ciclos, `seasonal_decompose` extrae fuerza 0,32 media incluso de ruido puro |
| Significancia estacional | 0,05 | `SEASONAL_PVALUE_MAX` | La doble condición baja el falso positivo del 26 % al 2 % |
| Significancia de tendencia | 0,05 | `TREND_PVALUE_MAX` | Convencional |
| Umbral de volatilidad | 0,50 | `CV_VOLATILE` | Convencional en gestión de inventarios |

**La precedencia no es cosmética.** Una serie estacional tiene `CV` alto por
construcción; si *Volátil* se evaluara antes, ninguna estacionalidad se
detectaría nunca. El orden pone los patrones explicables por delante del cajón
de sastre.

#### 13.1.6 Score de confianza del patrón

Combinación lineal convexa de tres factores escalonados:

```
gamma[s] = 0.30 * V(n)  +  0.45 * W(CV)  +  0.25 * R(y)
```

con

```
V(n)  = 0.20 si n < 6 ;  0.55 si n < 12 ;  0.80 si n < 24 ;  1.00 en otro caso

W(CV) = 1.00 si CV <= 0.25 ;  0.80 si CV <= 0.50 ;  0.50 si CV <= 1.00 ;  0.25 en otro caso

R(y)  = clip( 1 - | mean(y_ultimos3) - mean(y_resto) | / mean(y_resto) , 0 , 1 )
```

| Símbolo | Qué es | Unidad | Peso |
|---|---|---|---|
| `gamma[s]` | Confianza del patrón, previa a validar el método | fracción 0–1 | — |
| `V(n)` | Factor de volumen de historia | fracción 0–1 | 0,30 |
| `W(CV)` | Factor de volatilidad | fracción 0–1 | **0,45** — el mayor, porque la dispersión es lo que más degrada el pronóstico |
| `R(y)` | Estabilidad reciente: penaliza si los últimos 3 meses se despegan del histórico | fracción 0–1 | 0,25 |

Si `phi[s] = Insuficiente`, se fuerza `gamma[s] = 0`.

---

### 13.2 Etapa 2 — Proyección de demanda

El sistema **no aplica un solo estimador**: enruta cada serie a uno distinto
según su patrón. Formalmente es un **modelo por regímenes** con la clasificación
de §13.1 como función de asignación.

#### 13.2.1 Los cuatro estimadores

Sea `w = 6` (`MOVING_WINDOW`) la ventana reciente y `Y[s] = (y[s,n-w+1],...,y[s,n])`.

**Estable — media móvil:**
```
D50[s] = (1/w) * sum_{t=n-w+1}^{n}  y[s,t]

S[s]   = sqrt( (1/w) * sum_t ( y[s,t] - D50[s] )^2 )
```

**Volátil — percentiles empíricos:**
```
D25[s] = P25( Y[s] )      D50[s] = P50( Y[s] )      D75[s] = P75( Y[s] )
```

**Tendencia — mínimos cuadrados sobre toda la historia:**
```
(a, b) = argmin_{a,b}  sum_{t=1}^{n} ( y[s,t] - (a*t + b) )^2

D50[s] = a * n + b

S[s]   = sqrt( (1/n) * sum_t ( y[s,t] - (a*t + b) )^2 )
```

**Estacional — Holt-Winters aditivo sin tendencia, periodo 12:**
```
Nivel:       l[t] = alpha * ( y[t] - s[t-12] )  +  (1 - alpha) * l[t-1]
Estación:    s[t] = delta * ( y[t] - l[t] )     +  (1 - delta) * s[t-12]
Proyección:  D50[s] = l[n] + s[n-11]

S[s] = sqrt( (1/n) * sum_t ( y[s,t] - yhat[s,t] )^2 )      [residuos del ajuste]
```

| Símbolo | Qué es | Unidad | Origen |
|---|---|---|---|
| `D50[s]` | Proyección central de demanda mensual | unidades/mes | Salida `forecast_q50` |
| `S[s]` | Dispersión asociada al método | unidades/mes | Ventana, residuos OLS o residuos del ajuste, según método |
| `a`, `b` | Pendiente e intercepto de la recta | unidades/mes², unidades/mes | `np.polyfit` grado 1 |
| `alpha`, `delta` | Constantes de suavizado de nivel y estación | adimensional 0–1 | Estimadas por máxima verosimilitud (`.fit()`) |
| `l[t]`, `s[t]` | Componentes de nivel y estación | unidades | Recursivos |

**Salvaguardas:** si `n < 24` o Holt-Winters no converge (`ValueError` o
`LinAlgError`), la serie cae al estimador *Estable*. Si `phi[s] = Insuficiente`
se devuelve `(0,0,0)` y la decisión pasa al comprador.

#### 13.2.2 Construcción del intervalo

Salvo en el método volátil (que ya devuelve percentiles empíricos):

```
D25[s] = max( 0 ,  D50[s] - 0.674 * S[s] )
D75[s] = max( 0 ,  D50[s] + 0.674 * S[s] )
```

| Símbolo | Qué es | Unidad | Nota |
|---|---|---|---|
| `0.674` | Cuantil 0,75 de la normal estándar, `Phi^{-1}(0.75)` | adimensional | `QUANTILE_Z`. Define el rango intercuartílico bajo normalidad |
| `max(0, ·)` | Recorte en cero | — | Una demanda negativa no tiene sentido operativo |

**Limitación teórica declarada:** el intervalo asume **simetría normal**. Con
`CV > 0,5` la normal asigna masa a valores negativos y subestima la cola derecha;
el recorte mitiga lo primero, no lo segundo.

#### 13.2.3 Validación retrospectiva (WMAPE con origen móvil)

Se reservan los últimos `h = 6` meses (`BACKTEST_MONTHS`) y se re-proyecta cada
uno usando **solo** información anterior:

```
Para j = 0..h-1:
    tau_j = n - h + j
    e_j   = | y[s, tau_j]  -  D50( y[s, 1..tau_j-1] , phi[s] ) |

WMAPE[s] = ( sum_j e_j ) / ( sum_j y[s, tau_j] )
```

| Símbolo | Qué es | Unidad | Nota |
|---|---|---|---|
| `h` | Meses reservados para prueba | conteo | 6 |
| `tau_j` | Índice del mes evaluado | — | Origen móvil: el corte avanza mes a mes |
| `e_j` | Error absoluto del mes `j` | unidades | — |
| `WMAPE[s]` | Error porcentual **ponderado sobre el total** | fracción | NaN si `n < h + 24` o si el total real es 0 |

**Por qué WMAPE y no MAPE.** El MAPE clásico `(1/h)*sum|e_j/y_j|` diverge cuando
`y_j = 0`. La demanda de refacciones tiene meses en cero por definición: el MAPE
sería infinito, o habría que descartar justo las observaciones más informativas.
WMAPE pone el total en el denominador **una sola vez** y admite ceros
individuales.

#### 13.2.4 Ajuste de confianza por error medido

```
gamma_final[s] = clip( gamma[s] * psi(WMAPE[s]) , 0 , 1 )

psi(w) =  0.65  si w > 0.50
          0.85  si 0.30 < w <= 0.50
          1.00  si w <= 0.30
          1.00  si w = NaN            [sin validación, no se penaliza]
```

| Símbolo | Qué es | Unidad |
|---|---|---|
| `gamma_final[s]` | Confianza final publicada (`confidence_final`) | fracción 0–1 |
| `psi(·)` | Factor de penalización por error demostrado | adimensional |

**Bandera de revisión humana:** `needs_review = 1` si `gamma_final < 0.5` o
`phi[s] = Insuficiente`.

---

### 13.3 Etapa 2.b — Modelo de aprendizaje automático

**Paradigma: modelo global.** Se ajusta **un único estimador** sobre las 40
series a la vez, no uno por serie. Con `n = 72` observaciones por serie, un
modelo independiente sobreajustaría; el modelo global comparte estructura entre
series, práctica estándar cuando hay muchas series cortas.

#### 13.3.1 Espacio de variables

```
X[s,t] = (  y[s,t-1], y[s,t-2], y[s,t-3], y[s,t-6], y[s,t-12],
            MM3[s,t], SD3[s,t], MM6[s,t], SD6[s,t],
            ev[s,t-1], br[s,t-1],
            sin(2*pi*mes/12), cos(2*pi*mes/12),
            rank(k[i]), coste[i], V[i], 1{c = NAVA}  )
```

| Grupo | Símbolo | Qué es | Unidad |
|---|---|---|---|
| Rezagos | `y[s,t-L]`, `L in {1,2,3,6,12}` | Demanda de `L` meses atrás de la misma serie | unidades |
| Ventanas | `MM_w[s,t]`, `SD_w[s,t]`, `w in {3,6}` | Media y desviación móvil, **desplazadas un mes** | unidades |
| Eventos | `ev[s,t-1]`, `br[s,t-1]` | Eventos de salida y de falla del mes anterior | conteo |
| Calendario | `sin`, `cos` del mes | Codificación cíclica del mes del año | adimensional |
| Atributos | `rank(k[i])` | Criticidad ordinal: A=3, B=2, C=1 | ordinal |
| Atributos | `coste[i]`, `V[i]` | Costo unitario y vida útil de la pieza | USD, días |
| Geografía | `1{c = NAVA}` | Indicadora de planta | 0/1 |

**Prevención de fuga de información.** Todas las ventanas móviles llevan
`.shift(1)` antes de calcularse, y rezagos y agregados se calculan **dentro** de
cada grupo `(sku_id, city_id)`, de modo que ninguna serie contamine a otra ni el
mes `t` vea información de `t`.

#### 13.3.2 Estimador y objetivo

```
g* = argmin_{g in G}   sum_{(s,t) in Train}  ( y[s,t] - g(X[s,t]) )^2

     G = ensamble aditivo de árboles con refuerzo de gradiente
         (HistGradientBoostingRegressor)

Predicción:  M[s] = max( 0 , g*( X[s, n] ) )
```

| Hiperparámetro | Valor | Papel |
|---|---|---|
| `max_iter` | 300 | Número de árboles del ensamble |
| `learning_rate` | 0,06 | Contracción de cada árbol |
| `max_depth` | 5 | Profundidad máxima — controla el orden de interacción |
| `min_samples_leaf` | 12 | Mínimo de observaciones por hoja |
| `l2_regularization` | 1,0 | Penalización L2 sobre los valores de hoja |
| `random_state` | 20260803 | Semilla fija — reproducibilidad |

#### 13.3.3 Partición temporal y métricas

La partición es **por fecha, nunca aleatoria**: los últimos 6 meses son
validación. Una partición aleatoria dejaría meses futuros en el entrenamiento y
produciría una métrica optimista insostenible en producción.

```
e[s,t] = g*(X[s,t]) - y[s,t]

MAE   = mean( |e| )
RMSE  = sqrt( mean( e^2 ) )
WMAPE = sum(|e|) / sum(y)
MAPE  = mean( |e| / y )                 solo sobre y > 0
sMAPE = mean( 2*|e| / ( |y| + |yhat| ) )
Sesgo = mean( e )
```

| Símbolo | Qué es | Unidad | Papel |
|---|---|---|---|
| `WMAPE` | Métrica de cabecera | fracción | Admite ceros; refleja impacto sobre inventario |
| `Sesgo` | Error medio **con signo** | unidades/mes | Debe oscilar en torno a 0. Un sesgo persistente consume el colchón de seguridad de forma estructural y **ninguna fórmula de stock lo corrige** |
| `MAPE` | Porcentual clásico | fracción | Solo informativo, sobre `y > 0` |

**Referencias de comparación obligatorias:**

```
Baseline ingenuo:   yhat[s,t] = y[s,t-1]
Baseline promedio:  yhat[s,t] = MM6[s,t]

Mejora_vs_ref = 1  -  WMAPE_modelo / WMAPE_ref
```

#### 13.3.4 Combinación con la proyección estadística

El modelo **no reemplaza** al estimador estadístico: se promedian.

```
D50_final[s] = lambda * M[s]  +  (1 - lambda) * D50[s]

Delta[s]     = D50_final[s] - D50[s]

D25_final[s] = max( 0 , D25[s] + Delta[s] )
D75_final[s] = max( 0 , D75[s] + Delta[s] )
```

| Símbolo | Qué es | Unidad | Valor |
|---|---|---|---|
| `lambda` | Peso asignado al modelo de ML (`MODEL_WEIGHT`) | adimensional 0–1 | **0,5** |
| `M[s]` | Proyección del modelo para la serie | unidades/mes | §13.3.2 |
| `Delta[s]` | Desplazamiento aplicado también a los cuantiles | unidades/mes | Mantiene el intervalo centrado |

**Fundamento teórico:** combinación de pronósticos (Bates & Granger, 1969).
Cuando dos estimadores tienen error de magnitud parecida y errores poco
correlacionados, la combinación tiene varianza menor que cualquiera de los dos.
`lambda = 0.5` es la combinación de varianza mínima bajo el supuesto de errores
de igual varianza e incorrelados — **no está optimizado sobre los datos**.

**Degradación limpia:** si no existe modelo entrenado, `M[s]` no está definido y
la serie conserva la proyección estadística intacta (`forecast_source =
"estadistico"`). El pipeline nunca depende del modelo para arrancar.

---

### 13.4 Etapa 2/3 — Política de inventario: el inventario mínimo

La pieza teórica más establecida del sistema: **punto de reorden con stock de
seguridad bajo demanda y plazo de entrega estocásticos**, formulación canónica de
Hadley & Whitin (1963) y Silver-Pyke-Peterson.

#### 13.4.1 Conversión a base diaria

```
d[s]       = D50_final[s] / 30

sigma_d[s] = sigma[s] / sqrt(30)
```

| Símbolo | Qué es | Unidad | Nota |
|---|---|---|---|
| `d[s]` | Demanda media **diaria** | unidades/día | La media se reparte linealmente |
| `sigma_d[s]` | Desviación estándar **diaria** | unidades/día | Escala con `sqrt(30)`: la varianza de una suma de 30 variaciones diarias independientes es 30 veces la diaria |
| `30` | Días por mes (`DAYS_PER_MONTH`) | días/mes | Constante de planificación, no calendario real |

**Advertencia de consistencia.** El `sigma[s]` que entra aquí es la desviación de
la **serie histórica completa**, no el RMSE del pronóstico. La teoría pide el
error de pronóstico; usar la dispersión de la serie sobreestima el colchón en
series con estacionalidad ya modelada, porque carga contra una variación que el
método ya anticipa.

#### 13.4.2 Varianza combinada y stock de seguridad

```
Var_L[s] = L * sigma_d[s]^2   +   d[s]^2 * sigma_L^2

SS[s]    = z(k[i]) * sqrt( max( Var_L[s] , 0 ) )
```

| Símbolo | Qué es | Unidad | Origen |
|---|---|---|---|
| `L` | Plazo de entrega medio de planificación | días | Media de `lead_time_avg_days` de proveedores activos ≈ 10,6 |
| `sigma_L` | Desviación estándar del plazo de entrega | días | Media de `lead_time_std_days` ≈ 5,45 |
| `Var_L[s]` | Varianza de la demanda acumulada durante el plazo | unidades² | — |
| `SS[s]` | Stock de seguridad | unidades | — |
| `z(k)` | Factor de seguridad según criticidad | adimensional | A = 1,65 · B = 1,28 · C = 0,84 (`Z_BY_CRITICALITY`) |

**Derivación (ley de la varianza total).** Si `L` es aleatorio e independiente de
la demanda:

```
Var(D_L) = E[ Var(D_L | L) ]  +  Var( E[D_L | L] )
         = E[ L * sigma_d^2 ]  +  Var( L * d )
         = L * sigma_d^2       +  d^2 * sigma_L^2
```

El primer término es la incertidumbre de la demanda; el segundo, la del
proveedor, **multiplicada por la demanda al cuadrado**. Con `sigma_L / L ≈ 0,53`
en estos proveedores, ambos términos son del mismo orden: la mitad del riesgo no
viene de la demanda sino del plazo.

**Nivel de servicio implícito de cada `z`:**

| Criticidad | `z` | Nivel de servicio de ciclo `alpha = Phi(z)` |
|---|---|---|
| A | 1,65 | ≈ 95 % |
| B | 1,28 | ≈ 90 % |
| C | 0,84 | ≈ 80 % |

Estos tres números son **la única declaración de política de servicio del
sistema**, y están fijados por constante, no derivados de un costo de faltante.
Ver §13.12 para la relación de dualidad que permitiría calibrarlos.

#### 13.4.3 Inventario mínimo

```
DL[s]   = d[s] * L                      demanda durante el plazo

Imin[s] = ceil( DL[s] + SS[s] )
```

| Símbolo | Qué es | Unidad | Nota |
|---|---|---|---|
| `DL[s]` | Demanda esperada durante el plazo (`demand_lead_time`) | unidades | No es colchón: es lo mínimo indispensable |
| `Imin[s]` | **Inventario mínimo / punto de reorden** (`inventory_min`) | unidades enteras | `ceil` porque las piezas se compran enteras |

**Limitación teórica declarada (Eppen & Martin, 1988).** La fórmula da la
varianza correcta, pero aplicar `z = Phi^{-1}(alpha)` sobre ella supone que la
demanda durante un plazo aleatorio es normal. En realidad es una **mezcla** de
distribuciones, sesgada a la derecha, así que el servicio real queda por debajo
del nominal. El sistema no corrige esto.

---

### 13.5 Etapa 3 — Lote económico, niveles derivados y cotas

El nivel hasta el que se repone ya no es una cobertura en meses fijada por
constante. Sale de la **cantidad económica de pedido**, formulación de Harris
(1913) popularizada por Wilson (1934), y su enlace con el punto de reorden es la
política `(s, S)` de Hadley & Whitin (1963).

#### 13.5.1 La cantidad económica

```
h[i]  = i_h * c[i]                         costo de mantener

D[s]  = D50_final[s] * 12                  demanda anual

Q*[s] = sqrt( 2 * K[s] * D[s] / h[i] )     fórmula de Wilson

Q[s]  = min( ceil(Q*[s]) , floor( D50_final[s] * 6.0 ) )
```

| Símbolo | Qué es | Unidad | Constante |
|---|---|---|---|
| `K[s]` | Costo fijo de traer un pedido: el flete medio de las ofertas aplicables | USD/pedido | `planning_order_cost` |
| `c[i]` | Valor unitario de la pieza en el maestro | USD/unidad | `unit_cost_usd` |
| `i_h` | Tasa anual de posesión: capital, bodega, seguro y riesgo de obsolescencia | fracción | `HOLDING_COST_RATE_ANNUAL = 0.25` |
| `h[i]` | Costo de mantener una unidad parada un año | USD/unidad/año | — |
| `D[s]` | Demanda anual proyectada | unidades/año | `MONTHS_PER_YEAR = 12` |
| `Q*[s]` | Cantidad que minimiza el costo anual de pedir más mantener | unidades | — |
| `Q[s]` | La misma, recortada por el tope de obsolescencia | unidades enteras | `EOQ_MAX_COVERAGE_MONTHS = 6.0` |

**De dónde sale la fórmula.** El costo anual total es `K·D/Q + h·Q/2`: el primer
término es lo que se paga en fletes al año, que cae al pedir lotes grandes; el
segundo es el costo de mantener el inventario medio, que sube. Derivando e
igualando a cero sale `Q* = sqrt(2KD/h)`. Es el único punto del sistema donde dos
costos con signos opuestos se equilibran de forma cerrada.

**Por qué el flete es el medio de las ofertas.** `K` debería ser el flete del
proveedor que finalmente gane, pero ese proveedor lo elige el MILP de §13.6, que
a su vez necesita la cantidad. Se rompe el círculo con el flete medio de las
ofertas aplicables. La aproximación es barata por la forma de la fórmula: el
flete entra bajo una raíz, así que equivocarse en el doble mueve `Q*` solo un
41 %, y el costo total todavía menos.

**Por qué el tope de cobertura.** Wilson no sabe que las piezas caducan. Una
pieza barata con flete caro puede pedir lotes de más de un año de consumo, que es
óptimo en costo y pésimo en obsolescencia. Recortarlo cuesta poco: la curva de
costo total es **plana alrededor del óptimo** (Silver, Pyke & Peterson, 1998), y
equivocarse en el doble del lote óptimo encarece el total solo un 25 %.

#### 13.5.2 Niveles y cotas

```
Itgt[s] = Imax[s] = S[s] = Imin[s] + Q[s]

Ivida[s] = max( 0 ,  floor( d[s] * 0.80 * V[i] )  -  q[s] )

Amax[s]  = min( Imax[s] - q[s] ,  Ivida[s] )

need[s]  = max( 0 ,  Imin[s] - q[s] )

des[s]   = max( 0 ,  min( Itgt[s] - q[s] ,  Amax[s] ) )
```

| Símbolo | Qué es | Unidad | Constante |
|---|---|---|---|
| `S[s]` | Nivel de reposición. En una política `(s, S)` es a la vez el objetivo y el techo | unidades | — |
| `Ivida[s]` | Unidades consumibles antes del vencimiento, descontando lo que ya hay | unidades | `SHELF_LIFE_SAFETY_RATIO = 0.80` |
| `Amax[s]` | Techo efectivo de compra | unidades | El más restrictivo de los dos |
| `need[s]` | Faltante hasta el punto de reorden — **restricción dura** del MILP | unidades | — |
| `des[s]` | Cantidad deseada hasta el nivel de reposición — **lo que se pide** | unidades | — |

**Por qué el techo y el objetivo son el mismo número.** Nunca se compra por
encima de `S`, así que `S` es el inventario máximo que la pieza puede llegar a
tener. Mantenerlos como dos constantes distintas —una cobertura de 3 meses y otra
de 1,5— era una duplicación sin fundamento: la política solo tiene un nivel.

**Lo que esto cerró y lo que no.** Cierra el punto que la versión anterior de este
documento declaraba explícitamente: «la teoría clásica lo derivaría equilibrando
costo de ordenar contra costo de mantener (fórmula de Wilson / EOQ), usando el
flete que ya está en los datos. Esa derivación no está implementada». Ya lo está.
No cierra que `i_h = 0,25` sigue siendo un parámetro de negocio sin validar, del
mismo tipo que `c_dia(k)` en §13.7: es un valor típico de la práctica (20–30 %),
no una medición de esta operación.

---

### 13.6 Etapa 3 — MILP de selección de proveedor

Se resuelve **un modelo independiente por cada serie `s`** — 40 modelos de a lo
sumo 3 ofertas. Estructura: **problema de costo fijo** (*fixed-charge*), linaje
Balinski (1961).

```
minimizar     sum_{o in O(s)}  (  p[o] * x[o]  +  f[o] * u[o]  )

sujeto a      sum_o  x[o]  >=  R_inf                       (cobertura)
              sum_o  x[o]  <=  R_sup                       (techo)
              sum_o  u[o]  <=  1                           (proveedor único)

              x[o]  >=  m[o] * u[o]      para todo o       (MOQ condicional)
              x[o]  <=  U[o] * u[o]      para todo o       (enlace y capacidad)

              x[o]  in  Z+ ,   u[o]  in  {0,1}
```

| Símbolo | Qué es | Unidad | Nota |
|---|---|---|---|
| `x[o]` | Unidades a comprar de la oferta `o` | unidades enteras | Variable de decisión |
| `u[o]` | Indicadora de activación de la oferta `o` | 0/1 | Variable de decisión |
| `p[o]`, `f[o]`, `m[o]` | Precio unitario, flete fijo, MOQ | USD/u, USD, u | Datos |
| `U[o]` | Cota superior efectiva: `min( R_sup , K[o] )` | unidades | Datos |
| `R_inf` | Cantidad mínima requerida | unidades | `max(des, need)` en el caso normal |
| `R_sup` | Cantidad máxima permitida | unidades | `max(Amax, des, need)` en el caso normal |

**El mecanismo central son las dos restricciones de enlace.** Con `u[o] = 0`
ambas fuerzan `x[o] = 0` y no se paga flete. Con `u[o] = 1` obligan a
`m[o] <= x[o] <= U[o]`. Es lo que convierte «el flete solo se paga si se usa el
proveedor» y «el MOQ solo aplica si se le compra» en restricciones lineales.

**`sum_o u[o] <= 1` es una restricción operativa, no matemática.** Permitir
dividir la orden entre proveedores daría un óptimo igual o mejor; se impone
*single-sourcing* para que la orden sea ejecutable por una persona.

**Solver:** CBC vía PuLP, con sonda de arranque (`_solver_answers`) porque PuLP
declara disponible a `COIN_CMD` con que exista un ejecutable llamado `cbc`, sin
comprobar que arranque. Límite de 60 s por modelo; en la práctica milisegundos.

---

### 13.7 Etapa 3.b — Valoración del quiebre

Traduce el riesgo de faltante a dólares para que entre en la función objetivo de
la mochila. **Es un cálculo determinista**, no probabilístico.

```
cover[s]       = q[s] / d[s]                si D50 > 0 ,  else 360

expuesto_hoy   = max( 0 ,  L - cover[s] )
expuesto_luego = max( 0 ,  P + L - cover[s] )

dias[s]        = expuesto_luego  -  expuesto_hoy

Cq[s]          = dias[s]  *  clip( r[s] , 0 , 1 )  *  c_dia( k[i] )
```

| Símbolo | Qué es | Unidad | Origen |
|---|---|---|---|
| `cover[s]` | Días que aguantan las existencias al ritmo proyectado | días | Calculado |
| `P` | Periodo de planificación (`PLANNING_PERIOD_DAYS`) | días | 30 |
| `expuesto_hoy` | Días de quiebre si se repone en esta corrida | días | — |
| `expuesto_luego` | Días de quiebre si se aplaza a la corrida siguiente | días | — |
| `dias[s]` | **Días de quiebre que compra la decisión de hoy** | días | La diferencia entre ambos futuros |
| `r[s]` | Tasa de salida: proporción de días del mes en que la pieza se pide (`issue_rate`) | fracción 0–1 | `demand_forecast.csv` |
| `c_dia(k)` | Costo por día de quiebre según criticidad | USD/día | A = 400 · B = 80 · C = 10 (`STOCKOUT_COST_PER_DAY_USD`) |
| `Cq[s]` | Costo esperado del quiebre evitado (`stockout_cost_usd`) | USD | — |

**El factor `r[s]` es la corrección que hace defendible la cifra.** Un día sin
existencias solo cuesta si ese día alguien pide la pieza. Sin multiplicar por la
frecuencia de salida, la valoración supone que la pieza hace falta todos los días
y **triplica el riesgo**.

**Tres limitaciones declaradas:**

1. **Es determinista.** Supone que la demanda ocurre exactamente al ritmo
   proyectado, así que ignora que una serie volátil puede agotarse antes.
   Subestima el riesgo justo en las piezas menos predecibles. Corregirlo exige
   trabajar con la distribución de la demanda, no con su valor esperado.
2. **Es cota superior por el otro lado.** Supone que cada día en que la pieza se
   pide y no está se pierde entero, sin contar canibalización de otra máquina ni
   expedición de la orden.
3. **`c_dia(k)` es un parámetro fijo, no una estimación.** Su magnitud decide por
   sí sola cuánto pesa la criticidad frente al precio. Debe validarse con
   mantenimiento antes de darle poder sobre las compras.

---

### 13.8 Etapa 3.b — Reparto con la continuidad como restricción dura

**Es el único paso que acopla las piezas entre sí.** Hasta aquí cada serie se
resolvía por separado.

El presupuesto **dejó de mandar sobre todo**. Antes maximizaba beneficio neto
sujeto a `B`, y una pieza podía quedar aplazada aunque su quiebre parara una
línea, simplemente porque otras rendían más por dólar. Es un mal negocio que la
mochila no veía, porque trataba todas las piezas con la misma moneda. Ahora el
presupuesto es una restricción sobre *lo discrecional*, y la continuidad de
producción sube a restricción dura.

```
Cand_dura = { s : theta( k[i] ) = 1 }      criticidad A: paran una línea
Cand_flex = el resto

maximizar     sum_{s in Cand_flex}  b[s] * v[s]

sujeto a      v[s] = 1                     para todo s in Cand_dura       (R1)

              sum_{s in Cand}  Ctot[s] * v[s]  <=  B + E                  (R2)

              E  <=  E_max                                                (R3)

              sum_{s in Clase_k}  v[s]  >=  ceil( theta[k] * |Clase_k| )  (R4)

              v[s] in {0,1} ,  E >= 0
```

| Símbolo | Qué es | Unidad | Origen |
|---|---|---|---|
| `Cand` | Compras candidatas: solo las filas con `decision = COMPRAR` | conjunto | Salida de §13.6 |
| `v[s]` | Si la compra `s` se financia en esta corrida | 0/1 | Variable de decisión |
| `Ctot[s]` | Costo total de la compra ya resuelta (`total_cost_usd`) | USD | Salida del MILP |
| `b[s]` | Beneficio neto: `Cq[s] - Ctot[s]` (`net_benefit_usd`) | USD | §13.7 |
| `B` | Presupuesto nominal de la corrida | USD | `SCENARIO_BUDGET_USD = 2500` |
| `E` | **Excedente autorizado** consumido para cubrir lo crítico | USD | Reportado, no oculto |
| `E_max` | Tope del excedente | USD | `BUDGET_OVERRUN_MAX_USD = 1500` |
| `theta[k]` | Fracción mínima de la clase `k` que debe financiarse | fracción 0–1 | `SERVICE_FLOOR_BY_CRITICALITY` = A 1,00 · B 0,80 · C 0,50 |

**Cómo se lee (R1).** Toda pieza de criticidad A bajo su punto de reorden se
repone, sin competir. El optimizador ya no puede aplazarla.

**Cómo se lee (R2) y (R3).** El presupuesto se vuelve elástico hasta `E_max`. Si
lo crítico cabe en `B`, `E = 0` y nada cambia. Si no cabe, el modelo consume
excedente **y lo reporta explícitamente**, que es el punto: la decisión de gastar
de más queda visible y justificada. El excedente solo financia lo crítico; lo
discrecional compite por `max(0, B − gasto crítico)`.

**Cómo se lee (R4).** Es coherencia con §13.4.2. Si ya se declaró un 90 % de
nivel de servicio para las piezas B al calcular el punto de reorden, el
presupuesto no debería contradecirlo aplazando la mayoría de ellas. `theta_A = 1`
es exactamente (R1), de modo que las dos restricciones son un mismo mecanismo con
tres umbrales.

**Escalera de relajación.** Cuando el dinero no alcanza ni para los pisos, el
modelo no devuelve infactible: suelta el piso de la clase menos exigente, y si
sigue sin caber, el de la siguiente. Aplazar una pieza C antes que una B es la
misma jerarquía que declara el resto del sistema. El nivel de servicio realmente
alcanzado se publica junto al declarado (`budget_allocation_summary`), de modo
que soltar un piso sea visible y no un silencio.

**Es el problema de la mochila 0/1** con cardinalidad por clase, linaje Lorie &
Savage (1955) y Weingartner (1963) en racionamiento de capital.

**Por qué exacto y no voraz.** El algoritmo voraz —ordenar por `b[s]/Ctot[s]` y
llenar— es óptimo solo si las compras fueran fraccionables. Con decisiones
indivisibles puede fallar: una compra muy rentable y cara desplaza a varias menos
rentables y baratas que juntas rinden más. Con ~10–15 candidatos,
*branch-and-bound* resuelve en milisegundos.

**El caso infactible.** Si `sum_{Cand_dura} Ctot > B + E_max`, no se relaja (R1)
ni se falla en silencio. Se ordenan las piezas de `Cand_dura` por `Cq[s]`
descendente —el quiebre que evitan—, se cubren las que caben, y las que no salen
con decisión `ESCALAR` y el texto que dice cuánto dinero adicional hace falta y
contra qué riesgo. Es el mismo principio de `REVISAR`: cuando el sistema no puede
decidir, lo dice.

**Solo compiten las filas `COMPRAR`.** Las de `REVISAR` no son gasto aprobado
sino decisión pendiente de una persona; descontarlas reservaría dinero para
compras que quizá nunca se hagan.

**Nota sobre unidades del objetivo.** `b[s]` está en USD y la restricción en USD:
no hace falta multiplicador de Lagrange que traduzca entre «servicio» y «dinero»,
porque la valoración de §13.7 ya puso ambas mitades en la misma moneda.

---

### 13.9 Árbol de decisión completo

Orden estricto de evaluación por serie `s`:

```
1.  need[s] = 0                  ->  NO_COMPRAR   "por encima del punto de reorden"
2.  O(s) = vacío                 ->  NO_COMPRAR   "sin proveedor para la ciudad"
3.  Ivida[s] < min_o m[o]        ->  NO_COMPRAR   "vida útil no admite ni el MOQ"
4.  min_o m[o] > Amax[s]         ->  REVISAR      resolver con R_sup = min_o m[o]
5.  en otro caso                 ->  COMPRAR      resolver con R_inf = max(des,need)

6.  post-MILP:     si COMPRAR y b[s] <= 0
                                 ->  NO_COMPRAR   "reponer cuesta más que el quiebre"

7.  post-reparto:  si COMPRAR, criticidad A y no cabe ni con E_max
                                 ->  ESCALAR      "requiere ampliar el presupuesto"

8.  post-reparto:  si COMPRAR y v[s] = 0
                                 ->  APLAZADO     "no cabe en el presupuesto discrecional"
```

**Bandera de revisión humana** `needs_review = 1` si: la serie ya venía marcada
del forecast (`gamma_final < 0.5` o patrón Insuficiente), o la decisión es
`REVISAR`, o la decisión es `COMPRAR` con `gamma_final < 0.5`, o la decisión es
`APLAZADO`, o la decisión es `ESCALAR`.

**`ESCALAR` no es «más urgente que `APLAZADO`»: es de otra persona.** Una pieza
aplazada es una compra que rendía menos que otras y la resuelve un comprador la
corrida siguiente. Una escalada es una pieza cuyo quiebre para una línea y que ni
con el excedente autorizado cabe: exige que alguien amplíe el presupuesto ahora.
Por eso la interfaz le da banda propia y color de marca en lugar de un rojo más
intenso.

**El estado `REVISAR` no es un fallo del solver.** Es una tensión real de
compras: el lote mínimo del proveedor supera el máximo que la pieza admite en
bodega. Devolver «infactible» escondería la decisión; el sistema resuelve
igualmente, informa cuánto costaría y cuántos meses de inventario dejaría, y lo
marca para que decida el comprador.

---

### 13.10 Paradigma global y su ubicación en la literatura

El sistema implementa el paradigma clásico **«pronosticar y luego optimizar»**
(*predict-then-optimize* desacoplado), arquitectura estándar de investigación de
operaciones desde los años 60:

```
   clasificar patrón            ->  estadística de series de tiempo (1970s)
        |
   pronosticar por régimen      ->  media móvil / OLS / Holt-Winters / percentiles
        |                           + gradient boosting promediado al 50 %
   traducir a inventario mínimo ->  punto de reorden con varianza combinada
        |                           (Hadley & Whitin, 1963)
   optimizar la compra          ->  MILP de costo fijo (Balinski, 1961)
        |
   repartir el presupuesto      ->  mochila 0/1 (Lorie-Savage 1955 / Weingartner 1963)
```

**Lo que el sistema NO es.** No implementa el paradigma integrado moderno
(*Smart Predict-then-Optimize*, Elmachtoub & Grigas 2022; aprendizaje por
refuerzo): el modelo de ML se entrena para minimizar **error de pronóstico**
(WMAPE), sin ninguna noción de costo, presupuesto ni quiebre. Esas magnitudes
entran en una etapa posterior y completamente separada. Un modelo con mejor WMAPE
puede, en principio, producir peores decisiones de compra, y el sistema no lo
detectaría.

**Dónde el ML toca realmente la decisión.** En un solo punto: `D50_final`, y
diluido al 50 % con el método estadístico. Todo lo que decide —el patrón, el
inventario mínimo, el proveedor, el reparto del presupuesto— es matemática
determinista anterior a 1985.

---

### 13.11 Mapa fórmula → código

| § | Concepto | Archivo | Función / constante |
|---|---|---|---|
| 13.1.2 | Fuerza estacional | `app/core/patterns.py` | `seasonal_strength` |
| 13.1.3 | Kruskal-Wallis | `app/core/patterns.py` | `seasonality_pvalue` |
| 13.1.4 | Mann-Kendall | `app/core/patterns.py` | `trend_test` |
| 13.1.5 | Regla de precedencia | `app/core/patterns.py` | `classify_series`, `PRECEDENCE` |
| 13.1.6 | Score de confianza | `app/core/patterns.py` | `confidence_score` |
| 13.2.1 | Los cuatro estimadores | `app/core/forecast.py` | `forecast_stable/volatile/trend/seasonal` |
| 13.2.2 | Cuantiles | `app/core/forecast.py` | `_spread_from_std`, `QUANTILE_Z` |
| 13.2.3 | WMAPE origen móvil | `app/core/forecast.py` | `backtest_wmape` |
| 13.2.4 | Ajuste de confianza | `app/core/forecast.py` | `adjust_confidence` |
| 13.3.1 | Espacio de variables | `app/core/training.py` | `build_features`, `LAGS`, `ROLLING_WINDOWS` |
| 13.3.2 | Estimador | `app/core/training.py` | `DemandModel.train`, `MODEL_PARAMS` |
| 13.3.3 | Partición y métricas | `app/core/training.py` | `temporal_split`, `regression_metrics` |
| 13.3.4 | Combinación | `app/services/model_registry.py` | `blend_forecasts`, `MODEL_WEIGHT` |
| 13.4.1 | Conversión diaria | `app/core/inventory.py` | `monthly_to_daily`, `DAYS_PER_MONTH` |
| 13.4.2 | Stock de seguridad | `app/core/inventory.py` | `safety_stock`, `Z_BY_CRITICALITY` |
| 13.4.3 | Inventario mínimo | `app/core/inventory.py` | `inventory_minimum` |
| 13.5.1 | Cantidad económica | `app/core/optimization.py` | `economic_order_quantity`, `holding_cost_per_unit_year`, `planning_order_cost`, `HOLDING_COST_RATE_ANNUAL`, `EOQ_MAX_COVERAGE_MONTHS` |
| 13.5.2 | Niveles y cotas | `app/core/optimization.py` | `replenishment_level`, `consumable_within_shelf_life` |
| 13.6 | MILP de proveedor | `app/core/optimization.py` | `solve_single_purchase` |
| 13.7 | Valoración del quiebre | `app/core/optimization.py` | `days_of_cover`, `stockout_days_avoided`, `stockout_cost` |
| 13.8 | Reparto y continuidad dura | `app/core/optimization.py` | `allocate_budget`, `allocate_discretionary`, `apply_budget`, `budget_allocation_summary`, `BUDGET_OVERRUN_MAX_USD`, `SERVICE_FLOOR_BY_CRITICALITY` |
| 13.9 | Árbol de decisión | `app/core/optimization.py` | `build_recommendations`, `DECISION_ESCALATE` |
| 13.13 | Clasificación del catálogo | `app/core/classification.py` | `classify_parts`, `cross_matrix`, `build_classification` |
| §13 entero | Fórmulas en pantalla | `frontend/js/formulas.js` | `FORMULAS`, `renderTheory` |

---

### 13.12 Inventario de supuestos y sus límites

Recopilación explícita para que un agente sepa qué puede y qué no puede
concluirse del sistema.

| # | Supuesto | Dónde entra | Consecuencia si es falso |
|---|---|---|---|
| 1 | La demanda mensual es aproximadamente normal | Cuantiles (§13.2.2), stock de seguridad (§13.4.2) | Con `CV > 0,5` los intervalos y el servicio real quedan cortos en la cola derecha |
| 2 | La demanda durante un plazo aleatorio es normal | `z` aplicado sobre `sqrt(Var_L)` (§13.4.2) | Eppen & Martin (1988): la mezcla es sesgada; el servicio nominal se sobreestima |
| 3 | Demanda y plazo de entrega son independientes | Ley de varianza total (§13.4.2) | En la práctica correlacionan en la peor dirección: alta demanda congestiona al proveedor |
| 4 | La dispersión relevante es `sigma` de la serie | §13.4.1 | La teoría pide el RMSE del pronóstico; usar la serie sobreestima el colchón en series ya modeladas |
| 5 | Las demandas de meses consecutivos son independientes | Escalado `sqrt(30)` (§13.4.1) | Con autocorrelación el exponente real está entre 0,6 y 0,8, no en 0,5 |
| 6 | El pasado del proveedor predice su futuro | `L`, `sigma_L` (§13.4.2) | No contempla aduanas, cierres de planta ni estacionalidad del proveedor |
| 7 | El horizonte es de un periodo | Todo el sistema (§13.0) | No hay trayectoria de inventario: comprar hoy no afecta la decisión del mes siguiente |
| 8 | La demanda ocurre al ritmo proyectado | Valoración del quiebre (§13.7) | Subestima el riesgo en las series volátiles, que son las que más lo necesitan |
| 9 | `c_dia(k)` refleja el costo real de parar la línea | §13.7 | Su magnitud decide el peso de la criticidad frente al precio; hoy es un número fijo sin validar |
| 10 | Los tres `z` reflejan la política de servicio deseada | §13.4.2 | Fijados por constante, no derivados de un costo de faltante |
| 11 | Cada serie se optimiza independientemente | §13.6 | No modela consolidación de órdenes (un flete por proveedor) ni traslado entre plantas |
| 12 | Los errores de ambos estimadores tienen igual varianza y son incorrelados | `lambda = 0.5` (§13.3.4) | El peso óptimo de la combinación no está estimado sobre los datos |
| 13 | La tasa anual de posesión es del 25 % del valor de la pieza | `h = i·c` (§13.5.1) | Es un valor típico de la práctica (20–30 %), no una medición de esta operación. Sube la tasa y los lotes se encogen; bájala y crece el inventario |
| 14 | La demanda es constante dentro del año | Fórmula de Wilson (§13.5.1) | EOQ supone demanda uniforme; con estacionalidad marcada el lote óptimo varía por mes y esta versión no lo recoge |
| 15 | El flete medio de las ofertas aproxima el del proveedor que gane | `K` en §13.5.1 | Amortiguado por la raíz cuadrada: errar en el doble mueve `Q*` un 41 % y el costo total mucho menos |
| 16 | La etiqueta de criticidad del maestro es correcta | Restricción dura (§13.8) | Si una pieza está mal etiquetada como A, el modelo gasta excedente real protegiendo la pieza equivocada |

**La relación de dualidad que cerraría los supuestos 9 y 10.** Fijar `z` y fijar
un costo de faltante son el mismo acto. Para un modelo `(R,Q)`:

```
b  =  ( h * Q )  /  ( D * ( 1 - alpha ) )
```

| Símbolo | Qué es | Unidad |
|---|---|---|
| `b` | Costo de faltante por unidad **implícito** en el servicio declarado | USD/unidad |
| `h` | Costo de mantener inventario por unidad y año | USD/unidad/año |
| `Q` | Cantidad de reposición | unidades |
| `D` | Demanda anual | unidades/año |
| `alpha` | Nivel de servicio de ciclo declarado, `Phi(z)` | fracción 0–1 |

Corrida al revés sobre los parámetros que el sistema ya tiene, revela qué costo
de quiebre está asumiendo cada `z` sin haberlo decidido, y permite contrastarlo
contra lo que operaciones dice que cuesta parar una línea en Nava o en Obregón.

---

### 13.13 Diagnóstico del dato de entrada

Medido sobre `demand_history.csv` (2 880 observaciones) el 2026-08-18. Es
material de §13.12 pero se separa porque no es un supuesto del modelo sino una
propiedad del dato que lo alimenta.

| Métrica | Valor medido | Referencia en MRO real | Lectura |
|---|---|---|---|
| Meses con demanda cero | **3,26 %** | 40–70 % mensual | El histórico no es intermitente |
| `z0` mediano por serie | **0,000** | > 0,4 | La serie mediana consume **todos** los meses |
| ADI mediano | **1,00** | > 1,32 | Sin espaciamiento entre eventos |
| `CV²` mediano (sobre periodos con demanda) | **0,11** | > 1,0 | Tamaños de evento muy estables |
| Demanda media por serie | **18,3 u/mes** | 0,1–3 u/mes | Perfil de insumo de producción, no de refacción |
| Rotación mínima del catálogo | **9,8 vueltas/año** | ítems N rotan < 1 | Ningún ítem realmente inmóvil |

**Clasificación ADI / CV² (Syntetos, Boylan & Croston, 2005)**, umbrales
`ADI = 1,32` y `CV² = 0,49`:

| Régimen | Series | Lo que implica |
|---|---|---|
| Suave | **38 / 40** | El suavizado exponencial simple bastaría |
| Intermitente | 2 / 40 | Terreno de Croston/SBA |
| Errática | 0 / 40 | — |
| Lumpy | **0 / 40** | Es donde vive la mayoría del MRO real |

**Consecuencia teórica.** El dato actual **no ejercita** la rama de la literatura
que corresponde a refacciones (Croston 1972, SBA 2005, TSB 2011, distribuciones
Poisson/binomial negativa). Los métodos implementados en §13.2 son los adecuados
para el dato que hay; serían insuficientes para dato MRO real. Esto acota lo que
el MVP demuestra: valida la **arquitectura de decisión**, no la capacidad de
pronosticar demanda intermitente.

**Clasificaciones del catálogo** (20 piezas, ver `docs/diagnostico-piezas.html`):

- **Criticidad** (del maestro): A = 6 · B = 9 · C = 5
- **Valor ABC** (Pareto sobre consumo anual proyectado, 54 894 USD/año):
  A ≤ 80 % = 8 piezas · B 80–95 % = 6 · C = 6
- **Rotación FSN** (por `issue_rate`): F ≥ 50 % = 7 · S 15–50 % = 9 · N < 15 % = 4

La celda **N × Criticidad A** (contactor y sensor de proximidad) es el caso donde
el ABC por valor recomendaría no invertir y el cruce con criticidad dice lo
contrario: rotan poco pero paran una línea. Ninguna clasificación por separado
llega a esa conclusión.

---

## 14. Diseño — Continuidad de producción como restricción dura

> **Estado: ✅ IMPLEMENTADO el 2026-08-20.** La formulación operativa vive ahora
> en [§13.8](#138-etapa-3b--reparto-con-la-continuidad-como-restricción-dura) y
> el árbol de decisión con `ESCALAR` en
> [§13.9](#139-árbol-de-decisión-completo). Esta sección se conserva como el
> registro de por qué se hizo y qué se decidió, que es lo que §13 no cuenta.

### 14.1 El problema con el modelo actual

Hoy el presupuesto **manda sobre todo**. La mochila de §13.8 maximiza beneficio
neto sujeta a `B = 2.500 USD`, y una pieza puede quedar `APLAZADO` aunque su
quiebre pare una línea, simplemente porque otras rendían más por dólar.

La corrida actual lo demuestra: **3 piezas aplazadas por 1.116,94 USD**, dejando
3.152,08 USD de riesgo sin cubrir. Si alguna de esas tres es de criticidad A, el
sistema está eligiendo ahorrar 1.117 USD a cambio de arriesgar un paro de línea
que cuesta 400 USD/día. Eso es un mal negocio que el modelo no ve porque trata
todas las piezas con la misma moneda.

**La inversión conceptual:** el presupuesto deja de ser una restricción sobre
*todo* y pasa a ser una restricción sobre *lo discrecional*. La continuidad de
producción sube a restricción dura.

### 14.2 Formulación propuesta

Se parte el conjunto de candidatos en dos según criticidad:

```
Cand_dura   = { s : k[i] = A }        piezas cuyo quiebre para una línea
Cand_flex   = { s : k[i] in {B,C} }   el resto
```

Modelo:

```
maximizar     sum_{s in Cand_flex}  b[s] * v[s]

sujeto a      v[s] = 1                        para todo s in Cand_dura     (R1)

              sum_{s in Cand}  Ctot[s] * v[s]  <=  B + E                   (R2)

              E  <=  E_max                                                 (R3)

              v[s] in {0,1} ,  E >= 0
```

| Símbolo | Qué es | Unidad | Nota |
|---|---|---|---|
| `Cand_dura` | Reposiciones de criticidad A que están bajo el mínimo | conjunto | Se financian siempre |
| `Cand_flex` | Reposiciones B y C | conjunto | Compiten por lo que sobre |
| `v[s]` | Si la compra se financia | 0/1 | Forzada a 1 en `Cand_dura` |
| `b[s]` | Beneficio neto `Cq[s] − Ctot[s]` | USD | §13.7 |
| `B` | Presupuesto nominal de la corrida | USD | 2 500 |
| `E` | **Excedente autorizado**: cuánto se permite pasarse para cubrir lo crítico | USD | Nueva variable |
| `E_max` | Tope del excedente | USD | Parámetro de negocio |

**Cómo se lee (R1).** Toda pieza de criticidad A bajo su mínimo se repone, sin
competir. El optimizador ya no puede aplazarla.

**Cómo se lee (R2) y (R3).** El presupuesto se vuelve elástico hasta `E_max`.
Si lo crítico cabe en `B`, `E = 0` y nada cambia. Si no cabe, el modelo consume
excedente **y lo reporta explícitamente**, que es el punto: la decisión de gastar
de más queda visible y justificada, no escondida.

### 14.3 El caso infactible y qué debe hacer el sistema

Si `sum_{Cand_dura} Ctot[s] > B + E_max`, el modelo es infactible. **No debe
fallar en silencio ni relajar (R1) por su cuenta.** Debe:

1. Reportar el déficit exacto: `Deficit = sum_{Cand_dura} Ctot − (B + E_max)`.
2. Ordenar las piezas de `Cand_dura` por `Cq[s]` descendente —el quiebre que
   evitan— y marcar cuáles caben.
3. Devolver las que no caben con decisión `ESCALAR`, un quinto estado, con el
   texto: *«Reponer esta pieza crítica requiere ampliar el presupuesto en X USD;
   no hacerlo expone a un quiebre valorado en Y USD.»*

Es el mismo principio de `REVISAR`: cuando el sistema no puede decidir, lo dice
en vez de fingir que sí.

### 14.4 Refinamiento: criticidad como restricción de servicio, no como binaria

La partición A / {B,C} es tosca. Una versión más fina impone un **nivel de
servicio agregado mínimo por clase**:

```
sum_{s in Clase_k}  v[s]  >=  ceil( theta[k] * |Clase_k| )        para cada k
```

| Símbolo | Qué es | Unidad | Valor sugerido |
|---|---|---|---|
| `Clase_k` | Reposiciones necesarias de criticidad `k` | conjunto | — |
| `theta[k]` | Fracción mínima de la clase que debe financiarse | fracción 0–1 | A = 1,00 · B = 0,80 · C = 0,50 |

Esto es **consistente con los `z` de §13.4.2**: si ya se declaró 95/90/80 % de
nivel de servicio por criticidad al calcular `Imin`, el presupuesto no debería
contradecir esa política aplazando justo las críticas. Hoy hay una incoherencia
declarada entre las dos etapas y esta restricción la cierra.

### 14.5 Qué se tocó

| Archivo | Cambio | Estado |
|---|---|---|
| `app/core/optimization.py` | `allocate_budget`: parte candidatos, fuerza `v[s] = 1` en criticidad A y estira el presupuesto hasta `E_max` | ✅ |
| `app/core/optimization.py` | `allocate_discretionary` y `_solve_knapsack`: mochila de lo flexible con pisos de servicio y escalera de relajación | ✅ |
| `app/core/optimization.py` | `DECISION_ESCALATE = "ESCALAR"` y `REASON_ESCALATE` | ✅ |
| `app/core/optimization.py` | `BUDGET_OVERRUN_MAX_USD = 1500`, `SERVICE_FLOOR_BY_CRITICALITY = {A: 1.00, B: 0.80, C: 0.50}` | ✅ |
| `app/core/optimization.py` | `budget_allocation_summary`: excedente consumido, déficit y nivel de servicio alcanzado por clase | ✅ |
| `app/core/pipeline.py`, `app/services/recommendations.py` | Publican el reparto y el nivel de servicio junto al declarado | ✅ |
| `frontend/js/turno.js` | La apertura abre por continuidad, no por presupuesto; banda propia `ESCALAR` con color de marca | ✅ |
| `frontend/js/caso.js` | Bloque de escalada con el dinero adicional que pide y el quiebre que evita | ✅ |
| `tests/core/test_budget.py` | 9 casos nuevos: crítica que no cabe → `ESCALAR`; excedente reportado; pisos que ceden antes de declarar infactible | ✅ |

### 14.6 Lo que este diseño NO resuelve

- **El horizonte sigue siendo de un periodo.** Forzar la compra crítica hoy no
  considera que el mes siguiente puede haber otra peor.
- **`c_dia(k)` sigue sin validar** (§13.7, limitación 3). La partición por
  criticidad hereda la misma debilidad: si la etiqueta A está mal puesta en el
  maestro, el modelo protege la pieza equivocada con dinero real.
- **No sustituye al traslado entre plantas** (§11.4 mejora 5). Mover stock sigue
  siendo más barato que comprar, y debería resolverse *antes* de consumir
  excedente presupuestal.
- **`E_max` es un parámetro de negocio.** 1 500 USD sobre 2 500 es un 60 % de
  elasticidad, un número elegido para el MVP y no negociado con finanzas. Su
  magnitud decide cuántas piezas críticas caben antes de escalar.
- **Los pisos discrecionales rara vez se cumplen con este presupuesto.** En la
  corrida actual B y C quedan en 0 % contra pisos de 80 % y 50 %. La restricción
  no es decorativa —cede de forma ordenada y lo reporta— pero con este dinero
  casi nunca llega a morder, y eso es en sí mismo el hallazgo: el presupuesto de
  la corrida es incoherente con la política de servicio declarada en §13.4.2.

---

## 15. Diseño — Chat de explicabilidad y trazabilidad

> **Estado: ⬜ propuesto, no implementado.** Diseño corto para retomar después.

### 15.1 Qué problema resuelve

Hoy la explicación del sistema está congelada en la columna `reason` de cada
fila: una frase generada por plantilla en el momento de la corrida. Sirve para
auditar *una* decisión, pero no responde preguntas transversales, que son las que
de verdad hace un comprador o un gerente:

- «¿Por qué esta pieza está aplazada y aquella no, si cuestan lo mismo?»
- «¿Cuánto tendría que subir el presupuesto para que no quede nada aplazado?»
- «¿Qué piezas dependen del proveedor Alpha y qué pasa si se retrasa?»
- «¿Por qué el inventario mínimo de esta pieza subió respecto al mes pasado?»

Ninguna se contesta leyendo una fila. Todas se contestan con los datos que el
sistema ya tiene, si algo sabe navegarlos.

**El agente ya existe a medias.** `app/services/llm_agent.py` tiene
`ExplanationAgent` con `BaseAgent` del SDK y `llm_provider="gemini"`, pero solo
genera texto por fila. Este diseño lo convierte en conversacional.

### 15.2 Principio de diseño no negociable

**El LLM no calcula, no decide y no estima. Solo consulta y redacta.**

Toda cifra que aparezca en una respuesta debe venir de una herramienta que la
leyó del dataset o la recalculó con las funciones de `app/core/`. Si el LLM no
puede respaldar un número con una llamada a herramienta, debe decir que no lo
sabe. Esto es lo que separa un asistente auditable de uno que alucina cifras de
inventario — y en un sistema cuyo argumento central es la trazabilidad, un número
inventado destruye el producto entero.

### 15.3 Herramientas expuestas al agente

```
consultar_decision(sku_id, city_id)
    -> fila completa de purchase_recommendations.csv + su motivo

consultar_pronostico(sku_id, city_id)
    -> patrón, método, D25/D50/D75, WMAPE, confianza, Imin, safety_stock

consultar_inventario(sku_id?, city_id?, solo_bajo_minimo?)
    -> existencias, mínimo, máximo, cobertura en días

explicar_inventario_minimo(sku_id, city_id)
    -> descompone Imin en (d·L) + (z·sqrt(...)) con los valores usados

comparar_ofertas(sku_id, city_id)
    -> las 2-3 ofertas cotizadas, cuál ganó y por qué (usa offer_costs)

simular_presupuesto(nuevo_B)
    -> re-corre allocate_budget con otro B, devuelve qué dejaría de aplazarse

explicar_aplazamiento(sku_id, city_id)
    -> qué compras consumieron el presupuesto que esta necesitaba

resumen_corrida()
    -> conteos por decisión, gasto, quiebre evitado, retorno, aplazado

historial_serie(sku_id, city_id, meses)
    -> consumo mensual, marcando is_synthetic
```

| Herramienta | Lee de | Recalcula con |
|---|---|---|
| `consultar_decision` | `purchase_recommendations.csv` | — |
| `consultar_pronostico` | `demand_forecast.csv` | — |
| `explicar_inventario_minimo` | `demand_forecast.csv`, `suppliers.csv` | `app.core.inventory.inventory_minimum` |
| `comparar_ofertas` | `supplier_offers.csv`, `supplier_coverage.csv` | `app.core.optimization.offer_costs` |
| `simular_presupuesto` | `purchase_recommendations.csv` | `app.core.optimization.allocate_budget` |
| `explicar_aplazamiento` | `purchase_recommendations.csv` | `allocate_budget` con y sin la pieza |

`simular_presupuesto` y `explicar_aplazamiento` son las dos que justifican el
chat: responden contrafactuales que ninguna columna estática puede contener.

### 15.4 Arquitectura

Respeta la regla de dependencias `api → services → core`:

```
app/api/routes.py           POST /chat  { pregunta, historial } -> { respuesta, fuentes }
        |
app/services/chat_agent.py  ChatAgent(BaseAgent) — orquesta el bucle de herramientas
        |
app/services/chat_tools.py  las 9 funciones de §15.3, puras sobre DataFrames
        |
app/core/                   inventory.py, optimization.py — el cálculo real
```

`chat_tools.py` **no llama al LLM**: son funciones normales, testeables sin red.
Eso permite cubrirlas con pytest como cualquier otro módulo y garantiza que la
capa de cálculo sea verificable con independencia del modelo.

### 15.5 Contrato de respuesta

Cada respuesta del chat devuelve:

```json
{
  "respuesta": "texto en lenguaje natural",
  "fuentes": [
    {"herramienta": "explicar_inventario_minimo", "argumentos": {...}, "resultado": {...}}
  ],
  "run_id": "..."
}
```

**`fuentes` no es opcional y la interfaz debe mostrarlo.** Es lo que convierte la
respuesta en auditable: el usuario ve qué se consultó para producirla. Sin eso,
el chat es una caja negra encima de un sistema que se vendía como trazable.

El `run_id` (mejora 3 de §11.4) es **prerrequisito duro** de este diseño: una
respuesta sobre por qué algo está `APLAZADO` solo es reconstruible si se sabe
contra qué corrida se contestó. Implementar el chat antes que `run_id` produce un
asistente que da respuestas correctas hoy e irreproducibles mañana.

### 15.6 Degradación sin clave

Igual que `ExplanationAgent` hoy: sin `GEMINI_API_KEY`, el endpoint responde con
el resultado crudo de la herramienta más relevante y un aviso de que la redacción
en lenguaje natural no está disponible. El sistema no depende del LLM para ser
consultable — el LLM solo mejora la forma de la respuesta.

### 15.7 Riesgos declarados

| Riesgo | Mitigación |
|---|---|
| El LLM inventa cifras | Toda cifra proviene de herramienta; sin herramienta, se responde «no lo sé» |
| Inyección de instrucciones vía nombres de pieza o motivos | El contenido del dataset se pasa como **datos**, nunca como instrucción; el prompt de sistema lo declara |
| El chat se usa como fuente de verdad en vez del CSV | El contrato incluye `run_id` y `fuentes`; la interfaz enlaza a la fila original |
| Costo por consulta | Las herramientas devuelven agregados, no tablas completas; el histórico se resume antes de entrar al contexto |
| Sin autenticación (§11.3) el chat expone el dataset entero | **Bloqueante:** no publicar el endpoint antes de la mejora 1 de §11.4 |

### 15.8 Orden de implementación

1. `chat_tools.py` con las 9 funciones + tests. Sin LLM: es cálculo puro.
2. `run_id` en cada decisión (mejora 3 de §11.4) — prerrequisito.
3. `ChatAgent` sobre `BaseAgent`, con el bucle de herramientas.
4. Endpoint `POST /chat` **detrás de autenticación**.
5. Interfaz: panel lateral con el historial y las fuentes de cada respuesta.
