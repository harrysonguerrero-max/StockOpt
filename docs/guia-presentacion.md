# Guía de presentación — StockOpt

Documento de apoyo para presentar el sistema. Está escrito para que quien
presenta pueda **defender cada número** y responder en el lenguaje de gestión de
inventarios, no en el de código.

**Regla de oro de la presentación:** decir siempre qué dato es real y cuál es
sintético. La credibilidad se pierde una sola vez.

---

## 1. El planteamiento del problema (2 minutos)

### 1.1 La versión de una línea

> Optimización de inventario de refacciones MRO multi-planta bajo presupuesto
> restringido.

### 1.2 La versión completa

La gestión de refacciones e insumos MRO en las plantas de Nava y Ciudad Obregón
se decide hoy pieza por pieza, con criterio individual y sin un cálculo que ligue
el consumo futuro a la orden de compra: no existe un **punto de reorden** derivado
de la demanda proyectada y del **lead time** real, ni un **inventario máximo** que
acote la sobrecompra, ni una forma sistemática de elegir entre proveedores que
difieren en precio, **MOQ**, capacidad y tiempo de respuesta.

El resultado es una tensión permanente entre dos costos opuestos —**stockout** de
la pieza que detiene una línea, o **capital inmovilizado** en existencias que se
vuelven obsoletas— que se resuelve por intuición y termina inclinándose hacia el
exceso, **porque el quiebre duele de inmediato y el sobrestock no**.

El problema se agrava porque los factores que deberían gobernar la decisión son
medibles pero no se están midiendo:

- La demanda de refacciones es **intermitente**: el 87 % de los meses de este
  catálogo no registra consumo alguno, y el intervalo mediano entre movimientos
  es de **10,3 meses**. No es ruido en torno a un promedio; son eventos
  separados por vacíos.
- El patrón es además heterogéneo entre plantas: de las **407 piezas** que las dos
  consumen, **198 cambian de patrón según la planta**. La misma referencia se
  repone de forma periódica en Nava y de golpe en Obregón.
- El lead time de los proveedores varía con **σ/μ ≈ 0,37** y su peor caso
  declarado (132 días, importación OEM) cuadruplica al promedio ponderado
  (30,0 días).
- El presupuesto de cada corrida es finito, de modo que **reponer una pieza
  necesariamente desplaza a otra**.

### 1.3 El cierre

Sin un mecanismo que proyecte la demanda, traduzca esa proyección en umbrales de
inventario, reparta un presupuesto limitado entre todas las piezas a la vez y
explique cada decisión con la evidencia que la sustenta, **compras no puede
justificar por qué compró lo que compró, ni auditar después si acertó**.

---

## 2. Glosario para la sala

Úsalo de forma natural; son los términos que un profesional de la disciplina
espera oír.

| Término | Qué significa | Cómo usarlo |
|---|---|---|
| **Punto de reorden (ROP)** | Nivel que dispara la orden | «El punto de reorden es 13 unidades» |
| **Stock de seguridad** | Colchón sobre la demanda esperada del lead time | «El safety stock absorbe la variabilidad del proveedor» |
| **Lead time** | Plazo desde que se pide hasta que llega | «Lead time ponderado 30,0 días con sigma 11,07» |
| **MOQ** | Cantidad mínima de orden del proveedor | «El MOQ de 100 supera el máximo de bodega» |
| **Nivel de servicio de ciclo (α)** | Probabilidad de no quebrar en un ciclo | «Criticidad A opera a 95 % de servicio» |
| **Fill rate (β)** | Fracción de demanda servida del stock | «Ojo: α y β no son lo mismo» |
| **Stockout** | Quiebre de inventario | «El costo de stockout entra en la función objetivo» |
| **Cobertura** | Meses o días que aguanta el stock actual | «Quedan 8 días de cobertura contra 30 de lead time» |
| **Rotación / turnover** | Vueltas de inventario al año | «Las piezas clase F se mueven en más de uno de cada cuatro meses» |
| **ABC (Pareto)** | Segmentación por valor | «El 36 % de las referencias es el 80 % del valor» |
| **VED / criticidad** | Segmentación por impacto de la falla | «Criticidad A para en línea de producción» |
| **FSN** | Segmentación por rotación | «Los ítems N son candidatos a auditoría de existencia» |
| **Intermitencia / ADI** | Cada cuántos meses hay consumo | «ADI mediano 10,3: se mueve menos de una vez al año» |
| **CV² del evento** | Dispersión del tamaño del pedido, medida solo en los meses con consumo | «CV² mediano 0,40: cuando se pide, se pide una cantidad parecida» |
| **Cuadrante SBC** | Las cuatro categorías de demanda de Syntetos, Boylan y Croston | «Este catálogo es 63 % intermitente y 37 % irregular» |
| **Croston / SBA** | Estimadores que separan tamaño e intervalo en vez de suavizar la serie | «Con 87 % de ceros, Croston es lo que hay que usar; la media móvil devuelve cero» |
| **MILP** | Programación lineal entera mixta | «La selección de proveedor es un MILP de costo fijo» |
| **Mochila / knapsack** | Asignar recurso escaso entre proyectos indivisibles | «El presupuesto se reparte como mochila 0/1» |
| **WMAPE** | Error ponderado sobre el total | «WMAPE y no MAPE, porque hay meses en cero» |
| **MASE** | Error absoluto escalado contra repetir el mes anterior | «MASE por debajo de 1 significa ganarle al método ingenuo» |
| **Sesgo acumulado** | Unidades de más o de menos al cabo del periodo | «El sesgo acumulado es la métrica que decide, y dice cuánto faltaría en bodega» |
| **Order-up-to** | Reponer hasta un nivel objetivo | «No reponemos al mínimo, sino al nivel objetivo» |

---

## 3. Cómo funciona: el pipeline en cinco fórmulas

Estas son las únicas cinco que hay que poder escribir en un pizarrón.

### 3.1 Clasificación de patrón

La primera pregunta no es qué forma tiene la serie sino **si la serie se mueve
todos los meses**, porque de eso depende que los métodos clásicos sirvan de algo.
Esa pregunta se responde con dos números, y se responde primero:

```
ADI  =  n / n_e                         cada cuántos meses hay consumo
CV²  =  (sigma_e / mu_e)²               dispersión del tamaño, solo en los meses con consumo

Intermitente si  ADI >= 1,32  y  CV² <  0,49
Irregular    si  ADI >= 1,32  y  CV² >= 0,49
```

Solo si la serie **no** es intermitente se aplican los criterios clásicos:

```
Estacional   si  F_s >= 0,45  y  p_Kruskal-Wallis < 0,05
Tendencia    si  p_Mann-Kendall < 0,05
Volátil      si  CV = sigma/mu > 0,50
Estable      en otro caso
```

**Cómo se cuenta:** «Antes de proyectar, cada serie pieza-ciudad se clasifica, y
el primer corte es el de Syntetos, Boylan y Croston: el intervalo medio entre
consumos y la dispersión del tamaño del pedido. Los dos se miden sobre cosas
distintas a propósito. El intervalo cuenta los huecos; la dispersión mira **solo**
los meses que no son hueco. Un coeficiente de variación sobre la serie completa
mezclaría las dos, y con 87 % de ceros lo que domina son los huecos —que es
exactamente el error que hacía que el 94 % de este catálogo pareciera
impredecible antes de separarlos.

En este catálogo **las 1.283 series caen del lado intermitente**: 804
intermitentes y 479 irregulares, ninguna en régimen suave. Los umbrales 1,32 y
0,49 no son una convención: el artículo original los deriva del punto donde cada
estimador supera a los otros.

La estacionalidad, cuando se llega a evaluar, exige **dos** condiciones a la vez y
no una: con pocos ciclos de historia la descomposición clásica encuentra
estacionalidad aparente incluso en ruido puro —fuerza media 0,32—, así que se
exige además significancia estadística del efecto de mes. Eso baja el falso
positivo del 26 % al 2 %.»

### 3.2 Proyección según el patrón

| Patrón | Método | Por qué ese |
|---|---|---|
| **Intermitente** | **Croston (1972)** | La media y la mediana móviles devuelven cero |
| **Irregular** | **Croston-SBA (Syntetos & Boylan, 2005)** | Croston sesga al alza el cociente; SBA lo corrige |
| Estable | Media móvil 6 meses | No hay estructura que aprender |
| Volátil | Percentiles empíricos | La mediana no la arrastra un mes extremo |
| Tendencia | Regresión lineal | Captura la deriva sostenida |
| Estacional | Holt-Winters aditivo | Prophet sobreajusta con pocos ciclos |

Croston no suaviza la serie: la parte en dos y suaviza cada mitad por separado.

```
z_t  =  alpha·y_t  +  (1 - alpha)·z_(t-1)      cuánto se pide cuando se pide
p_t  =  alpha·q_t  +  (1 - alpha)·p_(t-1)      cada cuántos meses ocurre
D50  =  c · z_t / p_t

c = 1        Croston, para la serie intermitente
c = 1 - alpha/2 = 0,925   SBA, para la serie irregular
```

Las dos series se actualizan **solo en los meses en que algo se mueve**, y ahí
está todo el método.

**Cómo se cuenta:** «No aplicamos un solo modelo a todo. Es un modelo por
regímenes: cada serie va al estimador que su patrón justifica. En este catálogo
eso significa que **todas** van a Croston o a su aproximación, y no es un detalle
técnico: suavizar la serie cruda converge a cero, porque la mayoría de los meses
son cero, y afirmar que una pieza que se consume dos veces al año tiene demanda
cero no es un pronóstico, es una renuncia. Con la mediana móvil, el 86 % de las
series proyectaba demanda nula y el sistema no compraba nada. Ese fue el hallazgo
que obligó a incorporar Croston, y está medido, no supuesto.

La corrección de SBA existe porque el cociente de dos estimadores suavizados está
sesgado al alza. Se aplica a las series irregulares porque es ahí donde ese sesgo
inflaría el inventario de las piezas menos predecibles, que son las caras.»

### 3.3 Inventario mínimo — **la fórmula central**

La media y la varianza de la demanda durante el plazo son las de Hadley y Whitin
(1963), y son las mismas de siempre:

```
mu_LT  =  d · L
var_LT =  L · sigma_d²  +  d² · sigma_L²
          └──────┬────┘   └──────┬─────┘
        incertidumbre de   incertidumbre del
        la demanda         proveedor
```

Lo que cambió es **cómo se convierte esa media y esa varianza en un número de
unidades**. Antes se usaba `Imin = mu_LT + z(k)·sqrt(var_LT)`, que es la
aproximación normal. Ahora se toma el cuantil de una **binomial negativa**
ajustada a esa misma media y varianza:

```
Imin  =  F⁻¹( alpha(k) ; r, p )       con   p = mu_LT / var_LT ,   r = mu_LT · p / (1 − p)
```

| Símbolo | Qué es | Unidad | Valor actual |
|---|---|---|---|
| `d` | Demanda media diaria proyectada | unidades/día | Por serie |
| `L` | Lead time medio ponderado | días | 30,0 |
| `sigma_d` | Desviación de la demanda diaria | unidades/día | Por serie |
| `sigma_L` | Desviación del lead time | días | 11,07 |
| `alpha(k)` | Nivel de servicio de ciclo por criticidad | fracción | A = 0,95 · B = 0,90 · C = 0,80 |
| `r, p` | Parámetros de la binomial negativa ajustada a `mu_LT` y `var_LT` | — | Por serie |

**Cómo se cuenta:** «La media y la varianza son las canónicas de Hadley & Whitin,
las mismas que llevan los módulos MRP de SAP y Oracle, y lo importante sigue
siendo el segundo término: está multiplicado por la **demanda al cuadrado**, así
que buena parte del riesgo de cada pieza no viene de la demanda sino del
proveedor. Ignorar ese término dejaría el colchón corto creyendo tener 95 % de
servicio.

Lo que no se puede usar aquí es la aproximación normal. Con medias de dos o tres
unidades y desviaciones mayores que la media, una normal centrada en `mu_LT`
pone **una mediana del 39 % de su masa en demanda negativa** —más del 20 % en el
99 % de las series— y compensa esa masa imposible estirando la cola derecha. El
efecto medido era un catálogo inflado un 49 %: 16.241 unidades y 1,34 M USD
frente a 7.789 unidades y 683 k USD, al mismo nivel de servicio declarado. La
binomial negativa vive en los enteros no negativos, que es donde vive la demanda
de refacciones.»

**El puente a negocio:** «Y ese nivel de servicio es una decisión de negocio, no
técnica. 0,95 significa que una de cada veinte reposiciones puede llegar tarde.
Es la única declaración de política de servicio que hace el sistema, y hoy está
fijada por constante.»

### 3.4 Selección de proveedor — MILP de costo fijo

```
minimizar   suma_o ( precio_o · x_o  +  flete_o · u_o )

sujeto a    suma_o x_o >= faltante          cubrir la necesidad
            suma_o x_o <= techo             no pasar del máximo
            suma_o u_o <= 1                 un solo proveedor
            x_o >= MOQ_o · u_o              el MOQ solo aplica si le compro
            x_o <= U_o · u_o                y la capacidad lo acota
```

**Cómo se cuenta:** «Cada pieza-ciudad es un MILP pequeño —dos o tres ofertas—
que resuelve CBC en milisegundos. La binaria `u_o` es lo que permite modelar que
el flete se paga por activar al proveedor, no por unidad, y que el lote mínimo
solo obliga si efectivamente le compramos. Es la estructura de *fixed-charge*,
Balinski 1961. Forzamos un solo proveedor por orden, no por matemática sino para
que la orden sea ejecutable por una persona.»

### 3.5 Reparto del presupuesto — mochila 0/1

```
maximizar   suma_s ( costo_quiebre_s  −  costo_reposicion_s ) · v_s

sujeto a    suma_s costo_reposicion_s · v_s  <=  presupuesto

            v_s ∈ {0,1}
```

**Cómo se cuenta:** «Este es el único paso que mira todas las piezas a la vez.
Hasta aquí cada decisión era independiente. Es el problema de la mochila 0/1 —
Lorie & Savage, 1955, nacido en racionamiento de capital, no en logística. Y lo
resolvemos **exacto**, no con el algoritmo voraz: cuando las compras son
indivisibles, ordenar por rentabilidad por dólar y llenar puede dejar dinero mal
puesto. Una compra muy rentable y cara desplaza a varias baratas que juntas
rinden más.»

**El resultado:** «El presupuesto de 2.500 USD evita 12.486 USD de quiebre. Un
retorno de 5,1×. Y deja 3 reposiciones aplazadas por 1.117 USD, con 3.152 USD de
riesgo sin cubrir — cifra que sirve para pedir ampliación de presupuesto con
argumento, no con intuición.»

---

## 4. La calidad de los datos — cómo presentarla sin perder credibilidad

Esta es la sección donde se gana o se pierde la sala. **Adelantarse a la crítica
es más fuerte que defenderse de ella.**

### 4.1 De dónde salen los datos

El histórico de consumo es **B2B-Parts-Rec** (Zenodo 19492687, licencia
CC-BY-4.0): un libro de órdenes real y anonimizado de distribución de repuestos
industriales. Se toma un solo cliente, `7478E086CC`, y se parte por línea de
negocio: la línea mayor se asigna a Nava y las 53 restantes a Ciudad Obregón. No
se usan dos clientes distintos porque su catálogo solapa solo un 41 %, y dos
plantas que casi no comparten refacciones no permiten comparar nada.

| Dato | Origen | Calidad |
|---|---|---|
| Historia de consumo (72 meses, 2024-01 a 2029-12) | Órdenes reales del libro B2B | **Real** |
| Precios unitarios | Órdenes reales | **Real** |
| Qué pieza va con qué máquina | Órdenes reales | **Real** |
| Familia de la pieza | Derivada por rango de precio contra una composición declarada de 9 familias | Calculada |
| Criticidad | Derivada del nº de máquinas que dependen de la pieza, por cuota 8/30/62 % | Calculada |
| Patrón de demanda | Derivado del histórico (cuadrante SBC) | Calculado |

**Escala del catálogo:** 876 referencias, 1.283 series pieza-planta, 92.376 filas
de historia mensual, precio unitario mediano 46 USD y máximo 11.193 USD.

### 4.2 Lo que es sintético — decirlo antes de que pregunten

**Cero filas de las 92.376 de historia mensual son simuladas.** Esa es la
diferencia con la versión anterior del MVP y conviene decirla con esas palabras.

Lo que sí se genera con semilla fija: el nombre legible de cada pieza (el dataset
trae identificadores anonimizados, no descripciones), la cantidad de cada evento
—binomial negativa de media `60 / precio^0,45`, porque el libro de órdenes trae
importes pero no siempre unidades—, el stock actual, el MOQ, la capacidad de
bodega y el flete.

Los seis proveedores son sintéticos pero **no arbitrarios**: se organizan en tres
niveles con plazos separados —OEM de importación 62-71 días, nacional 16-18,
local 6-7— y **la oferta se asigna por gama de precio, no al azar**. Un tornillo
de 2 USD con flete OEM de 180 USD volvía antieconómico todo el catálogo barato, y
eso era un artefacto del generador, no un hallazgo.

> **Frase para la presentación:** «El consumo es real y el precio es real. Lo
> sintético está en la envoltura logística —stock actual, lote mínimo, flete— y
> está marcado en la interfaz. Las decisiones del optimizador son correctas *dado
> ese dato*, pero no son órdenes de compra reales. Lo digo explícitamente para
> que nadie confunda el ejercicio con una recomendación operativa.»

### 4.3 Los hallazgos de la limpieza — presentarlos como fortaleza

La Etapa 0 parte de **219.777 filas crudas** y deja 219.359. Los descartes no son
ruido de formato: son problemas que sesgaban cifras concretas.

| Problema | Tratamiento | Impacto |
|---|---|---|
| Órdenes canceladas contadas como entregas | Filtradas por estado | Sesgaban el lead time a la baja |
| Órdenes sin fecha de pedido o de entrega | Descartadas | Sin fechas no hay plazo medible |
| `Defective_Units` nulo | Imputado cero | La ausencia significa que no se reportaron |
| Mes con un solo día registrado | Descartado | Se leería como caída de demanda |
| Referencias con menos de 8 eventos en 72 meses | Descartadas del catálogo | Una serie de 3 puntos no admite ninguna clasificación |
| Piezas de precio unitario < 0,50 USD | Descartadas | Producían órdenes de 0 USD y decisiones sin sentido |

**Dos decisiones que demuestran criterio:**

1. **Los atípicos de sensor se marcan, no se eliminan.** Una vibración o
   temperatura extrema suele ser justamente la señal de que la máquina va a
   fallar — el evento que anticipa el consumo. Borrarlas eliminaría la
   información más valiosa del conjunto.

2. **Los meses de consumo atípico se reportan, no se corrigen**, evaluados contra
   la propia serie y no contra el conjunto, porque una pieza de 100 unidades al
   mes y otra de 2 tienen escalas incomparables. Requieren confirmación de
   mantenimiento: puede haber sido una parada mayor real.

### 4.4 El perfil del catálogo: intermitente, y eso cambia el método

**Esta era la limitación honesta de la versión anterior y ya no lo es.** El MVP
corría antes sobre 40 piezas de consumo prácticamente continuo —3,3 % de meses en
cero, ADI mediano 1,00— que es el perfil de un insumo, no el de una refacción. La
crítica que un experto haría era exactamente esa, y la migración a B2B-Parts-Rec
se hizo para responderla.

| Métrica | Antes (40 piezas) | **Ahora (876 piezas)** | Esperado en MRO real |
|---|---|---|---|
| Meses con demanda cero | 3,3 % | **87,0 %** | 40-70 % |
| ADI mediano | 1,00 | **10,29** | > 1,32 |
| CV² mediano del evento | 0,11 | **0,40** | — |
| Demanda media | 18,3 u/mes | **2,74 u/mes** | 0,1-3 u/mes |
| Tamaño mediano del evento | — | **11 u** | — |
| Cuadrante SBC | 38 de 40 «suave» | **804 intermitentes · 479 irregulares · 0 suaves** | mayoría lumpy/intermitente |
| Referencias | 40 | **876** | cientos a miles |
| Filas de historia simuladas | mayoría | **0 de 92.376** | — |

> **Frase para la presentación:** «El catálogo ahora tiene el perfil que la
> literatura describe: la mayoría de los meses no pasa nada, y cuando pasa se
> lleva once unidades de golpe. Eso no es un dato peor, es el dato correcto — y
> obligó a cambiar cinco cosas del sistema, porque los métodos que funcionaban
> con consumo continuo fallan aquí de formas que solo se ven con este dato.»

### 4.5 Los cinco fallos que el dato intermitente destapó

Esta es la sección más fuerte de la presentación técnica, porque son fallos
**medidos y corregidos**, no anticipados en abstracto.

| # | Qué falló | Por qué | Cómo se corrigió |
|---|---|---|---|
| 1 | **El 86 % de las series proyectaba demanda cero** | La mediana móvil de una serie con 87 % de ceros es cero | Croston y Croston-SBA, con la clasificación SBC decidiendo cuál |
| 2 | **La valoración del quiebre descontaba dos veces la rareza** | Multiplicaba por la tasa de salida una exposición que ya se deriva de la cobertura | `P(Poisson) × costo del evento`, con costo por evento (45.000 / 4.000 / 250 USD) y no por día |
| 3 | **El 94 % de las series se marcaba para revisión humana** | El score de confianza usaba el CV de la serie completa, que sobre 87 % de ceros mide los huecos y no la incertidumbre del tamaño | En régimen intermitente usa el CV del tamaño de evento (confianza media 0,42 → **0,75**) |
| 4 | **El inventario mínimo estaba inflado un 49 %** | La aproximación normal, centrada en una media pequeña con desviación grande, pone **una mediana del 39 % de su masa en demanda negativa** y compensa esa masa imposible estirando la cola derecha | Cuantil de una binomial negativa ajustada a la media y varianza compuestas: 16.241 u / 1,34 M USD → **7.789 u / 683 k USD**, al mismo nivel de servicio |
| 5 | **Las 876 piezas caían en clase N de FSN** | Los umbrales eran de consumo continuo (fracción de días con salida: 0,003 a 0,08 para todas) | Fracción de **meses** con movimiento: F ≥ 25 %, S 8-25 %, N < 8 % |

> **Frase para la presentación, sobre el punto 4:** «Este es el que más me
> interesa contar, porque **yo esperaba lo contrario**. La hipótesis era que un
> cuantil correcto subiría el inventario mínimo respecto de la aproximación
> normal. La medición dijo que lo baja, en dos de cada tres series, y la causa es
> que la normal reparte probabilidad sobre demanda negativa —más del 20 % de la
> masa en el 99 % de las series— y la compensa por el lado derecho. No era
> conservadora, era inválida. Lo digo así porque la diferencia entre un modelo
> defendible y uno decorativo es exactamente esto: que la medición pueda
> contradecir a quien lo escribió.»

### 4.6 El hallazgo del modelo — no taparlo

El WMAPE del modelo es **180 %**, y esa cifra por sí sola parece descalificarlo.
No lo hace, pero hay que saber explicar por qué.

**Por qué el WMAPE es tan alto:** divide el error absoluto entre el total
consumido. Con el 87 % de los meses en cero, cualquier unidad pronosticada en un
mes vacío es error puro sin nada que la compense, y el denominador es pequeño
porque casi todos los meses aportan cero. Un WMAPE superior al 100 % es el
resultado normal de esta métrica sobre demanda intermitente, para **cualquier**
método: el promedio móvil marca 160 % y repetir el último mes, 189 %.

**La trampa que hay detrás, y que conviene contar:** las métricas construidas
sobre error absoluto —WMAPE y también MASE— se minimizan con la **mediana**, y
sobre estas series la mediana es cero. Un pronosticador que dijera que ninguna
pieza se consume nunca, y que dejaría las dos plantas sin refacciones, puntúa
**mejor** que cualquier método honesto. Por eso la comparación se hace con las
métricas que se minimizan con la **media**, que es lo que la política de
inventario consume:

| Método | RMSE | MASE | Sesgo acumulado en 6 meses |
|---|---|---|---|
| **Modelo (gradient boosting + estadístico)** | **16,53** | 0,842 | **+351 u** |
| Promedio móvil 6 meses | 17,28 | **0,746** | **−4.125 u** |
| Repetir el último mes | 23,58 | 0,882 | −321 u |

> **Frase para la presentación:** «El promedio móvil gana en las métricas de
> error absoluto y pierde en las dos que importan. Su sesgo acumulado es de
> **menos 4.125 unidades** sobre 7.698 observaciones de validación: al cabo de
> seis meses habría dejado a las plantas cortas en cuatro mil piezas. El modelo
> se queda en +351. Cuando la métrica y la consecuencia operativa apuntan en
> direcciones distintas, la que manda es la consecuencia.»

---

## 5. El trade-off central: criticidad contra paro de producción

Esta es la conversación que hay que provocar, porque es donde el sistema aporta
más y donde la organización tiene los datos que le faltan.

### 5.1 La asimetría que nadie mide

| | Sobrestock | Stockout |
|---|---|---|
| **Cuándo se ve** | Nunca, o al hacer inventario anual | Inmediato |
| **Quién lo sufre** | Finanzas, difuso | Producción, concreto |
| **Cuánto cuesta** | Costo de capital 15–30 % anual + obsolescencia | Paro de línea: **cientos de USD por hora** |
| **Quién lo reporta** | Nadie | Todos |

**El resultado predecible:** la organización sobre-compra sistemáticamente,
porque solo uno de los dos costos tiene doliente.

### 5.2 Cómo el sistema lo pone en la misma moneda

```
Costo_quiebre  =  ( 1 − exp( −d · dias_expuestos ) )  ×  c_evento(criticidad)
                  └──────────────┬─────────────────┘
                  probabilidad de que llegue al menos
                  un pedido durante la exposición (Poisson)
```

| Símbolo | Qué es | Unidad | Valor |
|---|---|---|---|
| `dias_expuestos` | Días de quiebre que evita reponer ahora en vez de esperar a la siguiente corrida | días | Calculado |
| `d` | Demanda media diaria proyectada de la pieza | unidades/día | Por serie |
| `c_evento` | Costo de **un** evento de quiebre según criticidad | USD/evento | A = 45.000 · B = 4.000 · C = 250 |

**La corrección que hubo que hacer, y que vale la pena contar:** «La versión
anterior multiplicaba los días expuestos por la tasa de salida de la pieza, con
el argumento de que un día sin existencias solo cuesta si ese día alguien la
pide. El argumento es correcto pero **la rareza ya estaba descontada**: los días
expuestos se calculan sobre la cobertura, que se deriva de la demanda proyectada,
de modo que una pieza rara ya aparecía con menos días. Multiplicar otra vez por
la rareza la descontaba dos veces, y con este catálogo el efecto fue visible al
instante: el quiebre mediano valía 0,00 USD y el sistema no compraba nada.

Ahora la probabilidad de que ocurra al menos un pedido durante la exposición se
calcula con un proceso de Poisson, que es el modelo estándar de llegadas, y se
multiplica por lo que cuesta **un evento**, no un día. Parar una línea de
embotellado no cuesta 400 USD: cuesta el turno perdido.»

### 5.3 La pregunta que hay que hacerle a la sala

> **«Los 45.000 USD por evento de una pieza crítica son un parámetro que pusimos
> nosotros. ¿Cuánto cuesta realmente una hora de paro en Nava? Esa cifra la tiene
> operaciones, y cambiaría el orden de prioridades del sistema entero.»**

Esto convierte la presentación de un monólogo en una conversación, y traslada la
decisión a quien tiene el dato — que es donde debe estar.

### 5.4 La relación de dualidad (para audiencia técnica)

Fijar un nivel de servicio y fijar un costo de faltante **son el mismo acto**:

```
b  =  ( h · Q )  /  ( D · ( 1 − alpha ) )
```

| Símbolo | Qué es | Unidad |
|---|---|---|
| `b` | Costo de faltante por unidad **implícito** en el servicio declarado | USD/unidad |
| `h` | Costo de mantener inventario por unidad y año | USD/unidad/año |
| `Q` | Cantidad de reposición | unidades |
| `D` | Demanda anual | unidades/año |
| `alpha` | Nivel de servicio declarado | fracción 0–1 |

> «Cuando alguien dice "quiero 98 % de servicio", está declarando implícitamente
> cuánto cree que cuesta un quiebre, aunque no lo sepa. Esta fórmula, corrida al
> revés, revela ese número y permite contrastarlo con lo que operaciones dice que
> cuesta parar la línea. Si el sistema asume unos pocos dólares por unidad
> faltante y operaciones dice que el turno perdido son decenas de miles, el nivel
> de servicio está gravemente mal calibrado — y esa discrepancia es exactamente
> la conversación que hay que provocar.»

### 5.5 La composición del catálogo, en una frase

> «**44 piezas** —el 5 % de las referencias— son a la vez clase A de valor y
> criticidad A: mueven el 9,8 % del gasto anual *y* paran una línea si faltan. Ahí
> es donde el sistema se paga solo. En el otro extremo, **201 referencias** son el
> 23 % de la variedad y el 3,7 % del valor: ahí la política correcta es stock
> generoso y dejar de pensar en ellas.»

**Y la celda que solo aparece al cruzar las tres dimensiones:** hay **19 piezas de
criticidad A en clase N de rotación** — se mueven en menos del 8 % de los meses.
ABC las ignoraría por valor y FSN las marcaría como candidatas a depurar. Las dos
lecturas se equivocan a la vez, porque paran una línea cuando faltan y, al moverse
tan poco, es cuando más probable es que nadie se haya acordado de reponerlas.

---

## 6. Preguntas frecuentes y cómo responderlas

Organizadas por quién las hace.

---

### 6.1 Sobre el pronóstico

**P: ¿Cómo uso la proyección si un mes o dos no se consume nada y son cero? ¿Son
estacionales o simplemente no se usaron?**

La distinción la hace el sistema con dos pruebas independientes, no con
intuición:

1. **La clasificación de patrón** mide si esos ceros siguen un ciclo anual. Un
   cero de julio que se repite todos los años es estacionalidad; un cero suelto es
   intermitencia. La prueba de Kruskal-Wallis compara los 12 grupos de meses: si
   el mes del año explica la diferencia, `p < 0,05` y la serie se marca
   Estacional. Si no, los ceros son ruido y la serie va a Estable o Volátil.

2. **El método se elige en consecuencia.** Una serie con ceros dispersos va a
   *Volátil*, que usa **percentiles empíricos** en lugar de la media —
   precisamente para que unos meses en cero no arrastren la proyección hacia
   abajo.

**Lo que esto obligó a implementar:** con muchos ceros —aquí son el 87 % de los
meses— ningún método clásico funciona, y hay que pasar a **Croston** o **SBA**,
que descomponen la serie en *cada cuánto ocurre* y *cuánto se lleva cuando
ocurre*, y suavizan cada parte por separado. **Están implementados y son el
camino por defecto de este catálogo**: las 1.283 series se proyectan por uno de
los dos. No es una mejora pendiente, es lo que hace que el sistema compre algo.

**Y una salvaguarda que sí existe:** si una serie tiene menos de 6 meses de
historia o media cero, se marca `Insuficiente`, **no se proyecta automáticamente**
y la decisión pasa al comprador. El sistema prefiere no responder a responder mal.

---

**P: ¿Qué tan confiable es la proyección? ¿Cómo lo sé pieza por pieza?**

Cada serie lleva un **score de confianza de 0 a 1** que combina tres factores:

```
confianza  =  0,30 · volumen_de_historia  +  0,45 · volatilidad  +  0,25 · estabilidad_reciente
```

La volatilidad pesa más porque es lo que más degrada la precisión. Y ese score
**se penaliza después** con el error realmente medido: si el método falló en la
validación retrospectiva —WMAPE > 50 %— la confianza se multiplica por 0,65.

Toda serie con confianza < 0,5 se marca `needs_review = 1` y la interfaz la pone
en la banda de «requiere una persona». Hoy son el **1,3 %** de las 1.283 series,
con una confianza media de 0,75.

**Un ajuste que hubo que hacer con el dato intermitente:** el término de
volatilidad usaba el coeficiente de variación de la serie completa, que sobre
87 % de ceros mide el patrón de huecos y no la incertidumbre del tamaño del
pedido. Marcaba el **94 %** del catálogo para revisión, que en la práctica es no
marcar nada. En régimen intermitente ahora usa el CV del tamaño de evento, y la
confianza media pasó de 0,42 a 0,75.

---

**P: ¿Cómo validan que el modelo sirve y no está sobreajustado?**

Tres controles:

1. **Validación retrospectiva con origen móvil.** Se reservan los últimos 6 meses
   y se re-proyecta cada uno usando *solo* información anterior a ese mes. Nunca
   se evalúa sobre datos que el método vio.
2. **Partición temporal, no aleatoria**, en el modelo de ML. Una partición
   aleatoria dejaría meses futuros en el entrenamiento y daría una métrica
   optimista insostenible en producción.
3. **Dos referencias obligatorias:** repetir el último mes, y el promedio móvil.
   Un modelo que no supera al promedio móvil no justifica su existencia — y
   reportamos que apenas lo supera por 3,2 %.

---

**P: ¿Por qué WMAPE y no MAPE?**

Porque la demanda de refacciones tiene meses en cero. El MAPE clásico divide mes
a mes entre el valor real, así que un cero lo vuelve infinito. La alternativa
sería descartar esos meses, que son justamente los más informativos. WMAPE pone
el total en el denominador una sola vez y admite ceros individuales.

---

### 6.2 Sobre el inventario mínimo y máximo

**P: ¿Cómo se obtiene actualmente el inventario mínimo?**

```
mu_LT  =  d · L                            consumo esperado durante el plazo
Var_LT =  L · sigma_d²  +  d² · sigma_L²   varianza compuesta

Imin   =  cuantil( alpha(k) ) de una binomial negativa ajustada a mu_LT y Var_LT
```

En palabras: **lo que espero consumir mientras llega el pedido, más un colchón
que absorbe dos incertidumbres a la vez** — que la demanda sea mayor de lo
previsto y que el proveedor entregue más tarde de lo habitual.

Con números reales del sistema: lead time ponderado 30,0 días, σ del lead time
11,07 días.

**La media y la varianza son las estándar de la industria**, Hadley & Whitin
1963, las mismas que usan los módulos MRP de SAP y Oracle. Lo que este proyecto
cambió es el último paso: en vez de leer el cuantil sobre una normal, se lee
sobre una binomial negativa ajustada a esa media y esa varianza, porque con
demandas de dos o tres unidades la normal reparte una parte grande de su
probabilidad sobre demanda negativa. Ver §3.3 y §9.4.8 para la medición.

---

**P: ¿Cómo se obtiene el inventario máximo?**

```
Imax  =  max( Imin ,  ceil( demanda_mensual × 3 ) )
```

Es una **cobertura objetivo de 3 meses** sobre la demanda proyectada, nunca por
debajo del mínimo (un máximo menor que el mínimo dejaría el problema sin
solución). Se define así, y no como un número fijo por pieza, para que **escale
solo** cuando la demanda cambie.

**El límite honesto:** los 3 meses son un parámetro de política, no un óptimo
derivado. La teoría clásica lo obtendría equilibrando costo de ordenar contra
costo de mantener —fórmula de Wilson/EOQ— usando el flete que ya está en los
datos. Esa derivación está identificada y no implementada.

**Hay un segundo techo**, además del de bodega: la **vida útil**. No se recomienda
comprar más de lo que la demanda proyectada alcanza a consumir antes de que la
pieza venza, con un margen de seguridad del 20 %.

---

**P: ¿Se cuenta con un colchón de seguridad para no parar producción?**

Sí, y **está diferenciado por criticidad**, que es el punto:

| Criticidad | `z` | Nivel de servicio |
|---|---|---|
| A · para línea | 1,65 | **95 %** |
| B · importante | 1,28 | 90 % |
| C · rutinaria | 0,84 | 80 % |

Una pieza crítica lleva casi el doble de colchón que una rutinaria con la misma
variabilidad. Es la traducción directa de «esta pieza no puede faltar» a un
número.

**La limitación que hay que declarar:** hoy esos tres valores están **fijados por
constante**, no derivados del costo real de parar una línea. Y hay una
**incoherencia entre etapas**: el cálculo del mínimo protege la criticidad A al
95 %, pero el reparto del presupuesto puede aplazar justamente una pieza crítica
si otras rinden más por dólar. **Está identificado como mejora prioritaria** — ver
§14 del spec: subir la continuidad de producción a restricción dura.

---

**P: ¿Por qué reponen hasta un nivel objetivo y no hasta el mínimo?**

Porque reponer justo hasta el mínimo deja la pieza al borde del quiebre y obliga
a comprar otra vez el mes siguiente, **pagando otro flete y otra gestión**. El
nivel objetivo suma al mínimo 1,5 meses de demanda proyectada. Es una política
**order-up-to** estándar.

---

### 6.3 Sobre el ahorro y la justificación económica

**P: ¿Cuánto me reduce este sistema en costo frente a simplemente comprar cuando
llegue a un límite mínimo?**

Es la pregunta correcta, y la respuesta honesta tiene tres partes.

**1. Si el «límite mínimo» es un número fijo puesto a mano, la ganancia es
grande y medible.** Un mínimo estático no se entera de que la demanda cambió, no
distingue criticidad y no incorpora la variabilidad del proveedor. El sistema:

- Recalcula el mínimo cada corrida contra la demanda proyectada.
- Diferencia el colchón por criticidad (95/90/80 %).
- Incorpora σ del lead time, que **con σ/μ ≈ 0,37 aporta una parte sustancial de
  la varianza**. Un mínimo fijo que ignore esto queda corto.

**2. Donde el sistema gana con seguridad es en las tres decisiones que un
min-max simple no toma:**

| Decisión | Min-max simple | StockOpt |
|---|---|---|
| **A qué proveedor comprar** | No decide | MILP compara precio + flete + MOQ + capacidad |
| **Cuánto comprar** | Un lote fijo | Nivel objetivo derivado de la demanda, acotado por vida útil |
| **Qué hacer si no alcanza el dinero** | Nada, o por orden de llegada | Mochila que maximiza beneficio neto |
| **Qué pasa si el MOQ excede el máximo** | Compra o no compra a ciegas | Estado `REVISAR` con las dos salidas y su costo |

**3. La cifra concreta de la corrida actual:** con 2.500 USD de presupuesto se
evitan **12.486 USD de quiebre** — retorno de **5,1×**. Y quedan 3.152 USD de
riesgo identificado sin cubrir, que es información que un min-max nunca produce.

**La salvedad que hay que decir:** «Estas cifras son sobre dato parcialmente
sintético. Lo defendible es la **arquitectura**; el ahorro real hay que medirlo
contra la operación durante unos meses, y para eso hace falta cerrar el bucle de
feedback, que aún no existe.»

---

**P: ¿Cuánto tendría que subir el presupuesto para que no quede nada aplazado?**

Hoy: **1.117 USD adicionales** cubrirían las 3 reposiciones aplazadas, que
representan 3.152 USD de riesgo de quiebre. Es decir, **2,8 USD de riesgo evitado
por cada USD adicional**.

Esa es exactamente la clase de pregunta que el chat de trazabilidad (§15 del
spec) contestaría de forma interactiva, re-corriendo la mochila con otro
presupuesto.

---

**P: ¿Cómo sé que el sistema no está sobre-comprando?**

Cuatro frenos explícitos:

1. **Inventario máximo** por cobertura de 3 meses.
2. **Tope por vida útil**: nunca más de lo consumible antes del vencimiento.
3. **Regla de beneficio neto**: si reponer cuesta más que el quiebre que evita, la
   decisión cambia a `NO_COMPRAR` con ese motivo explícito.
4. **Presupuesto de corrida** como restricción dura.

---

### 6.4 Sobre la operación y la confianza

**P: ¿Qué pasa cuando el sistema no puede decidir?**

Lo dice, en vez de fingir que sí. Hay **cuatro estados**, no dos:

| Estado | Significado |
|---|---|
| `COMPRAR` | Reposición recomendada con proveedor y cantidad |
| `NO_COMPRAR` | Con motivo: por encima del mínimo, sin proveedor, vida útil, o no rentable |
| `REVISAR` | **El sistema no decide**: el MOQ del proveedor supera el máximo de bodega |
| `APLAZADO` | Procedía pero no cupo en el presupuesto |

El estado `REVISAR` merece explicación: «Al implementar, 9 de 18 casos volvían
"no factible". No era un fallo del solver sino una **tensión real de compras**: un
O-ring se vende en lotes de 100 pero solo caben 48. Devolver "infactible"
escondía la decisión. Ahora el sistema resuelve igualmente, informa cuánto
costaría y cuántos meses de inventario dejaría, y lo marca para que decida el
comprador. Es el 39 % de lo accionable.»

---

**P: ¿Quién decide finalmente, la IA o la persona?**

| La IA | La persona |
|---|---|
| Proyecta demanda | Revisa excepciones |
| Calcula umbrales de inventario | Aprueba compras sensibles |
| Evalúa proveedor óptimo | Ajusta reglas de negocio |
| Genera la explicación | Valida calidad de datos |

**El LLM no decide nada.** Solo explica con base en la evidencia del forecast, del
optimizador y de las reglas aplicadas. Toda decisión pasa por aprobación humana
con flujo de estados auditado: `Pendiente → Aprobado → Contactado proveedor →
Orden confirmada`.

---

**P: ¿Puedo auditar por qué se tomó una decisión concreta?**

Cada fila lleva su motivo en lenguaje natural con las cifras que lo sustentan.
Ejemplo real del sistema:

> «Quedan 5 unidades y el mínimo es 10. Con una demanda proyectada de 17,1 al mes
> se repone hasta 35 unidades, equivalente a 2,0 meses de consumo. Se eligió Alpha
> Inc. por menor costo total entre 3 opciones que surten NAVA.»

**Lo que falta, y hay que decirlo:** un `run_id` que identifique contra qué
corrida se decidió. Con la mochila es necesario, porque una fila está `APLAZADO`
**por lo que consumieron las demás** — sin saber la corrida, ese motivo no se
puede reconstruir. Está identificado como mejora prioritaria.

---

**P: ¿Por qué no usaron Prophet / redes neuronales / algo más moderno?**

Por tres razones, en orden de peso:

1. **Prophet sobreajusta con 3 ciclos de historia** y exige compilar Stan, lo que
   en Windows complica la demo. Holt-Winters viene en statsmodels, ya instalado, y
   es igual de explicable.
2. **El modelo de gradient boosting que sí entrenamos apenas supera al promedio
   móvil.** Con series mayormente planas no hay estructura que aprender. Añadir
   más capacidad de modelo no arregla la falta de señal.
3. **La explicabilidad es requisito, no adorno.** Un comprador no ejecuta lo que
   no entiende, y todo el argumento del sistema es la trazabilidad.

**La mejora real de pronóstico no está en el modelo, está en los datos:** órdenes
de trabajo programadas, paros de planta, horas de operación de la máquina, plan
de producción. Hoy el modelo solo mira su propio pasado.

---

**P: ¿Esto funciona para nuestra industria?**

Las 20 referencias son **MRO industrial genérico** —rodamientos, sellos, bandas,
filtros, acoplamientos, sensores, tornillería— presentes en cualquier planta con
motores, bombas y transportadores. El rodamiento 6205 es la referencia más común
del mundo.

**Lo que faltaría para una cervecera** (decirlo antes de que lo pregunten):
sellos sanitarios, válvulas mariposa y de asiento, mangueras grado alimenticio,
empaques de intercambiador de placas, y materiales certificados —acero 316L,
elastómeros EPDM/FKM— que cambian por completo el proveedor y el precio. Además,
la estacionalidad real de producción cervecera, que el histórico actual no tiene.

---

### 6.5 Sobre limitaciones y siguientes pasos

**P: ¿Cuál es la mayor debilidad del sistema hoy?**

Tres, en orden:

1. **No hay autenticación**, así que la traza de auditoría no prueba quién
   aprobó qué. Bloquea enseñárselo a un cliente en producción.
2. **Las aprobaciones no persisten**: la base se hornea en la imagen del
   contenedor y el apagado nocturno las borra. Para un producto cuyo argumento es
   la trazabilidad, es el fallo más grave.
3. **No existe el bucle de feedback.** Sin comparar la demanda real contra la
   proyectada y la compra ejecutada contra la recomendada, el sistema no aprende.

---

**P: ¿No sería más barato mover stock entre plantas que comprar?**

Sí, y está medido: **11 piezas** están en esa situación, por unos **2.860 USD** de
compra evitable — más que el presupuesto entero de la corrida. Una de ellas está
aplazada por falta de presupuesto mientras la otra planta tiene ocho unidades
sobre su mínimo.

Un traslado paga flete pero no precio de compra, así que **bajo restricción de
presupuesto es estrictamente más barato**. No está implementado.

**La advertencia honesta:** el excedente medido es *stock por encima del mínimo*,
así que moverlo entero dejaría a la planta de origen sin colchón. El modelo
tendría que respetar el mínimo de las dos.

---

**P: El horizonte es de un mes. ¿No debería considerar varios?**

Correcto, y es una limitación declarada. El sistema decide como si cada mes fuera
independiente: no hay noción de que comprar hoy afecta la decisión del mes
siguiente, ni de trayectoria de inventario. La formulación dinámica —Scarf 1960,
optimalidad de las políticas (s,S)— existe y es tratable; queda fuera del alcance
del MVP.

---

**P: ¿Qué sigue?**

En orden de lo que bloquea, no de lo que sería vistoso:

1. Autenticación y persistencia fuera de la imagen — sin eso no hay auditoría.
2. `run_id` en cada decisión — barato, y sin él la mochila no es reconstruible.
3. **Validar `c_evento(k)` con mantenimiento.** Es el parámetro que más manda
   sobre las prioridades del sistema y hoy es una declaración nuestra.
4. **Deconvolucionar el lote de compra**: el histórico registra lo que se pidió,
   no lo que se consumió, y eso infla el tamaño del evento.
5. **Ajustar `alpha` de Croston por serie** — hoy es una constante única para todo
   el catálogo, y es la mejora de mayor retorno esperado en el pronóstico.
6. **Chat de trazabilidad** para responder contrafactuales: «¿cuánto presupuesto
   necesito para no aplazar nada?» (§15 del spec).
7. Bucle de feedback — lo que convierte el MVP en un sistema que aprende.
8. Traslado entre plantas — el ahorro está medido.
9. Variables externas en el modelo — la vía con más recorrido para el forecast.

**Ya no está en esta lista, y conviene decirlo:** la continuidad de producción
como restricción dura (§14 del spec) **está implementada**. Las piezas de
criticidad A se financian antes de que la mochila reparta nada, con un excedente
autorizado y acotado por encima del presupuesto, y cuando ni así alcanzan, la
decisión no es «aplazado» sino `ESCALAR` — que es una petición explícita de más
presupuesto y no un silencio.

---

## 7. Guion de 10 minutos

| Min | Bloque | Mensaje clave |
|---|---|---|
| 0–2 | **El problema** | «Dos costos opuestos, uno con doliente y otro sin él» |
| 2–3 | **Los datos** | «876 referencias, 72 meses, cero filas de consumo simuladas — y el 87 % de los meses en cero» |
| 3–4 | **La composición** | «El 36 % de las referencias es el 80 % del gasto; el 8 % para línea» |
| 4–6 | **Cómo decide** | Las cuatro fórmulas: Croston, inventario mínimo, MILP, mochila |
| 6–7 | **El resultado** | «40.000 USD evitan 511.000 de quiebre, y las 11 reposiciones críticas quedan financiadas» |
| 7–9 | **Los fallos que el dato destapó** | Los cinco de §4.5 — con el del inventario mínimo, donde la medición contradijo la hipótesis |
| 9–10 | **La pregunta** | «¿Cuánto cuesta realmente una hora de paro en Nava?» |

Si la audiencia es de producto o de negocio y no de datos, cambia el bloque de
7-9 por **§10, el diseño de la pantalla**: los tres semáforos, por qué el titular
es el peor de ellos, y qué se quitó de la lista para que deje de haber fatiga de
alertas.

**Cierre sugerido:**

> «Lo que este MVP demuestra es que se puede ir de datos operativos a una
> recomendación de compra explicable y auditable, con trazabilidad suficiente para
> que un comprador la defienda. Lo que **no** demuestra todavía es el ahorro real
> en operación — para eso hace falta el bucle de feedback y unos meses de datos
> reales. Y hay una cifra que ustedes tienen y nosotros no: **el costo real de un
> paro de línea**. Ese número reordena las prioridades del sistema entero.»

---

## 8. Material de apoyo

| Documento | Para qué |
|---|---|
| [`docs/diagnostico-piezas.html`](diagnostico-piezas.html) | Gráficas de composición, matriz criticidad × valor, FSN, calidad del dato |
| [`Spec.md` §13](../Spec.md) | Formulación matemática completa con glosarios |
| [`Spec.md` §13.11](../Spec.md) | Mapa fórmula → archivo → función |
| [`Spec.md` §13.12](../Spec.md) | Los supuestos del modelo y su consecuencia si fallan |
| [`Spec.md` §13.13](../Spec.md) | Diagnóstico del dataset: el perfil medido, antes y después de la migración |
| [`Spec.md` §14](../Spec.md) | Diseño: continuidad de producción como restricción dura |
| [`Spec.md` §15](../Spec.md) | Diseño: chat de explicabilidad y trazabilidad |
| [`Spec.md` §16](../Spec.md) | Diseño: la pantalla del turno como soporte de decisión |
| [§10 de esta guía](#10-la-pantalla-cómo-se-defiende-el-diseño) | Cómo defender el diseño de la interfaz |

---

## 9. Formulario técnico del pipeline — cada fórmula explicada

Esta sección es el respaldo matemático de la guía. Contiene **todas las fórmulas**
que el sistema aplica, en el orden en que se ejecutan, con su justificación, fuente
bibliográfica, glosario completo de símbolos y las condiciones bajo las cuales deja
de ser válida. Úsala cuando la audiencia es técnica o cuando alguien pregunta
«¿de dónde salió ese número?».

---

### 9.1 Etapa 0 · Limpieza de fuentes

#### 9.1.1 Banda intercuartílica de Tukey

**Qué hace:** Marca una observación como atípica si cae fuera del intervalo
`[Q1 − 1,5·RIC , Q3 + 1,5·RIC]`.

```
x ∉ [Q1 − 1,5·IQR ,  Q3 + 1,5·IQR]  ⟹  outlier
```

| Símbolo | Qué es | Unidad |
|---|---|---|
| `Q1, Q3` | Primer y tercer cuartil de la columna | unidad de la columna |
| `IQR` | Rango intercuartílico, Q3 − Q1 | unidad de la columna |
| `1,5` | Ancho de la banda. Convención de Tukey para atípico leve | adimensional |

**Fuente:** Tukey, J.W. (1977). *Exploratory Data Analysis*. Addison-Wesley.

**Por qué se usa:** No asume distribución normal. Funciona razonablemente bien con
colas asimétricas, que son la norma en datos de consumo de refacciones.

**Cuándo falla:** Si más de un cuarto de las observaciones son extremas, los
cuartiles se desplazan y el criterio se vuelve demasiado permisivo. Por eso no se
usa solo.

---

#### 9.1.2 Z-score modificado sobre la desviación absoluta mediana (MAD)

**Qué hace:** Compara cada valor con la mediana usando la MAD como escala. Si el
score supera 3,5, la observación se marca.

```
Mᵢ  =  0,6745 · (xᵢ − x̃) / MAD   >  3,5  ⟹  outlier
```

| Símbolo | Qué es | Unidad |
|---|---|---|
| `xᵢ` | Valor observado | unidad de la columna |
| `x̃` | Mediana de la columna | unidad de la columna |
| `MAD` | Mediana de `|xᵢ − x̃|` | unidad de la columna |
| `0,6745` | Factor de escala que hace la MAD comparable a una desviación estándar bajo normalidad | adimensional |
| `3,5` | Umbral de corte | adimensional |

**Fuente:** Iglewicz, B. & Hoaglin, D.C. (1993). *How to Detect and Handle Outliers*.
ASQC; reproducido en NIST/SEMATECH e-Handbook of Statistical Methods.

**Por qué se usa:** Usa la mediana en lugar de la media, por lo que unos pocos
valores extremos no desplazan el criterio. Es robusto donde el IQR empieza a fallar.

**Cuándo falla:** Cuando más de la mitad de las observaciones son idénticas —caso
habitual en refacciones con muchos ceros— la MAD vale cero y la división indefine
el score. El código detecta esta situación y recurre a la desviación media absoluta
respecto de la mediana, que conserva la robustez.

---

#### 9.1.3 Mínimo de días registrados por mes

**Qué hace:** Descarta un mes completo si tiene menos de 20 días con registro.

```
días_registrados_en_el_mes < 20  ⟹  mes descartado
```

| Símbolo | Qué es | Unidad |
|---|---|---|
| `20` | Umbral de días por debajo del cual el mes no es evidencia de demanda | días/mes |

**Fuente:** Regla operativa declarada para este conjunto de datos.

**Por qué se usa:** Un mes con un solo día registrado se leería como una caída
brusca de la demanda. Descartarlo elimina una señal falsa, no información real.

---

### 9.2 Etapa 1 · Ingesta y validación

#### 9.2.1 Integridad referencial del dataset

**Qué hace:** Bloquea el pipeline antes de procesar si alguna de estas condiciones
falla.

```
precio ≥ 0 ,   MOQ ≥ 1 ,   L > 0 ,   qty ≥ 0 ,   ∀ s : |O(s)| ≥ 2
```

| Símbolo | Qué es | Unidad |
|---|---|---|
| `precio` | Precio unitario de una oferta | USD/unidad |
| `MOQ` | Cantidad mínima de orden | unidades |
| `L` | Lead time del proveedor | días |
| `qty` | Cantidad en cualquier fila de inventario o demanda | unidades |
| `\|O(s)\|` | Número de ofertas que pueden servir la serie `s` | ofertas |

**Fuente:** Reglas duras de negocio declaradas para el proyecto.

**Por qué se usa:** La última regla es la que más importa para el optimizador: con
una sola oferta no hay nada que elegir, y el modelo de selección de proveedor se
reduce a aritmética. El optimizador necesita al menos dos alternativas para producir
una decisión defendible.

---

#### 9.2.2 Punto de reorden inicial del inventario sintético

**Qué hace:** Genera el stock de partida de cada serie usando el servicio declarado.

```
ROP  =  ceil( μ  +  z(k) · σ )
```

| Símbolo | Qué es | Unidad |
|---|---|---|
| `μ` | Consumo mensual medio de la serie | unidades/mes |
| `σ` | Desviación estándar del consumo mensual | unidades/mes |
| `z(k)` | Factor de servicio por criticidad: A 1,65 · B 1,28 · C 0,84 | adimensional |

**Fuente:** Aproximación normal estándar, con los mismos factores de servicio que
la política de inventario.

**Aclaración importante:** Este es solo el stock de arranque que escribe el build.
El punto de reorden real que el sistema calcula opera sobre el lead time verdadero
(días), no sobre el mes calendario. La fórmula completa está en §9.4.2.

---

### 9.3 Etapa 2 · Clasificación de patrones de demanda

#### 9.3.1 Cuadrante de intermitencia e irregularidad (SBC)

**Qué hace:** Decide, antes que cualquier otra prueba, si la serie se mueve todos
los meses o a intervalos. De esa respuesta depende que los estimadores clásicos
sirvan o devuelvan cero.

```
ADI  =  n / n_e ,     CV²  =  (σ_e / μ_e)²

ADI ≥ 1,32  ∧  CV² <  0,49   ⟹  Intermitente
ADI ≥ 1,32  ∧  CV² ≥ 0,49   ⟹  Irregular
```

| Símbolo | Qué es | Unidad |
|---|---|---|
| `n` | Meses de historia de la serie | meses |
| `n_e` | De esos, los meses con algún consumo | meses |
| `ADI` | Intervalo medio entre demandas: se mueve un mes de cada ADI | meses por evento |
| `σ_e`, `μ_e` | Desviación y media del tamaño del evento, medidas **solo** sobre los meses con consumo | unidades |
| `CV²` | Dispersión relativa al cuadrado del tamaño del evento | adimensional |
| `1,32` | Intervalo por encima del cual los estimadores clásicos dejan de funcionar | meses por evento |
| `0,49` | Dispersión por encima de la cual el tamaño deja de ser predecible | adimensional |

**Fuente:** Syntetos, A.A., Boylan, J.E. & Croston, J.D. (2005). On the
categorization of demand patterns. *Journal of the Operational Research Society*,
56(5), 495-503.

**Por qué se usa:** Las dos cifras miden cosas distintas a propósito, y ahí está
toda la regla. El intervalo cuenta los huecos; la dispersión mira solo los meses
que **no** son hueco. Un coeficiente de variación sobre la serie completa
mezclaría las dos, y con 87 % de ceros lo dominarían los huecos — que es
exactamente el error que hacía que el 94 % de este catálogo pareciera
impredecible antes de separarlas.

Los umbrales no son convencionales: el artículo los deriva del punto donde el
error cuadrático de cada estimador supera al de los otros.

**Medido en este catálogo:** ADI mediano 10,29 y CV² mediano 0,40. Las 1.283
series caen del lado intermitente — 804 intermitentes y 479 irregulares, ninguna
suave.

**Cuándo falla:** Con menos de dos eventos no hay dispersión que medir y la serie
va a «Historial insuficiente», que es una etiqueta propia y no un valor por
defecto. Es la primera de la precedencia, por delante de la intermitencia.

---

#### 9.3.2 Coeficiente de variación (CV)

**Qué hace:** Mide la dispersión relativa de la serie. Si CV > 0,5, la serie se
clasifica como Volátil.

```
CV  =  σ / μ ,    CV > 0,5  ⟹  Volátil
```

| Símbolo | Qué es | Unidad |
|---|---|---|
| `σ` | Desviación estándar del consumo mensual | unidades/mes |
| `μ` | Media del consumo mensual | unidades/mes |
| `CV` | Dispersión relativa, comparable entre piezas de cualquier escala | adimensional |
| `0,5` | Umbral de volatilidad declarado como política | adimensional |

**Fuente:** Estadística descriptiva clásica. Umbral declarado como política de
negocio, no estimado.

**Por qué se usa:** Dividir por la media hace que una pieza que mueve 100 unidades
al mes sea comparable con una que mueve 2. La desviación absoluta sola no sirve
para comparar piezas de distinta escala.

---

#### 9.3.3 Fuerza estacional de la descomposición

**Qué hace:** Mide qué fracción de la varianza de la señal (estacional + residuo)
se explica por el componente estacional. Si Fₛ ≥ 0,45, la condición de fuerza se
cumple.

```
Fₛ  =  1  −  Var(R) / Var(S + R) ,    Fₛ ≥ 0,45
```

| Símbolo | Qué es | Unidad |
|---|---|---|
| `S` | Componente estacional de la descomposición | unidades/mes |
| `R` | Residuo tras eliminar tendencia y estación | unidades/mes |
| `Fₛ` | Proporción de la varianza (S+R) explicada por la estación | 0 a 1 |
| `0,45` | Fuerza mínima para considerar estacional | adimensional |

**Fuente:** Wang, X., Smith, K. & Hyndman, R.J. (2006). Characteristic-based
clustering for time series data. *Data Mining and Knowledge Discovery*, 13(3).
Descomposición STL: Cleveland et al. (1990). *J. of Official Statistics*, 6(1).

**Por qué se usa:** Cuantifica cuánto de lo que varía en la serie es ciclo anual y
no ruido. La decomposición clásica extrae un componente estacional aparente incluso
de ruido puro con solo 3 ciclos de historia, de ahí que esta condición no sea
suficiente por sí sola.

**Cuándo falla:** Con 3 ciclos de historia la fuerza media de una serie de ruido
puro es 0,32 y supera 0,40 en el 26 % de los casos. Por eso se exige también la
prueba de Kruskal-Wallis.

---

#### 9.3.4 Prueba de efecto de mes (Kruskal-Wallis)

**Qué hace:** Verifica si el mes del calendario explica de forma estadísticamente
significativa las diferencias de consumo. Si p < 0,05, el efecto es real.

```
H  =  12/(N·(N+1)) · Σⱼ (Rⱼ² / nⱼ)  −  3·(N+1) ,    p < 0,05
```

| Símbolo | Qué es | Unidad |
|---|---|---|
| `N` | Total de observaciones de la serie | meses |
| `nⱼ` | Observaciones en el mes calendario j | meses |
| `Rⱼ` | Suma de rangos de las observaciones del mes j | rangos |
| `H` | Estadístico de prueba, aprox. chi-cuadrado con 11 grados de libertad | adimensional |
| `p` | Probabilidad de ver este efecto de mes por azar | 0 a 1 |

**Fuente:** Kruskal, W.H. & Wallis, W.A. (1952). Use of ranks in one-criterion
variance analysis. *J. of the American Statistical Association*, 47(260).

**Por qué se usa:** Opera sobre rangos, no sobre valores, así que no exige que la
demanda sea normal — y la demanda de refacciones no lo es. Es una ANOVA no
paramétrica de un factor.

**La combinación que importa:** La clasificación Estacional exige Fₛ ≥ 0,45 **Y**
p < 0,05 simultáneamente. Medido sobre 400 simulaciones, el falso positivo con
ambas condiciones baja del 26 % al 2 %.

---

#### 9.3.5 Score de confianza del patrón (γ)

**Qué hace:** Combina tres señales en un número de 0 a 1 que mide cuánto se puede
confiar en la etiqueta asignada. Si γ < 0,5, la serie se marca para revisión humana.

```
γ  =  0,30 · V(n)  +  0,45 · W(CV)  +  0,25 · R(y)
```

| Símbolo | Qué es | Unidad |
|---|---|---|
| `V(n)` | Cuánta historia tiene la serie, saturando en la ventana completa | 0 a 1 |
| `W(CV)` | Cuán estable es la serie; cae a medida que sube el coeficiente de variación | 0 a 1 |
| `R(y)` | Qué tan cercanos están los últimos 3 meses al nivel histórico | 0 a 1 |
| `γ` | Confianza en la etiqueta del patrón | 0 a 1 |

**Fuente:** Política declarada del proyecto, no estimada estadísticamente.

**Por qué se usa:** Las tres señales capturan las tres razones por las que un
pronóstico falla: poca historia, alta volatilidad y cambio de régimen reciente.
La volatilidad pesa más (0,45) porque es la que más degrada la precisión. Los pesos
son una declaración de criterio, no un ajuste de datos.

---

### 9.4 Etapa 3 · Proyección de demanda e inventario mínimo

#### 9.4.1 Croston y la aproximación de Syntetos-Boylan

**Qué hace:** Proyecta las series intermitentes separando la serie en dos —cuánto
se pide cuando se pide, y cada cuántos meses ocurre— y suavizando cada una por
separado.

```
z_t  =  α·y_t  +  (1 − α)·z_(t−1)          tamaño suavizado del evento
p_t  =  α·q_t  +  (1 − α)·p_(t−1)          intervalo suavizado entre eventos

D₅₀  =  c · z_t / p_t

c = 1            Croston original, patrón Intermitente
c = 1 − α/2      aproximación SBA, patrón Irregular      (= 0,925 con α = 0,15)
```

| Símbolo | Qué es | Unidad |
|---|---|---|
| `y_t` | Tamaño del evento de demanda observado en el mes t | unidades |
| `q_t` | Meses transcurridos desde el evento anterior | meses |
| `z_t` | Estimador suavizado de cuánto se lleva cuando se lleva algo | unidades |
| `p_t` | Estimador suavizado de cuántos meses pasan entre eventos | meses |
| `α` | Constante de suavizado, la misma para ambos componentes | 0,15 adimensional |
| `c` | Corrección de sesgo del cociente | adimensional |
| `D₅₀` | Consumo esperado por mes | unidades/mes |

**Fuente:** Croston, J.D. (1972). Forecasting and stock control for intermittent
demands. *Operational Research Quarterly*, 23(3), 289-303. Corrección: Syntetos,
A.A. & Boylan, J.E. (2005). The accuracy of intermittent demand estimates.
*International Journal of Forecasting*, 21(2), 303-314.

**Por qué se usa:** Ambas series se actualizan **solo en los meses en que algo se
mueve**, y ahí está el método entero. Suavizar la serie cruda converge a cero,
porque la mayoría de los meses son cero. Antes de incorporarlo, el 86 % de las
series de este catálogo proyectaba demanda nula y el optimizador no compraba
nada: la mediana móvil de una serie con 87 % de ceros es cero, y afirmar que una
pieza que se consume dos veces al año tiene demanda cero no es un pronóstico.

La corrección `1 − α/2` existe porque el cociente de dos estimadores suavizados
está sesgado al alza. Se aplica al patrón irregular porque es donde ese sesgo
inflaría el stock de las piezas menos predecibles.

**Cuándo falla:** Con un solo evento en toda la historia no hay intervalo que
suavizar y el estimador cae al nivel medio de la serie. Y α es una constante
única para todo el catálogo: ajustarla por serie es una mejora identificada y no
implementada — está declarada como supuesto abierto.

**El intervalo de la proyección** sale de la dispersión de los **tamaños
observados**, no de la serie completa: sobre una serie de ceros la desviación mide
el patrón de huecos, que ya lo mide `p_t`, y no la incertidumbre del tamaño.

---

#### 9.4.2 Los cuatro estimadores para series que se mueven todos los meses

**Qué hace:** Selecciona el método de proyección para las series que el
cuadrante SBC ya descartó del régimen intermitente.

```
D₅₀  =  ⎧ (1/6) · Σₜ yₜ          si Estable
         ⎪ P₅₀(ventana)           si Volátil
         ⎪ a·n + b                 si Tendencia
         ⎩ ℓₙ + sₙ₋₁₁             si Estacional
```

| Símbolo | Qué es | Unidad |
|---|---|---|
| `yₜ` | Consumo observado en el mes t | unidades/mes |
| `P₅₀` | Mediana de los últimos seis meses | unidades/mes |
| `a, b` | Pendiente e intercepto de la recta por mínimos cuadrados | unidades/mes² y unidades |
| `ℓₙ` | Nivel Holt-Winters en el último mes | unidades/mes |
| `sₙ₋₁₁` | Índice estacional del mismo mes calendario del año anterior | unidades/mes |
| `D₅₀` | Pronóstico central del mes siguiente | unidades/mes |

**Fuentes:**
- Media móvil: estadística descriptiva clásica.
- Percentiles empíricos: estadística no paramétrica.
- OLS: Gauss (1809) / Legendre (1805).
- Holt-Winters: Holt, C.C. (1957); Winters, P.R. (1960). *Management Science*, 6(3).

**Por qué se usa:** El método lo decide el patrón, no se ajusta por serie. Eso
hace el pronóstico reproducible: el motivo de cada cifra es la etiqueta, que la
etapa anterior ya publicó.

**El orden importa, y es la lección de la migración.** Los cuatro colapsan a cero
sobre una serie que es casi toda ceros —la mediana primero y la media detrás—, así
que ninguno se evalúa antes de que el cuadrante SBC haya descartado el régimen
intermitente. En el catálogo actual ese corte se lleva las 1.283 series, y estos
cuatro quedan para las referencias que de verdad se mueven todos los meses. En un
catálogo mixto, que es lo que habría en la cervecera real, ambos regímenes
convivirían y por eso los cuatro siguen implementados.

**Por qué no Prophet:** Con esta cantidad de ciclos Prophet está sobredimensionado
y sobreajusta. Además exige compilar Stan, que en Windows complica la demo.
Holt-Winters viene en statsmodels y es igualmente explicable.

---

#### 9.4.3 Intervalo de incertidumbre del pronóstico

**Qué hace:** Construye el escenario bajo (D₂₅) y alto (D₇₅) alrededor del punto
central.

```
D₂₅ / D₇₅  =  max( 0 ,  D₅₀  ∓  0,674 · S )
```

| Símbolo | Qué es | Unidad |
|---|---|---|
| `S` | Dispersión de la serie usada como estimador del error | unidades/mes |
| `0,674` | Cuantil de la normal estándar que deja el 25 % en cada cola | adimensional |
| `D₂₅, D₇₅` | Escenario bajo y alto del mes siguiente | unidades/mes |

**Fuente:** Cuantil de la distribución normal estándar.

**Por qué se recorta en cero:** Una demanda negativa no tiene significado operativo.
La aproximación normal la produce cuando la media es pequeña frente a la dispersión,
que es frecuente en refacciones. No es cosmético.

---

#### 9.4.4 Error ponderado del método — validación con origen móvil

**Qué hace:** Mide el error del método como fracción del volumen total movido,
evitando la división por cero del MAPE clásico.

```
WMAPE  =  Σⱼ |eⱼ| / Σⱼ yⱼ
```

| Símbolo | Qué es | Unidad |
|---|---|---|
| `eⱼ` | Error del mes j: pronóstico menos observado | unidades |
| `yⱼ` | Consumo observado en el mes j | unidades |
| `WMAPE` | Error como fracción del volumen realmente movido | 0 a 1 |

**Fuente:** Tashman, L.J. (2000). Out-of-sample tests of forecasting accuracy.
*International Journal of Forecasting*, 16(4). Evaluación con origen móvil
(*rolling-origin evaluation*) reservando los últimos 6 meses.

**Por qué WMAPE y no MAPE:** El MAPE divide mes a mes entre el valor real y
explota cuando hay meses en cero. Descartar esos meses los eliminaría siendo los
más informativos. WMAPE pone el total en el denominador una sola vez. Ponderar por
volumen evita además que un método se clasifique por su comportamiento en los meses
de menor demanda — que son los menos importantes operativamente.

---

#### 9.4.5 Combinación de los dos pronósticos

**Qué hace:** Mezcla el pronóstico del modelo global de ML con el del método
estadístico del patrón, con peso igual para ambos.

```
D₅₀,final  =  0,5 · M  +  0,5 · D₅₀
```

| Símbolo | Qué es | Unidad |
|---|---|---|
| `M` | Pronóstico del modelo global entrenado | unidades/mes |
| `D₅₀` | Pronóstico del método estadístico del patrón | unidades/mes |
| `λ` | Peso dado al modelo (aquí λ = 0,5) | 0 a 1 |

**Fuente:** Bates, J.M. & Granger, C.W.J. (1969). The combination of forecasts.
*Operational Research Quarterly*, 20(4). Premio Nobel de Economía 2003 para
Granger por trabajos posteriores en series temporales.

**Por qué peso igual:** El peso óptimo teórico minimizaría el error combinado
teniendo en cuenta la correlación de los errores de ambos métodos. Se usa 0,5
porque la validación muestra errores similares y errores débilmente correlacionados
entre el modelo y el estadístico — que es exactamente el caso en que la
combinación aequiponderada aproxima bien el óptimo. El peso óptimo no se estima
para no sobreajustar la combinación a los datos de validación.

---

#### 9.4.6 Base diaria de la demanda

**Qué hace:** Convierte el pronóstico mensual en tasa y desviación diarias para
alimentar el cálculo del inventario mínimo.

```
d  =  D₅₀,final / 30 ,    σ_d  =  σ / √30
```

| Símbolo | Qué es | Unidad |
|---|---|---|
| `d` | Demanda media diaria | unidades/día |
| `σ_d` | Desviación estándar de la demanda diaria | unidades/día |
| `30` | Días de planificación por mes. Constante de política, no el calendario | días/mes |

**Fuente:** Varianza de una suma de variaciones diarias independientes.

**La sutileza estadística:** La media divide lineal por 30 y la desviación divide
por √30, porque la varianza de una suma de 30 variaciones diarias independientes es
30 veces la varianza diaria. Con autocorrelación positiva —que la demanda de
refacciones suele tener— el exponente real está entre 0,6 y 0,8, no en 0,5, así
que esta conversión subestima el colchón en las series más correlacionadas.

---

#### 9.4.7 Varianza de la demanda sobre un lead time aleatorio

**Qué hace:** Descompone el riesgo total del reorden en dos fuentes independientes:
la incertidumbre de la demanda y la incertidumbre del proveedor.

```
Var(D_L)  =  L · σ_d²  +  d² · σ_L²
```

| Símbolo | Qué es | Unidad |
|---|---|---|
| `L` | Lead time medio de planificación | días |
| `σ_L` | Desviación estándar del lead time | días |
| `d, σ_d` | Media y desviación de la demanda diaria | unidades/día |
| `Var(D_L)` | Varianza de la demanda acumulada mientras el pedido está en tránsito | unidades² |

**Fuente:** Ley de la varianza total (*law of total variance*). Hadley, G. &
Whitin, T.M. (1963). *Analysis of Inventory Systems*. Prentice-Hall. También en
Silver, E.A., Pyke, D.F. & Peterson, R. (1998). *Inventory Management and
Production Planning and Scheduling*. Wiley.

**El dato que lo hace importante:** Con σ_L/L ≈ 0,37 en estos proveedores —y hasta
0,35 en el proveedor OEM, cuyo plazo va de 34 a 118 días— los dos términos son del
mismo orden de magnitud: **una parte grande del riesgo de cada pieza no viene de la
demanda, viene del proveedor**. Un cálculo de inventario mínimo que ignore el
segundo término queda corto creyendo tener el nivel de servicio declarado.

---

#### 9.4.8 Punto de reorden — el inventario mínimo (fórmula central)

**Qué hace:** Calcula el nivel de existencias al que se debe lanzar la orden de
compra para que, con la probabilidad declarada por criticidad, el stock no se agote
antes de que llegue el pedido.

```
μ_LT  =  d · L                              consumo esperado mientras llega el pedido
Var_LT = L · σ_d²  +  d² · σ_L²             varianza compuesta (demanda Y proveedor)

p  =  μ_LT / Var_LT ,    r  =  μ_LT · p / (1 − p)

Imin  =  F⁻¹( α(k) ; r, p )                 cuantil de la binomial negativa
```

| Símbolo | Qué es | Unidad | Valor actual |
|---|---|---|---|
| `d` | Demanda media diaria proyectada | unidades/día | Por serie |
| `L` | Lead time medio ponderado | días | ≈ 30,0 |
| `σ_d` | Desviación de la demanda diaria | unidades/día | Por serie |
| `σ_L` | Desviación del lead time | días | ≈ 11,07 |
| `α(k)` | Nivel de servicio de ciclo por criticidad | fracción | A 0,95 · B 0,90 · C 0,80 |
| `r, p` | Parámetros de la binomial negativa ajustada a `μ_LT` y `Var_LT` | — | Por serie |
| `Imin` | Nivel al que se lanza la orden | unidades enteras | — |

**Fuente:** La media y la varianza son Hadley, G. & Whitin, T.M. (1963).
*Analysis of Inventory Systems*. Prentice-Hall — la formulación canónica de los
módulos MRP de SAP, Oracle y la mayoría de los ERP industriales. El cuantil
compuesto sigue a Eppen, G.D. & Martin, R.K. (1988). Determining safety stock in
the presence of stochastic lead time and demand. *Management Science*, 34(11).

**Por qué se usa esto y no solo `d · L`:** El primer término es el mínimo
absoluto: lo que se consume mientras llega el pedido, sin colchón ninguno. La
varianza compuesta suma las dos incertidumbres porque son independientes. Ignorar
el término `d² · σ_L²` equivale a asumir que todos los proveedores son
perfectamente puntuales — supuesto que el propio dataset refuta (σ_L/μ_L = 0,37).

**Por qué el cuantil y no `μ + z·σ` — y por qué el resultado sorprendió.** La
aproximación normal es válida cuando la media es grande frente a la desviación.
Aquí no lo es: con medias de dos o tres unidades y desviaciones mayores, una
normal centrada en `μ_LT` pone **una mediana del 39 % de su masa en demanda
negativa**, y más del 20 % en el 99 % de las series. Esa masa imposible se
compensa estirando la cola derecha, así que el cuantil sale inflado.

La hipótesis de partida de este proyecto era la contraria: que corregir la
distribución **subiría** el inventario mínimo, porque la literatura advierte que
la normal subestima el colchón. Medido sobre este catálogo, lo **baja** en dos de
cada tres series. El catálogo pasó de 16.241 unidades y 1,34 M USD a **7.789
unidades y 683 k USD**, un 49 % menos, al mismo nivel de servicio declarado. La
normal no era conservadora, era inválida a estas medias.

La binomial negativa se ajusta por momentos a la misma media y varianza y vive en
los enteros no negativos, que es donde vive la demanda de refacciones. Cuando la
varianza no supera a la media, el ajuste degenera y se usa Poisson.

**Trampa operativa a recordar:** dos etapas distintas llaman a esta función —la
construcción del inventario actual y la proyección—. Si se cambia la definición
de mínimo hay que **re-correr el dataset entero**, no solo la proyección, o las
dos etapas dejan de compartir la definición. Existe un test que lo detecta:
`test_inventory_minimum_has_no_systematic_bias_against_reorder_point`.

---

### 9.5 Etapa 4 · Optimización de abastecimiento

#### 9.5.1 Cantidad económica de pedido (EOQ / Wilson)

**Qué hace:** Calcula la cantidad de compra que minimiza la suma anual del costo de
pedir (flete por pedido) más el costo de mantener (capital inmovilizado + seguros +
obsolescencia).

```
Q*  =  √( 2 · K · D / h ) ,    con  h = i · c ,    D = 12 · D₅₀
```

| Símbolo | Qué es | Unidad |
|---|---|---|
| `K` | Costo fijo de traer un pedido: el flete a esa planta | USD/pedido |
| `D` | Demanda anual proyectada para la pieza | unidades/año |
| `c` | Valor unitario de la pieza en el maestro | USD/unidad |
| `h` | Costo de mantener una unidad ociosa un año: capital + almacenamiento + seguros + riesgo de obsolescencia | USD/unidad/año |
| `i` | Tasa anual de posesión aplicada al valor de la pieza | fracción (0,25 = 25 %) |
| `Q*` | Cantidad que minimiza la suma anual de costo de ordenar + mantener | unidades |

**Fuente:** Harris, F.W. (1913). How many parts to make at once. *Factory, The
Magazine of Management*, 10(2). Wilson, R.H. (1934). A scientific routine for
stock control. *Harvard Business Review*, 13. Enlace con la política order-up-to:
Hadley & Whitin (1963).

**Por qué reemplaza la cobertura en meses fija:** Una cobertura de 1,5 meses fija
no se entera de que el flete de esta pieza es 5 veces el de aquella, ni de que el
valor de esta otra justifica un lote menor para no inmovilizar capital. El EOQ
equilibra esos dos costos explícitamente. El resultado: lotes más grandes en piezas
baratas con flete alto, lotes más pequeños en piezas caras con bajo flete.

**La propiedad del costo plano:** La curva de costo total alrededor del óptimo es
cuadrática aplastada, no en V. Estar el doble del Q* óptimo sube el costo total
anual solo un 25 %. Esto hace que una aproximación a K con el flete promedio de las
ofertas sea razonable: el efecto de la raíz cuadrada amortigua el error.

---

#### 9.5.2 Nivel order-up-to y tope de cobertura

**Qué hace:** Calcula el nivel hasta el que se repone (S), aplica el tope de
cobertura para no acumular más de 6 meses, y define el máximo de inventario.

```
Q    =  min( ceil(Q*) ,  floor(D₅₀ × 6) )
S    =  Imin + Q
Imax =  S
```

| Símbolo | Qué es | Unidad |
|---|---|---|
| `s` | Punto de reorden, que es Imin de la etapa anterior | unidades |
| `S` | Nivel al que se repone cuando se lanza la orden | unidades |
| `Q` | Lote económico después del tope de cobertura | unidades |
| `6` | Meses de cobertura por encima de los cuales la obsolescencia supera el ahorro en flete | meses |

**Fuente:** Política (s, S). Propiedad del costo plano: Silver, Pyke & Peterson
(1998). *Inventory Management and Production Planning and Scheduling*. Wiley.

**La implicación de política:** En una política (s, S), el nivel de reposición y
el techo de inventario son el mismo número. Nunca se compra por encima de S, así
que ese nivel es a la vez el objetivo y el máximo. Esto reemplaza los 3 meses
fijados a dedo que usaba el sistema anterior.

**Por qué el tope de 6 meses:** Por encima de 6 meses de cobertura, la ganancia de
ordenar menos veces al año es menor que el costo de inmovilizar esas unidades
adicionales. También limita el riesgo de obsolescencia: el EOQ de Wilson no sabe
que las piezas vencen; este tope se lo dice.

---

#### 9.5.3 Techo por vida útil (anti-obsolescencia)

**Qué hace:** Limita la compra a lo que la demanda proyectada puede consumir antes
de que la pieza venza, con un margen de seguridad del 20 %.

```
Ivida  =  max( 0 ,  floor( d × 0,80 × V )  −  q )
```

| Símbolo | Qué es | Unidad |
|---|---|---|
| `V` | Vida útil de la pieza | días |
| `0,80` | Margen de seguridad: solo se planifica contra el 80 % de la vida útil | adimensional |
| `q` | Unidades ya en bodega, que se consumen primero | unidades |
| `Ivida` | Unidades que todavía se pueden consumir antes del vencimiento | unidades |

**Fuente:** Regla anti-obsolescencia declarada para este dataset.

**Por qué el 80 %:** Una parte de la vida útil se pierde en almacenamiento,
manipulación y variabilidad de la tasa de consumo. El 20 % de margen absorbe ese
riesgo sin agotar el presupuesto en unidades que probablemente se consuman a tiempo.

---

#### 9.5.4 Selección de proveedor — MILP de costo fijo

**Qué hace:** Elige a qué proveedor comprarle y cuántas unidades, minimizando el
costo total (precio × cantidad + flete), respetando el lote mínimo, la capacidad
y un solo proveedor por orden.

```
minimizar   Σₒ ( pₒ · xₒ  +  fₒ · uₒ )

sujeto a    Σₒ xₒ  ≥  Rinf           cubrir el faltante
            Σₒ uₒ  ≤  1              un solo proveedor por orden
            xₒ ≥ mₒ · uₒ            el MOQ solo aplica si se activa el proveedor
            xₒ ≤ Uₒ · uₒ            y la capacidad lo acota
```

| Símbolo | Qué es | Unidad |
|---|---|---|
| `xₒ` | Unidades compradas de la oferta o | unidades enteras |
| `uₒ` | Si la oferta o se activa o no | 0 ó 1 |
| `pₒ, fₒ, mₒ` | Precio unitario, flete fijo y MOQ de la oferta | USD/unidad, USD, unidades |
| `Uₒ` | Cota superior efectiva: el menor entre el techo de inventario y la capacidad del proveedor | unidades |
| `Rinf` | Cantidad que hay que cubrir (diferencia entre mínimo e inventario actual) | unidades |

**Fuente:** Problema de costo fijo (*fixed-charge problem*). Balinski, M.L. (1961).
Fixed-cost transportation problems. *Naval Research Logistics Quarterly*, 8(1).
Resuelto exactamente con el solver CBC (COIN-BC), que es gratuito y corre en
milisegundos para modelos de 2–3 ofertas.

**Las dos restricciones de enlace son el mecanismo clave:**
- Con `uₒ = 0`: `xₒ ≥ 0 · 0 = 0` y `xₒ ≤ Uₒ · 0 = 0`, por lo que `xₒ = 0`. No
  se compra nada y no se paga flete.
- Con `uₒ = 1`: `xₒ ≥ mₒ`, por lo que el lote mínimo se respeta. Y `xₒ ≤ Uₒ`,
  por lo que la capacidad acota.

Esto es lo que convierte «el flete se paga solo si se usa al proveedor» y «el MOQ
solo aplica si se le compra» en restricciones lineales que un solver exacto puede
tratar.

**Por qué un solo proveedor:** No es una restricción matemática — split entre dos
proveedores sería igual o mejor en costo. Es una regla operativa: una orden tiene
que ser ejecutable por una persona sin coordinar dos suministros simultáneos.

---

#### 9.5.5 Valoración del quiebre que la reposición evita

**Qué hace:** Traduce el riesgo de quiebre a dólares para que el reparto de
presupuesto pueda comparar piezas en la misma moneda.

```
días_expuestos  =  max(0, P + L − cobertura)  −  max(0, L − cobertura)

Cq  =  ( 1 − exp( −d · días_expuestos ) )  ×  c_evento(k)
       └──────────────┬──────────────────┘
       P(al menos un pedido durante la exposición), Poisson
```

| Símbolo | Qué es | Unidad | Valor actual |
|---|---|---|---|
| `cobertura` | Días que aguanta el stock actual a la tasa de pronóstico | días | Por serie |
| `P` | Período de planificación hasta la siguiente corrida | días | 30 |
| `L` | Lead time de reposición | días | ≈ 30,0 |
| `d` | Demanda media diaria proyectada | unidades/día | Por serie |
| `c_evento(k)` | Costo de **un** evento de quiebre, por criticidad | USD/evento | A 45.000 · B 4.000 · C 250 |
| `Cq` | Valor del quiebre que evita reponer ahora en vez de esperar | USD | — |

**Fuente:** Proceso de Poisson para las llegadas de demanda, que es el modelo
estándar de la teoría de inventarios de repuestos. Los `c_evento(k)` son
parámetros de negocio declarados, no estimados.

**El fallo que el dato intermitente destapó, y que hay que saber contar.** La
versión anterior era `días_expuestos × tasa_de_salida × costo_por_día(k)`, con el
argumento de que un día sin existencias solo cuesta si ese día alguien pide la
pieza. El argumento es correcto, pero **la rareza ya estaba contada una vez**:
los días expuestos se derivan de la cobertura, y la cobertura se deriva de la
demanda proyectada, de modo que una pieza rara ya aparecía con más cobertura y
menos exposición. Multiplicar otra vez por la tasa de salida la descontaba dos
veces.

Con el catálogo anterior el efecto pasaba desapercibido porque la tasa de salida
rondaba la unidad. Con este, se derrumbó a 0,005 y el quiebre mediano quedó
valorado en **0,00 USD**: el optimizador no compraba nada, y no porque no hiciera
falta.

La corrección tiene dos partes. La probabilidad de que ocurra al menos un pedido
durante la ventana de exposición se calcula con Poisson, que es donde esa
probabilidad corresponde. Y la constante pasó de costo **por día** a costo **por
evento**, con una recalibración de dos órdenes de magnitud: parar una línea de
embotellado no cuesta 400 USD, cuesta el turno.

**Limitaciones conocidas:**
1. Poisson asume llegadas independientes a tasa constante. En una pieza cuya
   falla dispara varias solicitudes seguidas, subestima el riesgo.
2. `c_evento(k)` es un parámetro fijo, no una estimación. Su magnitud decide
   cuánto pesa la criticidad frente al precio, y **es el número que hay que
   validar con mantenimiento antes de operar el sistema**.

---

#### 9.5.6 Reparto del presupuesto con continuidad de producción como restricción dura

**Qué hace:** Distribuye el presupuesto de la corrida entre todas las piezas a la
vez, garantizando primero que ninguna pieza de criticidad A quede sin financiar, y
luego maximizando el beneficio neto de las discrecionales.

```
maximizar   Σ_{s ∈ Cand_flex}  bₛ · vₛ

sujeto a    vₛ = 1    ∀ s ∈ Cand_crit         criticidad A siempre financiada
            Σₛ Cₛ · vₛ  ≤  B + E              presupuesto elástico
            E  ≤  Emax                         excedente acotado y publicado
```

| Símbolo | Qué es | Unidad | Valor actual |
|---|---|---|---|
| `Cand_crit` | Reposiciones cuyo quiebre para una línea: criticidad A | conjunto | — |
| `Cand_flex` | El resto, que compite por lo que sobra | conjunto | — |
| `bₛ` | Beneficio neto: quiebre evitado menos costo de evitarlo | USD | Por serie |
| `Cₛ` | Costo total de la reposición ya resulto por el modelo anterior | USD | Por serie |
| `vₛ` | Si la compra se financia en esta corrida | 0 ó 1 | — |
| `B` | Presupuesto nominal de la corrida | USD | 250.000 |
| `E` | Excedente realmente consumido para cubrir las críticas | USD | — |
| `Emax` | Techo autorizado sobre ese excedente | USD | 1.500 |

**Fuente:** Mochila 0/1 (*0/1 knapsack problem*). Lorie, J.H. & Savage, L.J.
(1955). Three problems in capital rationing. *Journal of Business*, 28(4).
Weingartner, H.M. (1963). *Mathematical Programming and the Analysis of Capital
Budgeting Problems*. Prentice-Hall.

**Por qué se resuelve exacto y no con el algoritmo voraz:** El algoritmo voraz
—ordenar por rentabilidad por dólar y llenar hasta agotar el presupuesto— es
óptimo solo cuando las compras son divisibles. Cuando son indivisibles (0 ó 1),
una compra muy rentable y cara puede desplazar a varias baratas que juntas rinden
más. El solver CBC lo resuelve exactamente en milisegundos para este tamaño.

**La inversión de mando que importa explicar:** Antes, el presupuesto mandaba sobre
todo y una pieza de criticidad A podía aplazarse si otras rentaban más por dólar —
un intercambio que el negocio no aprobaría si lo viera. Ahora la continuidad de
producción no compite: las críticas se financian primero, el presupuesto se vuelve
elástico hasta `Emax` para lograrlo, y lo que no cabe ni así sale como `ESCALAR`
en vez de aplazarse en silencio. El excedente se publica, no se oculta.

---

#### 9.5.7 Piso de nivel de servicio por clase de criticidad

**Qué hace:** Añade una restricción al knapsack para que el número de reposiciones
financiadas por clase sea coherente con el nivel de servicio declarado en el punto
de reorden.

```
Σ_{s ∈ Class_k}  vₛ  ≥  ceil( θₖ × |Class_k| )
```

| Símbolo | Qué es | Unidad | Valor actual |
|---|---|---|---|
| `Class_k` | Reposiciones de criticidad k que estaban pendientes | conjunto | — |
| `θₖ` | Fracción de la clase que debe financiarse | 0 a 1 | A 1,00 · B 0,80 · C 0,50 |
| `vₛ` | Si la compra se financia | 0 ó 1 | — |

**Fuente:** Consistencia con los valores `z` declarados en el punto de reorden.

**Por qué existe:** Si en la etapa del inventario mínimo se declaró que las piezas
B operan al 90 % de nivel de servicio, el presupuesto no puede contradecirlo
aplazando la mayoría de ellas. Esta restricción impone coherencia entre ambas
etapas. Cuando el dinero no alcanza ni para los pisos, se sueltan de la clase
menos exigente hacia arriba en vez de declarar el modelo infactible, y el nivel
realmente alcanzado se publica junto al declarado.

---

### 9.6 Cuadro resumen: de dónde viene cada número

| Número en pantalla | Fórmula que lo produce | Sección |
|---|---|---|
| Régimen intermitente o irregular | Cuadrante SBC: ADI y CV² del evento | §9.3.1 |
| Patrón de la serie | CV, Fₛ, Kruskal-Wallis, Mann-Kendall | §9.3 |
| Confianza en el patrón (γ) | Score compuesto ponderado | §9.3.5 |
| Pronóstico de series intermitentes | Croston · Croston-SBA | §9.4.1 |
| Pronóstico del resto (D₅₀) | Media / percentil / OLS / Holt-Winters + combinación ML | §9.4.2–5 |
| Intervalo D₂₅–D₇₅ | Cuantil normal ±0,674·S | §9.4.3 |
| Error WMAPE, MASE y sesgo acumulado | Validación con origen móvil | §9.4.4 |
| Inventario mínimo (Imin) | Cuantil de la binomial negativa compuesta | §9.4.8 |
| Lote económico (Q*) | EOQ de Wilson: √(2·K·D/h) | §9.5.1 |
| Inventario máximo (Imax) | Nivel order-up-to: Imin + Q | §9.5.2 |
| Techo por vida útil | Anti-obsolescencia: d·0,8·V − q | §9.5.3 |
| Proveedor y cantidad | MILP de costo fijo, solver CBC | §9.5.4 |
| Costo del quiebre (Cq) | P(Poisson de quiebre) × costo del evento c(k) | §9.5.5 |
| COMPRAR / APLAZADO / ESCALAR | Mochila 0/1 con restricción de continuidad | §9.5.6 |
| Nivel de servicio alcanzado vs. declarado | Piso por clase θₖ | §9.5.7 |

---

### 9.7 Los supuestos que hay que poder defender

Estos son los supuestos implícitos más cuestionables. Si alguien los señala, hay
que tenerlos reconocidos. Los tres primeros son los abiertos; el cuarto se
cerró con la migración y se deja documentado porque la corrección es en sí misma
un argumento.

| Supuesto | Dónde aplica | Consecuencia si falla |
|---|---|---|
| **La demanda diaria es independiente entre días** | Conversión mensual → diaria (§9.4.7) | El colchón se subestima en series con días de alta correlación. El exponente real está entre 0,6 y 0,8, no 0,5 |
| **α = 0,15 vale para todo el catálogo** | Croston y SBA (§9.4.1) | Una constante única suaviza igual una pieza de reposición periódica y una de falla esporádica. Ajustarla por serie es la mejora identificada de mayor retorno en el pronóstico |
| **El lote de compra observado es la demanda** | Historia de consumo (§4.2) | El libro de órdenes registra lo que se pidió, no lo que se consumió. Si el cliente pide de a lotes, el tamaño del evento está inflado y el intervalo estirado. Deconvolucionarlo está identificado y no implementado |
| **Los parámetros c(k) del costo de quiebre son correctos** | Valoración del quiebre (§9.5.5) y mochila (§9.5.6) | Si el paro de línea no cuesta 45.000 USD por evento, las prioridades del sistema entero cambian. Es el número que hay que validar con negocio antes de operar |
| ~~La distribución de demanda sobre el lead time es normal~~ | ~~Inventario mínimo~~ | **Cerrado.** Se midió que la normal ponía una mediana del 39 % de su masa en demanda negativa e inflaba el catálogo un 49 %. Sustituida por el cuantil de una binomial negativa ajustada a la media y varianza compuestas (§9.4.8) |

---

## 10. La pantalla: cómo se defiende el diseño

Esta sección es para cuando alguien pregunte por qué la interfaz se ve así. No es
decoración: cada decisión responde a un problema medido sobre la versión
anterior, y contarlo convierte una demo en una defensa.

### 10.1 El problema que resolvió el rediseño

> «La pantalla decía **"Production is covered"** y justo debajo tenía setenta y
> ocho casos en rojo. Las dos cosas eran verdad —las piezas críticas estaban
> financiadas *y* había trabajo pendiente— pero el titular respondía una pregunta
> y las alertas otra. Una pantalla que parece contradecirse deja de usarse para
> decidir, y entonces da igual lo bueno que sea el optimizador de detrás.»

### 10.2 Tres semáforos, y el titular es el peor

| Luz | Pregunta que responde | Cuándo se pone en rojo |
|---|---|---|
| **Production continuity** | ¿Puede pararse una línea? | Alguna criticidad A sin financiar |
| **Run budget** | ¿El dinero dio, y a costa de qué? | Se consumió excedente autorizado |
| **Waiting for you** | ¿Cuánto espera a una persona? | Entre lo pendiente hay criticidad A |

**Frase para la sala:** «El titular es la peor de las tres, nunca un promedio.
Promediar un rojo con dos verdes da ámbar, y un ámbar no mueve a nadie. El riesgo
no se compensa: que el presupuesto esté sano no baja la probabilidad de que se
pare una línea.»

**El detalle que demuestra criterio:** cada luz lleva su palabra —`Clear`,
`Watch`, `Act now`— además del color. Uno de cada doce hombres no distingue rojo
de verde, y una captura en blanco y negro tiene que seguir diciendo lo mismo.

### 10.3 Lo que se quitó de la lista, y por qué

La fatiga de alertas es un problema **de diseño**, no de disciplina: una alerta
que no exige acción entrena a ignorar las que sí.

| Antes | Ahora |
|---|---|
| Banda con **1.117** piezas en «No action» | Una línea con enlace al catálogo completo |
| **73** compras automáticas pidiendo Aprobar/Rechazar | Plegadas, sin botones, «comprometidas por el sistema» |
| **78** casos planos con idéntica causa | Agrupados por criticidad, solo el grupo A abierto |

**Frase para la sala:** «Pedirle a un comprador setenta y tres firmas sobre
compras que el optimizador resolvió sin ambigüedad no es control, es el ruido que
hace que se firme sin mirar. Nacen comprometidas y la traza queda: aprobadas por
el sistema, bajo una regla que se puede leer. Lo que sí pide firma es lo que
exige criterio.»

### 10.4 La tarjeta: riesgo, plan, decisión

El orden no es estético, es el orden en que se decide:

1. **Riesgo** — qué pasa si falta y cuánto queda al ritmo actual. Sin cifras en
   dólares: la urgencia la marca el tiempo, no el importe.
2. **Medidor** — una escala con el stock, el punto de reorden y el nivel de
   reposición *en su posición*, no una barra con los números en una frase aparte.
3. **Plan** — cantidad, proveedor, importe y plazo en una línea, con el proveedor
   marcado como el mejor de las ofertas comparadas.
4. **Decisión** — el titular (`I would buy`) y los botones. El razonamiento vive
   en el detalle.

**Frase para la sala:** «Ninguna cifra aparece dos veces. El beneficio neto se
dice como múltiplo —*83 veces lo que cuesta el lote*— y no como un tercer importe,
porque con el costo y el riesgo ya en pantalla una tercera cantidad obliga a
restar mentalmente, que es justo la cuenta que la tarjeta debería ahorrar.»

### 10.5 El mapa: previsualizar y fijar

Pasar el ratón previsualiza la planta; hacer clic la fija y filtra los casos; el
foco de teclado hace lo mismo que el ratón.

**Frase para la sala, si preguntan por accesibilidad:** «Hover-solo habría sido
una violación de WCAG 2.1. Una previsualización que solo existe bajo el cursor no
existe en un móvil ni para quien navega con tabulador. Las tres vías hacen lo
mismo a propósito, y el clic sigue siendo el que tiene consecuencia.»

### 10.6 Las tres limitaciones de la pantalla

Reconocerlas antes de que las señalen:

1. **El rojo de continuidad es binario por criticidad, no por tiempo.** Una pieza
   A con dos semanas de cobertura pinta igual que una con dos días. Lo correcto
   sería comparar la cobertura contra el plazo de entrega de esa serie.
2. **No hay acción en lote.** Aprobar setenta y ocho revisiones siguen siendo
   setenta y ocho clics. La agrupación por criticidad prepara el terreno, pero el
   botón de grupo no existe.
3. **El reparto por planta es descriptivo.** Dice a dónde fue el dinero, no si
   ese reparto fue el correcto: la mochila tiene un presupuesto único y global,
   sin restricciones por planta.
