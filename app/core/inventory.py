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
from scipy import stats

DAYS_PER_MONTH = 30

Z_BY_CRITICALITY = {"A": 1.65, "B": 1.28, "C": 0.84}

SERVICE_LEVEL_BY_Z = {1.65: 0.95, 1.28: 0.90, 0.84: 0.80}


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


def service_level(z: float) -> float:
    """Traduce el factor de servicio al nivel de servicio que representa.

    Entrada:
        z: factor de seguridad de la criticidad.

    Salida:
        Probabilidad de no quedarse sin existencias durante el ciclo.

    Funcionalidad:
        Los tres `z` del sistema son la unica declaracion de politica de
        servicio que existe, y estan escritos como factores normales. Para tomar
        un cuantil sobre una distribucion que no es normal hace falta el nivel
        que esos factores representan, no el factor en si.

        Se resuelve por tabla y no por la inversa de la normal para que el nivel
        declarado sea exactamente el que dice la documentacion —95, 90 y 80 por
        ciento— en lugar de un numero con decimales que nadie escribio.
    """
    known = SERVICE_LEVEL_BY_Z.get(round(float(z), 2))
    return known if known is not None else float(stats.norm.cdf(z))


def demand_quantile(mean: float, variance: float, level: float) -> float:
    """Toma el cuantil de la demanda acumulada durante el plazo de entrega.

    Entrada:
        mean: demanda esperada durante el plazo.
        variance: varianza de esa demanda.
        level: nivel de servicio deseado.

    Salida:
        Unidades por debajo de las cuales queda la demanda con esa probabilidad.

    Funcionalidad:
        Sustituye a la aproximacion `media + z * desviacion`, que supone que la
        demanda durante el plazo es normal. Con consumo intermitente no lo es:
        la mayoria de los meses no se pide nada y de vez en cuando se pide un
        lote, asi que la distribucion esta sesgada a la derecha y la
        aproximacion normal deja el servicio real por debajo del nominal. Es
        exactamente la limitacion que Eppen y Martin (1988) describen y que el
        sistema declaraba sin corregir.

        Se elige una binomial negativa cuando la varianza supera a la media, que
        es el caso normal en refacciones y el motivo de que a esta distribucion
        se la llame Poisson sobredispersada. Sus dos parametros se resuelven
        igualando media y varianza a las observadas, de modo que el colchon
        recoja la misma incertidumbre que antes pero repartida con la forma
        correcta.

        Si la varianza no supera a la media, la binomial negativa no esta
        definida y se recurre a una Poisson, que es su limite. Y si no hay ni
        media ni varianza, no hay nada que cubrir.
    """
    if mean <= 0:
        return 0.0
    if variance <= mean:
        return float(stats.poisson.ppf(level, mean))

    probability = mean / variance
    successes = mean * probability / (1.0 - probability)
    return float(stats.nbinom.ppf(level, successes, probability))


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
        Traduce la demanda mensual al horizonte real de reposicion y busca el
        nivel que cubre esa demanda con la probabilidad que declara la
        criticidad de la pieza.

        La varianza se compone igual que antes, sumando la incertidumbre de la
        demanda y la del plazo de entrega. Lo que cambia es como se convierte esa
        varianza en unidades: en lugar de multiplicarla por un factor normal, se
        toma el cuantil de una distribucion sesgada a la derecha, que es la forma
        que de verdad tiene la demanda de una refaccion durante un plazo.

        El colchon de seguridad se sigue reportando como la diferencia entre ese
        nivel y la demanda esperada, de modo que las dos mitades del minimo
        —lo que se consume mientras se espera y lo que absorbe la variabilidad—
        se puedan leer por separado como hasta ahora.

        El minimo se redondea hacia arriba porque las piezas se compran en
        unidades enteras. En las series de mucho volumen el resultado coincide
        practicamente con la formula normal, que es lo esperable: la binomial
        negativa converge a la normal cuando la media crece.
    """
    daily_demand, daily_std = monthly_to_daily(monthly_mean, monthly_std)
    demand_lead_time = daily_demand * lead_time
    variance = lead_time * daily_std**2 + (daily_demand**2) * (lead_time_std**2)

    level = demand_quantile(demand_lead_time, max(variance, 0.0), service_level(z))
    buffer = max(0.0, level - demand_lead_time)
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
