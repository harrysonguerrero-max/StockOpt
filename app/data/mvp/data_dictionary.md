# Diccionario de datos - MVP SupplyOpt

Montos en USD (1 USD = 83 INR).
Alcance: 20 piezas MRO x 2 ciudades x 5 proveedores, demanda mensual.
Ciudades: Nava (Coahuila) y Ciudad Obregon (Sonora).
El historico se desplaza para terminar en el horizonte configurado y se amplia
hacia atras con meses simulados, marcados con `is_synthetic`, hasta completar 72
meses.

## Fuentes
| Tabla generada | Fuente cruda |
|---|---|
| parts_master, demand_history, inventory_current | `synthetic_industrial_machine_data.csv` |
| suppliers, supplier_offers | `Procurement KPI Analysis Dataset.csv` |
| cities | `mapeo fijo de plant_code` |

## Llaves
- `sku_id` -> parts_master (PK). Referenciada por inventory, demand, offers.
- `city_id` -> cities (PK). Referenciada por inventory, demand, suppliers.
- `supplier_id` -> suppliers (PK). Referenciada por offers y coverage.
- `offer_id` = `supplier_id` + `_` + `sku_id` (PK de supplier_offers).

---

## cities.csv - Ciudades

Las dos plantas del alcance y su bodega asociada.

| Columna | Tipo | Unidad | Origen | Descripcion |
|---|---|---|---|---|
| city_id | str | - | Derivado de plant_code | Codigo corto de la ciudad. Llave primaria. |
| city_name | str | - | Mapeo fijo | Nombre para mostrar en pantalla. |
| country | str | - | Fijo | Pais de la planta. |
| warehouse_id | str | - | plant_code | Bodega que atiende esa ciudad. |

Las 3 plantas del dato crudo se consolidan en 2 ciudades: dos van a Nava, que es el complejo mayor, y una a Obregon.

---

## parts_master.csv - Maestro de piezas

Catalogo de las 20 refacciones del alcance.

| Columna | Tipo | Unidad | Origen | Descripcion |
|---|---|---|---|---|
| sku_id | str | - | part_no (real) | Codigo de la pieza. Llave primaria. |
| description | str | - | real | Descripcion comercial de la pieza. |
| category | str | - | part_family (real) | Familia a la que pertenece. |
| criticality | str A/B/C | - | real | Criticidad operativa. Fija el nivel de servicio. |
| uom | str | - | real | Unidad de medida en que se compra. |
| unit_cost_usd | float | USD | real, convertido de INR | Costo unitario en libros. |
| currency | str | - | fijo USD | Moneda de los montos. |
| shelf_life_days | int | dias | sintetico, por familia | Vida util. Limita cuanto se puede comprar de una vez. |

Vida util por familia: Lubrication 180, Filter 365, Seal & Gasket 730, Drive Belt 1095, Bearing 1825, Coupling 2555, Electrical 1825, Sensor 1825, Fastener 3650.

---

## inventory_current.csv - Inventario actual

Existencias por pieza y ciudad en el ultimo mes del historico.

| Columna | Tipo | Unidad | Origen | Descripcion |
|---|---|---|---|---|
| sku_id | str | - | FK parts_master | Pieza. |
| city_id | str | - | FK cities | Ciudad. |
| warehouse_id | str | - | derivado de city_id | Bodega donde estan las piezas. |
| snapshot_date | str | fecha | ultimo mes del historico | Fecha a la que corresponde el conteo. |
| on_hand_qty | int | uds | sintetico | Unidades disponibles hoy. |
| reorder_point | int | uds | sintetico | Nivel a partir del cual conviene reponer. |
| reorder_qty | int | uds | sintetico | Cantidad habitual de reposicion. |
| unit_cost_usd | float | USD | real | Costo unitario de la pieza. |
| stock_value_usd | float | USD | on_hand_qty * unit_cost_usd | Valor inmovilizado en esa combinacion. |
| below_reorder | int 0/1 | - | on_hand_qty < reorder_point | Marca si ya esta por debajo del punto de reorden. |

on_hand_qty = round(reorder_point * cobertura), con cobertura ~ U(0.35, 1.75).

reorder_point = ceil(mu + z*sigma), donde mu y sigma son la media y la desviacion de qty_issued mensual por sku x ciudad, y z vale 1.65 para criticidad A, 1.28 para B y 0.84 para C.

---

## demand_history.csv - Demanda historica

Consumo mensual por pieza y ciudad, con la señal operativa que lo acompaña.

| Columna | Tipo | Unidad | Origen | Descripcion |
|---|---|---|---|---|
| sku_id | str | - | FK parts_master | Pieza. |
| city_id | str | - | FK cities | Ciudad. |
| period_month | str | YYYY-MM | real | Mes al que corresponde el consumo. |
| qty_issued | int | uds | real, suma mensual | Unidades consumidas en el mes. |
| issue_events | int | dias | real | Dias del mes con algun consumo. Mide intermitencia. |
| breakdown_events | int | eventos | real | Averias registradas en el mes. |
| is_synthetic | int 0/1 | - | extend_history | Marca si el mes fue simulado para alargar la historia. |

La mitad de las filas son meses simulados: los reales terminan en el horizonte configurado y la historia se amplia hacia atras para alcanzar los 72 meses que exige detectar estacionalidad.

---

## suppliers.csv - Proveedores

Los 5 proveedores con sus plazos de entrega medidos sobre ordenes reales.

| Columna | Tipo | Unidad | Origen | Descripcion |
|---|---|---|---|---|
| supplier_id | str | - | asignado | Codigo del proveedor. Llave primaria. |
| name | str | - | real | Razon social. |
| city_id | str | - | asignado de forma ciclica | Ciudad donde tiene su base. |
| active | bool | - | fijo True | Si esta habilitado para recibir ordenes. |
| contact_email | str | - | sintetico | Correo al que se envia la orden. |
| base_freight_usd | float | USD | sintetico | Flete base antes del recargo por ciudad. |
| lead_time_avg_days | float | dias | real | Plazo medio entre pedido y entrega. |
| lead_time_min_days | int | dias | real | Mejor plazo observado. |
| lead_time_max_days | int | dias | real | Peor plazo observado. |
| lead_time_std_days | float | dias | real | Variabilidad del plazo. Alimenta el colchon de seguridad. |

Los cuatro plazos salen de Delivery_Date menos Order_Date sobre las ordenes entregadas. La variabilidad es alta: sigma sobre media ronda 0,53, asi que el colchon por plazo no es cosmetico.

---

## supplier_offers.csv - Ofertas proveedor-pieza

Precio, lote minimo y capacidad de cada proveedor para cada pieza.

| Columna | Tipo | Unidad | Origen | Descripcion |
|---|---|---|---|---|
| offer_id | str | - | supplier_id + sku_id | Llave primaria de la oferta. |
| supplier_id | str | - | FK suppliers | Proveedor que ofrece. |
| sku_id | str | - | FK parts_master | Pieza ofertada. |
| unit_price_usd | float | USD | sintetico | Precio por unidad. |
| moq | int | uds | sintetico | Lote minimo. Es la restriccion que produce los casos a revisar. |
| capacity_per_month | int | uds | sintetico | Cuanto puede surtir al mes. |
| currency | str | - | fijo USD | Moneda del precio. |

El margen por proveedor va de 1,05 a 1,17 en pasos de 0,03 sobre el costo en libros. Cada pieza recibe 2 o 3 ofertas, de modo que el optimizador siempre tenga contra que comparar.

El flete no vive aqui sino en supplier_coverage, porque depende de la ciudad de destino y no de la pieza.

---

## supplier_coverage.csv - Cobertura geografica

Que proveedor puede surtir que ciudad y con que recargo.

| Columna | Tipo | Unidad | Origen | Descripcion |
|---|---|---|---|---|
| supplier_id | str | - | FK suppliers | Proveedor. |
| city_id | str | - | FK cities | Ciudad que atiende. |
| is_home | int 0/1 | - | derivado | Si es su ciudad base. |
| freight_cost_usd | float | USD | derivado del flete base | Flete hacia esa ciudad. |
| lead_time_extra_days | int | dias | derivado | Dias adicionales cuando surte fuera de su base. |

Sin esta tabla el optimizador quedaba infactible para una de cada cuatro combinaciones, porque ningun proveedor atendia la ciudad.

---

## demand_patterns.csv - Patrones de demanda

Clasificacion de cada serie y las medidas que la sustentan.

| Columna | Tipo | Unidad | Origen | Descripcion |
|---|---|---|---|---|
| sku_id | str | - | FK parts_master | Pieza. |
| city_id | str | - | FK cities | Ciudad. |
| n_periods | int | meses | calculado | Meses de historia disponibles. |
| mean_monthly | float | uds | calculado | Consumo medio mensual. |
| std_monthly | float | uds | calculado | Desviacion tipica mensual. |
| cv | float | - | std / mean | Coeficiente de variacion. Decide si la serie es volatil. |
| zero_ratio | float | - | calculado | Proporcion de meses sin consumo. |
| seasonal_strength | float | - | seasonal_decompose | Fuerza del componente estacional. |
| seasonal_pvalue | float | - | Kruskal-Wallis | Significancia del efecto del mes. |
| trend_tau | float | - | Mann-Kendall | Direccion y fuerza de la tendencia. |
| trend_pvalue | float | - | Mann-Kendall | Significancia de la tendencia. |
| pattern | str | - | reglas de clasificacion | Etiqueta final: Estacional, Tendencia, Estable, Volatil o Insuficiente. |
| confidence | float 0-1 | - | calculado | Cuanta confianza merece esa etiqueta. |
| recommended_model | str | - | derivado del patron | Metodo de proyeccion que corresponde al patron. |

Se clasifica por pieza y ciudad, no solo por pieza: 8 de 20 piezas cambian de patron segun la planta.

Estacional exige dos condiciones a la vez, fuerza mayor o igual a 0,45 y efecto de mes significativo, porque la fuerza por si sola marca como estacional hasta el ruido.

---

## demand_forecast.csv - Proyeccion de demanda

Lo que sale del modelo por serie, y el inventario minimo que se deriva.

| Columna | Tipo | Unidad | Origen | Descripcion |
|---|---|---|---|---|
| sku_id | str | - | FK parts_master | Pieza. |
| city_id | str | - | FK cities | Ciudad. |
| pattern | str | - | demand_patterns | Patron detectado para la serie. |
| method | str | - | derivado del patron | Metodo estadistico aplicado. |
| n_periods | int | meses | calculado | Meses usados para proyectar. |
| forecast_q25 | float | uds | calculado | Escenario bajo de demanda mensual. |
| forecast_q50 | float | uds | calculado | Demanda mensual esperada. Es la que entra al optimizador. |
| forecast_q75 | float | uds | calculado | Escenario alto de demanda mensual. |
| wmape_backtest | float | - | backtest | Error del metodo sobre la propia serie. |
| confidence_pattern | float 0-1 | - | demand_patterns | Confianza que aporta el patron. |
| confidence_final | float 0-1 | - | calculado | Confianza combinada. Por debajo del umbral marca revision. |
| lead_time_days | float | dias | suppliers | Plazo de reposicion usado para planificar. |
| demand_lead_time | float | uds | inventory_policy | Demanda esperada mientras llega la reposicion. |
| safety_stock | float | uds | inventory_policy | Colchon que absorbe la variabilidad de demanda y de plazo. |
| inventory_min | int | uds | demand_lead_time + safety_stock | Nivel minimo operativo de la pieza. |
| issue_rate | float 0-1 | - | issue_events / 30 | Con que frecuencia se pide la pieza. Escala el costo de quiebre. |
| forecast_model | float | uds | modelo ML | Proyeccion del modelo global entrenado. |
| forecast_source | str | - | calculado | Si la cifra final viene del modelo, del metodo estadistico o de ambos. |
| needs_review | int 0/1 | - | calculado | Marca las series cuya proyeccion no es confiable. |

El minimo se unifico aqui: antes el dataset cubria un mes completo y la proyeccion solo el plazo real, y ambas etapas daban respuestas opuestas sobre que reponer.

issue_rate recoge la intermitencia del consumo: la mediana de estas series tiene movimiento once dias de cada treinta. Un dia sin existencias solo cuesta dinero si ese dia alguien pide la pieza.

---

## purchase_recommendations.csv - Recomendaciones de compra

La decision final por pieza y ciudad, con su motivo.

| Columna | Tipo | Unidad | Origen | Descripcion |
|---|---|---|---|---|
| sku_id | str | - | FK parts_master | Pieza. |
| city_id | str | - | FK cities | Ciudad. |
| description | str | - | parts_master | Descripcion de la pieza. |
| criticality | str A/B/C | - | parts_master | Criticidad operativa. |
| on_hand_qty | int | uds | inventory_current | Existencias actuales. |
| inventory_min | int | uds | demand_forecast | Nivel minimo que hay que sostener. |
| inventory_max | int | uds | cobertura objetivo | Techo de bodega para esa pieza. |
| demand_monthly | float | uds | demand_forecast | Demanda mensual proyectada. |
| forecast_source | str | - | demand_forecast | De donde sale la proyeccion usada. |
| shelf_life_days | int | dias | parts_master | Vida util de la pieza. |
| target_qty | int | uds | calculado | Cantidad que llevaria al nivel objetivo. |
| max_allowed_qty | int | uds | calculado | Tope por bodega y por vida util. |
| coverage_months | float | meses | calculado | Meses de inventario que dejaria la compra. |
| decision | str | - | optimizador | COMPRAR, NO_COMPRAR, REVISAR o APLAZADO. |
| recommended_qty | int | uds | optimizador | Unidades a pedir. |
| supplier_id | str | - | optimizador | Proveedor elegido. |
| supplier_name | str | - | suppliers | Nombre del proveedor elegido. |
| unit_price_usd | float | USD | supplier_offers | Precio unitario aplicado. |
| freight_cost_usd | float | USD | supplier_coverage | Flete de la orden. |
| lead_time_days | float | dias | suppliers | Plazo del proveedor elegido. |
| total_cost_usd | float | USD | precio * cantidad + flete | Costo total de la orden. |
| alternatives_evaluated | int | ofertas | optimizador | Cuantas ofertas compitieron. |
| confidence | float 0-1 | - | demand_forecast | Confianza de la proyeccion que sustenta la decision. |
| stockout_cost_usd | float | USD | calculado | Costo del quiebre que evita reponer ahora en lugar de esperar. |
| net_benefit_usd | float | USD | quiebre evitado - costo | Lo que rinde la compra. Si es negativo, no se hace. |
| needs_review | int 0/1 | - | calculado | Marca las filas que exigen criterio humano. |
| reason | str | - | optimizador | Motivo explicito de la decision. |

REVISAR no es un fallo del solver: aparece cuando el lote minimo del proveedor supera el maximo que la pieza admite en bodega, que es una tension real de compras y la decide una persona.

APLAZADO marca una reposicion tecnicamente correcta que no cabe en el presupuesto de la corrida. Conserva cantidad, proveedor y costo, porque es la cifra con la que se pide una ampliacion.

El costo de quiebre se estima como los dias que la pieza estaria sin existencias por el costo diario de su criticidad, y ese costo diario es un parametro de negocio que hay que validar con mantenimiento: su magnitud decide por si sola cuanto pesa la criticidad frente al precio.

La estimacion es deterministica y supone que la demanda ocurre al ritmo proyectado, asi que subestima el riesgo en las series volatiles.

---

## quality/demand_outliers.csv - Meses de consumo atipico

Meses que se apartan de su propia serie y piden confirmacion de mantenimiento.

| Columna | Tipo | Unidad | Origen | Descripcion |
|---|---|---|---|---|
| sku_id | str | - | FK parts_master | Pieza. |
| city_id | str | - | FK cities | Ciudad. |
| period_month | str | YYYY-MM | demand_history | Mes señalado. |
| qty_issued | int | uds | demand_history | Consumo observado ese mes. |
| median_series | float | uds | calculado | Consumo tipico de esa misma serie. |
| ratio_vs_median | float | - | qty_issued / median_series | Cuantas veces se aparta de lo habitual. |

Se evaluan contra la propia serie y no contra el conjunto: una pieza de 100 unidades al mes y otra de 2 tienen escalas incomparables.

Se reportan, no se corrigen. Puede haber sido una parada mayor real.
