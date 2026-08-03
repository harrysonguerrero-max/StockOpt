# Spec — MVP de optimización de inventario con IA

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

### Etapa 1. Ingesta y preparación de datos
Se consolidan los datos necesarios para la recomendación: inventario actual, historial de consumo, catálogo de piezas, proveedores, ciudades, precios, lead time y vida útil. En el MVP estos datos pueden provenir de archivos CSV o tablas simples para reducir complejidad inicial.

**Tecnologías posibles**
- Python
- Pandas
- CSV / SQLite / Postgres

#### 1.1 Validación explícita de datos
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

#### 1.2 Ingesta manual de datos de proveedores de piezas
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

### Etapa 1.3 Clasificación de patrones de demanda
Antes de hacer la proyección, se analiza el historial de consumo para clasificar el patrón de demanda de cada pieza, informando qué modelo y qué nivel de confianza esperar:

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

### Etapa 4. Reglas de negocio y restricciones operativas
Antes de emitir la recomendación final, la solución debe aplicar reglas operativas. Estas reglas limitan lo que el optimizador puede recomendar y garantizan alineación con la operación real.

**Restricciones mínimas del MVP**
- No comprar si el inventario proyectado permanece por encima del mínimo.
- No superar el inventario máximo definido.
- No recomendar cantidades que excedan la demanda consumible dentro de la vida útil.
- No seleccionar proveedores que no operen para la ciudad requerida.
- No exceder capacidad máxima de compra o presupuesto del escenario.
- Permitir marcación de casos que requieran revisión humana.

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
- 10 a 20 piezas.
- 2 ciudades.
- 3 a 5 proveedores.
- 6 a 12 meses de histórico.
- Un único flujo de recomendación por corrida.
- Datos batch, no streaming.
- Sin integración directa con ERP en la primera versión.

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
1. Fuente de datos de inventario y proveedores.
2. Módulo de validación y limpieza de datos.
3. Módulo de entrada manual de datos de proveedores.
4. Clasificador de patrones de demanda.
5. Modelo ML de proyección de demanda (con tiempos variables y confianza).
6. Módulo de optimización MILP.
7. Motor de reglas de negocio.
8. Capa LLM de explicación con comunicación de supuestos.
9. Interfaz de usuario para visualización, aprobación y confirmación de compra manual.
10. Sistema de feedback y reentrenamiento.

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


## 11. Colores de MVP

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