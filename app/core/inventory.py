"""Politica de inventario compartida.

    Define tambien el nivel de servicio por criticidad y los dias por mes, que
    son parametros de negocio usados por la construccion del dataset, la
    proyeccion y la optimizacion. Viven aqui por ser la unica definicion.

Funcionalidad:
    Define en un unico lugar como se calcula el nivel minimo de inventario de
    una pieza. Tanto la construccion del dataset como la proyeccion de demanda
    consumen estas funciones, de modo que exista una sola definicion de
    "inventario minimo" en todo el sistema.

    El minimo cubre la demanda esperada durante el tiempo que tarda en llegar
    una reposicion, mas un colchon que absorbe dos incertidumbres a la vez: que
    la demanda sea mayor de lo previsto y que el proveedor entregue mas tarde de
    lo habitual.
"""

import numpy as np

DAYS_PER_MONTH = 30

Z_BY_CRITICALITY = {"A": 1.65, "B": 1.28, "C": 0.84}


def safety_stock(
    daily_demand: float, daily_std: float, lead_time: float, lead_time_std: float, z: float
) -> float:
    """Calcula el colchon de seguridad de una pieza.

    Entrada:
        daily_demand: demanda media diaria.
        daily_std: desviacion tipica de la demanda diaria.
        lead_time: tiempo de entrega en dias.
        lead_time_std: variabilidad del tiempo de entrega en dias.
        z: factor de nivel de servicio segun criticidad de la pieza.

    Salida:
        Unidades del colchon de seguridad.

    Funcionalidad:
        Compone la varianza de la demanda durante el tiempo de entrega sumando
        la contribucion de la demanda y la del propio plazo de entrega. Ignorar
        la segunda dejaria el minimo corto cuando el proveedor es irregular,
        como ocurre aqui con entregas que oscilan entre 1 y 20 dias.
    """
    variance = lead_time * daily_std**2 + (daily_demand**2) * (lead_time_std**2)
    return float(z * np.sqrt(max(variance, 0.0)))


def monthly_to_daily(monthly_mean: float, monthly_std: float) -> tuple:
    """Convierte estadisticas mensuales de demanda a base diaria.

    Entrada:
        monthly_mean: demanda media mensual.
        monthly_std: desviacion tipica mensual.

    Salida:
        Tupla (demanda_diaria, desviacion_diaria).

    Funcionalidad:
        La media se reparte entre los dias del mes y la desviacion se escala por
        la raiz del numero de dias, como corresponde a la suma de variaciones
        diarias independientes.
    """
    days = DAYS_PER_MONTH
    return (monthly_mean / days, monthly_std / np.sqrt(days))


def inventory_minimum(
    monthly_mean: float, monthly_std: float, lead_time: float, lead_time_std: float, z: float
) -> tuple:
    """Calcula el inventario minimo de una pieza.

    Entrada:
        monthly_mean: demanda media mensual esperada.
        monthly_std: desviacion tipica mensual de la demanda.
        lead_time: tiempo de entrega en dias.
        lead_time_std: variabilidad del tiempo de entrega en dias.
        z: factor de nivel de servicio segun criticidad de la pieza.

    Salida:
        Tupla (demanda_durante_entrega, colchon_seguridad, minimo_redondeado).

    Funcionalidad:
        Traduce la demanda mensual al horizonte real de reposicion y le suma el
        colchon de seguridad. El minimo se redondea hacia arriba porque las
        piezas se compran en unidades enteras.
    """
    daily_demand, daily_std = monthly_to_daily(monthly_mean, monthly_std)
    demand_lead_time = daily_demand * lead_time
    buffer = safety_stock(daily_demand, daily_std, lead_time, lead_time_std, z)
    return (demand_lead_time, buffer, int(np.ceil(demand_lead_time + buffer)))


def planning_lead_time(suppliers) -> tuple:
    """Determina el tiempo de entrega usado para planificar.

    Entrada:
        suppliers: catalogo de proveedores con sus metricas de lead time.

    Salida:
        Tupla (lead_time_dias, desviacion_dias).

    Funcionalidad:
        Promedia el plazo y la variabilidad de los proveedores activos. Sirve de
        referencia mientras no se ha elegido proveedor: el optimizador
        recalculara con el plazo del que finalmente seleccione.
    """
    active = suppliers[suppliers["active"]] if "active" in suppliers else suppliers
    return (float(active["lead_time_avg_days"].mean()), float(active["lead_time_std_days"].mean()))
