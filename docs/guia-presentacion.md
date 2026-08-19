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

- La demanda de refacciones es **intermitente** y de patrón heterogéneo — una
  misma pieza es estable en una planta y estacional en la otra (**8 de 20 piezas**
  cambian de patrón según la ciudad).
- El lead time de los proveedores varía con **σ/μ ≈ 0,53** y su peor caso (20
  días) casi duplica al promedio (10,6 días).
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
| **Lead time** | Plazo desde que se pide hasta que llega | «Lead time medio 10,6 días con sigma 5,45» |
| **MOQ** | Cantidad mínima de orden del proveedor | «El MOQ de 100 supera el máximo de bodega» |
| **Nivel de servicio de ciclo (α)** | Probabilidad de no quebrar en un ciclo | «Criticidad A opera a 95 % de servicio» |
| **Fill rate (β)** | Fracción de demanda servida del stock | «Ojo: α y β no son lo mismo» |
| **Stockout** | Quiebre de inventario | «El costo de stockout entra en la función objetivo» |
| **Cobertura** | Meses o días que aguanta el stock actual | «Quedan 8 días de cobertura contra 10,6 de lead time» |
| **Rotación / turnover** | Vueltas de inventario al año | «Rotación mínima del catálogo: 9,8 vueltas/año» |
| **ABC (Pareto)** | Segmentación por valor | «El 40 % de las referencias es el 78 % del valor» |
| **VED / criticidad** | Segmentación por impacto de la falla | «Criticidad A para en línea de producción» |
| **FSN** | Segmentación por rotación | «Los ítems N son candidatos a auditoría de existencia» |
| **Intermitencia / ADI** | Cada cuánto hay consumo | «ADI mediano 1,00: sin espaciamiento» |
| **MILP** | Programación lineal entera mixta | «La selección de proveedor es un MILP de costo fijo» |
| **Mochila / knapsack** | Asignar recurso escaso entre proyectos indivisibles | «El presupuesto se reparte como mochila 0/1» |
| **WMAPE** | Error ponderado sobre el total | «WMAPE y no MAPE, porque hay meses en cero» |
| **Order-up-to** | Reponer hasta un nivel objetivo | «No reponemos al mínimo, sino al nivel objetivo» |

---

## 3. Cómo funciona: el pipeline en cinco fórmulas

Estas son las únicas cinco que hay que poder escribir en un pizarrón.

### 3.1 Clasificación de patrón

```
Estacional   si  F_s >= 0,45  y  p_Kruskal-Wallis < 0,05
Tendencia    si  p_Mann-Kendall < 0,05
Volátil      si  CV = sigma/mu > 0,50
Estable      en otro caso
```

**Cómo se cuenta:** «Antes de proyectar, cada serie pieza-ciudad se clasifica.
La estacionalidad exige **dos** condiciones a la vez, no una: con solo tres ciclos
de historia, la descomposición clásica encuentra estacionalidad aparente incluso
en ruido puro —fuerza media 0,32—, así que exigimos además significancia
estadística del efecto de mes. Eso baja el falso positivo del 26 % al 2 %.»

### 3.2 Proyección según el patrón

| Patrón | Método | Por qué ese |
|---|---|---|
| Estable | Media móvil 6 meses | No hay estructura que aprender |
| Volátil | Percentiles empíricos | La mediana no la arrastra un mes extremo |
| Tendencia | Regresión lineal | Captura la deriva sostenida |
| Estacional | Holt-Winters aditivo | Prophet sobreajusta con 3 ciclos |

**Cómo se cuenta:** «No aplicamos un solo modelo a todo. Es un modelo por
regímenes: cada serie va al estimador que su patrón justifica. Solo 6 de 40
series necesitan Holt-Winters; el 85 % se resuelve con métodos estadísticos
simples, que es lo correcto para este volumen de datos.»

### 3.3 Inventario mínimo — **la fórmula central**

```
Imin  =  d · L   +   z(k) · sqrt( L · sigma_d²  +  d² · sigma_L² )
         └──┬─┘       └────────────────┬──────────────────────────┘
       demanda durante        colchón que absorbe DOS incertidumbres:
       el lead time           la de la demanda Y la del proveedor
```

| Símbolo | Qué es | Unidad | Valor actual |
|---|---|---|---|
| `d` | Demanda media diaria proyectada | unidades/día | Por serie |
| `L` | Lead time medio | días | 10,6 |
| `sigma_d` | Desviación de la demanda diaria | unidades/día | Por serie |
| `sigma_L` | Desviación del lead time | días | 5,45 |
| `z(k)` | Factor de servicio por criticidad | adimensional | A=1,65 · B=1,28 · C=0,84 |

**Cómo se cuenta:** «Esta es la formulación canónica de Hadley & Whitin, 1963 —
la misma que llevan los módulos MRP de SAP y Oracle. Lo importante es el segundo
término bajo la raíz: está multiplicado por la **demanda al cuadrado**. Con
σ/μ ≈ 0,53 en estos proveedores, **la mitad del riesgo de cada pieza no viene de
la demanda, viene del proveedor**. Ignorar ese término dejaría el colchón un 30 a
40 % corto creyendo tener 95 % de servicio.»

**El puente a negocio:** «Y ese `z` es una decisión de negocio, no técnica. 1,65
significa 95 % de nivel de servicio. Es la única declaración de política de
servicio que hace el sistema, y hoy está fijada por constante.»

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

### 4.1 Lo que sí es real

| Dato | Origen | Calidad |
|---|---|---|
| Lead times (10,6 d, σ 5,45) | 777 órdenes reales con fecha de pedido y entrega | Real, calculado |
| Proveedores y precios | Dataset de compras | Real |
| Patrón de demanda | Derivado del histórico | Calculado |
| Defectuosos, cumplimiento | Dataset de compras | Real |

### 4.2 Lo que es sintético — decirlo antes de que pregunten

Vida útil, stock actual, MOQ, capacidad y flete **los generó el build con semilla
fija**. La interfaz los marca con un distintivo y los meses de histórico simulado
se dibujan en trazo discontinuo.

> **Frase para la presentación:** «Las decisiones del optimizador son correctas
> *dado ese dato*, pero no son decisiones de compra reales. Lo digo explícitamente
> para que nadie confunda el ejercicio con una recomendación operativa.»

### 4.3 Los hallazgos de la limpieza — presentarlos como fortaleza

La Etapa 0 encontró problemas reales que cualquier proyecto habría pasado por
alto:

| Problema | Magnitud | Tratamiento | Impacto |
|---|---|---|---|
| **Órdenes canceladas contadas como entregas** | 130 de 689 | Filtradas por estado | Sesgaban el lead time ~0,2 días a la baja |
| Órdenes sin fecha de pedido o entrega | 87 | Descartadas | Sin fechas no hay plazo medible |
| `Defective_Units` nulo | 136 | Imputado cero | La ausencia significa que no se reportaron |
| Mes con un solo día registrado | 200 filas | Descartado | Se leería como caída de demanda |

**Dos decisiones que demuestran criterio:**

1. **Los atípicos de sensor se marcan, no se eliminan** (44.860 lecturas). Una
   vibración o temperatura extrema suele ser justamente la señal de que la máquina
   va a fallar — el evento que anticipa el consumo. Borrarlas eliminaría la
   información más valiosa del conjunto.

2. **Los meses de consumo atípico se reportan, no se corrigen** (9 casos),
   evaluados contra la propia serie y no contra el conjunto, porque una pieza de
   100 unidades al mes y otra de 2 tienen escalas incomparables. Requieren
   confirmación de mantenimiento: puede haber sido una parada mayor real.

### 4.4 La limitación honesta: el histórico no es intermitente

**Esta es la crítica que un experto hará. Adelantarse.**

| Métrica | Medido | Esperado en MRO real | Lectura |
|---|---|---|---|
| Meses con demanda cero | **3,3 %** | 40–70 % | El histórico no es intermitente |
| ADI mediano | **1,00** | > 1,32 | Consumo todos los meses |
| CV² mediano | **0,11** | > 1,0 | Tamaños de evento muy estables |
| Demanda media | **18,3 u/mes** | 0,1–3 u/mes | Perfil de insumo, no de refacción |
| Rotación mínima | **9,8 vueltas/año** | ítems N rotan < 1 | Ningún ítem inmóvil |

Clasificación ADI/CV² (Syntetos, Boylan & Croston, 2005): **38 de 40 series caen
en «Suave»** y **cero en «Lumpy»**, que es el cuadrante donde vive la mayoría del
MRO real.

> **Frase para la presentación:** «El dato crudo diario sí tenía la intermitencia
> esperada —90 % de días en cero, 86 % de eventos de una unidad— y nuestro
> perfilado lo midió. Esa intermitencia se perdió al agregar a mes. Lo que esto
> acota es qué demuestra el MVP: **valida la arquitectura de decisión, no la
> capacidad de pronosticar demanda intermitente**. Con dato real habría que
> incorporar Croston o SBA, que están fuera del alcance actual pero identificados.»

### 4.5 El hallazgo del modelo — no taparlo

> «El modelo de gradient boosting mejora **28,2 %** sobre repetir el último mes,
> pero solo **3,2 %** sobre el promedio móvil. Con 36 meses y series mayormente
> planas, no hay mucha estructura que aprender. Hay tres caminos: más historia,
> variables externas —órdenes de trabajo programadas, paros de planta, plan de
> producción, que es la mejora con mayor retorno esperado— o **aceptar el
> resultado**: si el promedio móvil basta, el valor del sistema está en la
> optimización y la trazabilidad, no en el forecast. Es una conclusión legítima y
> prefiero decirla.»

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
Costo_quiebre  =  dias_expuestos  ×  tasa_de_salida  ×  costo_por_dia(criticidad)
```

| Símbolo | Qué es | Unidad | Valor |
|---|---|---|---|
| `dias_expuestos` | Días de quiebre que evita reponer ahora en vez de esperar a la siguiente corrida | días | Calculado |
| `tasa_de_salida` | Proporción de días en que la pieza se pide realmente | fracción 0–1 | Medida por serie |
| `costo_por_dia` | Costo diario del quiebre según criticidad | USD/día | A = 400 · B = 80 · C = 10 |

**La sutileza que vale la pena explicar:** «Multiplicamos por la tasa de salida
porque **no todos los días sin existencias cuestan lo mismo**. Un día sin la pieza
solo interrumpe algo si ese día alguien la pide, y en refacciones eso ocurre en
una minoría de los días. Sin esa corrección, la valoración triplica el riesgo y
produce cifras que nadie puede defender frente a finanzas.»

### 5.3 La pregunta que hay que hacerle a la sala

> **«Los 400 USD/día de una pieza crítica son un parámetro que pusimos nosotros.
> ¿Cuánto cuesta realmente una hora de paro en Nava? Esa cifra la tiene
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
> cuesta parar la línea. Si el sistema asume 6,67 USD por unidad faltante y
> operaciones dice 400, el nivel de servicio está gravemente mal calibrado.»

### 5.5 La composición del catálogo, en una frase

> «Cuatro piezas —el **20 % de las referencias**— concentran el **44,6 % del
> gasto anual** *y* son de criticidad A. Ahí es donde el sistema se paga solo. En
> el otro extremo, seis referencias son el 30 % de la variedad y el 4,2 % del
> valor: ahí la política correcta es stock generoso y dejar de pensar en ellas.»

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

**La limitación honesta:** con muchos ceros —más del 40 % de los meses— ningún
método clásico funciona bien y hay que pasar a **Croston** o **SBA**, que
descomponen la serie en *cada cuánto ocurre* y *cuánto se lleva cuando ocurre*, y
suavizan cada parte por separado. **Hoy no está implementado**, porque el
histórico actual solo tiene 3,3 % de meses en cero y no lo justifica. Está
identificado como el paso siguiente si el dato real resulta intermitente.

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
en la banda de «requiere una persona». Hoy son 7 de 40.

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
Imin  =  d · L  +  z(k) · sqrt( L · sigma_d²  +  d² · sigma_L² )
```

En palabras: **lo que espero consumir mientras llega el pedido, más un colchón
que absorbe dos incertidumbres a la vez** — que la demanda sea mayor de lo
previsto y que el proveedor entregue más tarde de lo habitual.

Con números reales del sistema: lead time 10,6 días, σ del lead time 5,45 días.
Para una pieza con demanda de 15 unidades/mes y criticidad A (`z = 1,65`), el
mínimo sale alrededor de 13 unidades — de las cuales unas 5,8 son la demanda del
lead time y 6,6 el colchón.

**Es la fórmula estándar de la industria**, Hadley & Whitin 1963, la misma que
usan los módulos MRP de SAP y Oracle. No es una invención del proyecto.

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
- Incorpora σ del lead time, que **con σ/μ ≈ 0,53 aporta la mitad de la varianza**.
  Un mínimo fijo que ignore esto queda 30–40 % corto.

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
3. **Continuidad de producción como restricción dura** en vez de presupuesto
   primero (§14 del spec).
4. **Chat de trazabilidad** para responder contrafactuales: «¿cuánto presupuesto
   necesito para no aplazar nada?» (§15 del spec).
5. Bucle de feedback — lo que convierte el MVP en un sistema que aprende.
6. Traslado entre plantas — el ahorro está medido.
7. Variables externas en el modelo — la única vía para que el forecast mejore.

---

## 7. Guion de 10 minutos

| Min | Bloque | Mensaje clave |
|---|---|---|
| 0–2 | **El problema** | «Dos costos opuestos, uno con doliente y otro sin él» |
| 2–3 | **Los datos** | «Qué es real, qué es sintético, y qué encontramos al limpiar» |
| 3–5 | **La composición** | «El 20 % de las referencias es el 44,6 % del gasto y además para línea» |
| 5–7 | **Cómo decide** | Las tres fórmulas: inventario mínimo, MILP, mochila |
| 7–8 | **El resultado** | «2.500 USD evitan 12.486 de quiebre: 5,1×» |
| 8–9 | **Las limitaciones** | Intermitencia, modelo vs. promedio móvil, dato sintético |
| 9–10 | **La pregunta** | «¿Cuánto cuesta realmente una hora de paro en Nava?» |

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
| [`Spec.md` §13.12](../Spec.md) | Los 12 supuestos del modelo y su consecuencia si fallan |
| [`Spec.md` §14](../Spec.md) | Diseño: continuidad de producción como restricción dura |
| [`Spec.md` §15](../Spec.md) | Diseño: chat de explicabilidad y trazabilidad |
