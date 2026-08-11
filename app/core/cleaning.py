"""Limpieza de las fuentes crudas.

Funcionalidad:
    Corrige los problemas concretos detectados en los datos de origen y deja
    constancia de cada correccion. La limpieza es explicita y auditable: cada
    funcion devuelve la tabla corregida junto con la bitacora de lo que hizo y
    cuantas filas afecto.

    No se imputan valores silenciosamente. Cuando un registro no sirve para su
    proposito se descarta y se registra por que, porque en abastecimiento un
    dato inventado se convierte en una orden de compra equivocada.
"""

import numpy as np
import pandas as pd

from app.core.profiling import detect_outliers_mad

DELIVERED_STATUSES = ["Delivered", "Partially Delivered"]

MIN_DAYS_PER_MONTH = 20

MAX_PLAUSIBLE_LEAD_DAYS = 365

SENSOR_COLUMNS = [
    "temp_bearing_degC",
    "temp_motor_degC",
    "vibration_h_mms",
    "vibration_v_mms",
    "oil_pressure_bar",
    "load_pct",
    "shaft_rpm",
    "power_consumption_kw",
]


def clean_procurement(frame: pd.DataFrame) -> tuple:
    """Depura el historico de ordenes de compra.

    Entrada:
        frame: tabla cruda de ordenes.

    Salida:
        Tupla (tabla limpia, bitacora) donde la bitacora es una lista de
        diccionarios con la regla aplicada y las filas afectadas.

    Funcionalidad:
        Descarta las ordenes que no sirven para medir plazos de entrega y anade
        la columna lead_days ya validada.

        La correccion de fondo es filtrar por estado. El archivo trae ordenes
        canceladas y pendientes que tienen fecha de entrega registrada; contarlas
        como entregas reales contamina el plazo que despues usa el optimizador.
        Son 130 de 689 registros con fecha.
    """
    log = []
    clean = frame.copy()
    start = len(clean)

    clean["Order_Date"] = pd.to_datetime(clean["Order_Date"], errors="coerce")
    clean["Delivery_Date"] = pd.to_datetime(clean["Delivery_Date"], errors="coerce")

    missing_dates = clean["Order_Date"].isna() | clean["Delivery_Date"].isna()
    if missing_dates.any():
        log.append(
            {
                "regla": "Descartar ordenes sin fecha de pedido o de entrega",
                "motivo": "Sin ambas fechas no se puede medir el plazo",
                "filas": int(missing_dates.sum()),
            }
        )
        clean = clean[~missing_dates]

    not_delivered = ~clean["Order_Status"].isin(DELIVERED_STATUSES)
    if not_delivered.any():
        log.append(
            {
                "regla": f"Conservar solo ordenes en estado {DELIVERED_STATUSES}",
                "motivo": "Una orden cancelada o pendiente no evidencia un plazo real",
                "filas": int(not_delivered.sum()),
            }
        )
        clean = clean[~not_delivered]

    clean["lead_days"] = (clean["Delivery_Date"] - clean["Order_Date"]).dt.days

    invalid_lead = (clean["lead_days"] <= 0) | (clean["lead_days"] > MAX_PLAUSIBLE_LEAD_DAYS)
    if invalid_lead.any():
        log.append(
            {
                "regla": f"Descartar plazos fuera de (0, {MAX_PLAUSIBLE_LEAD_DAYS}] dias",
                "motivo": "Entrega anterior al pedido o plazo implausible",
                "filas": int(invalid_lead.sum()),
            }
        )
        clean = clean[~invalid_lead]

    impossible = clean["Defective_Units"] > clean["Quantity"]
    if impossible.any():
        log.append(
            {
                "regla": "Descartar ordenes con mas defectuosos que unidades",
                "motivo": "Inconsistencia aritmetica en el registro",
                "filas": int(impossible.sum()),
            }
        )
        clean = clean[~impossible]

    clean["Defective_Units"] = clean["Defective_Units"].fillna(0)
    log.append(
        {
            "regla": "Imputar Defective_Units nulo como cero",
            "motivo": "Ausencia de registro significa que no se reportaron defectos",
            "filas": int(frame["Defective_Units"].isna().sum()),
        }
    )

    log.append(
        {
            "regla": "RESULTADO",
            "motivo": f"De {start} filas quedan {len(clean)}",
            "filas": start - len(clean),
        }
    )
    return clean.reset_index(drop=True), log


def clean_spine(frame: pd.DataFrame) -> tuple:
    """Depura el historico de consumo de refacciones.

    Entrada:
        frame: tabla cruda de movimientos diarios.

    Salida:
        Tupla (tabla limpia, bitacora).

    Funcionalidad:
        Normaliza tipos, elimina duplicados por llave y descarta los meses con
        cobertura insuficiente.

        Dos decisiones que parecen anomalias y no lo son. El 90 por ciento de
        filas con consumo cero no es un defecto sino la naturaleza intermitente
        del consumo de refacciones, y se conserva porque la ausencia de consumo
        es informacion. El 80 por ciento de nulos en wo_type tampoco es un
        defecto: esa columna solo aplica cuando el movimiento nace de una orden
        de trabajo, asi que se rellena con una categoria explicita en vez de
        descartar la columna.
    """
    log = []
    clean = frame.copy()
    start = len(clean)

    clean["transaction_date"] = pd.to_datetime(clean["transaction_date"], errors="coerce")
    invalid_date = clean["transaction_date"].isna()
    if invalid_date.any():
        log.append(
            {
                "regla": "Descartar movimientos sin fecha valida",
                "motivo": "No se pueden ubicar en el tiempo",
                "filas": int(invalid_date.sum()),
            }
        )
        clean = clean[~invalid_date]

    duplicated = clean.duplicated(subset=["transaction_date", "asset_tag", "part_no"])
    if duplicated.any():
        log.append(
            {
                "regla": "Eliminar duplicados por fecha, activo y pieza",
                "motivo": "Un mismo movimiento cargado dos veces duplicaria el consumo",
                "filas": int(duplicated.sum()),
            }
        )
        clean = clean[~duplicated]

    negative = clean["qty_issued"] < 0
    if negative.any():
        log.append(
            {
                "regla": "Descartar consumos negativos",
                "motivo": "Una salida de material no puede ser negativa",
                "filas": int(negative.sum()),
            }
        )
        clean = clean[~negative]

    nulls_wo = int(clean["wo_type"].isna().sum())
    clean["wo_type"] = clean["wo_type"].fillna("SIN_ORDEN")
    log.append(
        {
            "regla": "Rellenar wo_type nulo con SIN_ORDEN",
            "motivo": "El nulo significa movimiento sin orden de trabajo asociada",
            "filas": nulls_wo,
        }
    )

    clean["breakdown_flag"] = clean["breakdown_flag"].fillna(0).astype(int)

    period = clean["transaction_date"].dt.strftime("%Y-%m")
    days = clean.groupby(period)["transaction_date"].transform("nunique")
    incomplete = days < MIN_DAYS_PER_MONTH
    if incomplete.any():
        months = sorted(period[incomplete].unique())
        log.append(
            {
                "regla": f"Descartar meses con menos de {MIN_DAYS_PER_MONTH} dias registrados",
                "motivo": f"Meses incompletos se leerian como caida de demanda: {months}",
                "filas": int(incomplete.sum()),
            }
        )
        clean = clean[~incomplete]

    log.append(
        {
            "regla": "RESULTADO",
            "motivo": f"De {start} filas quedan {len(clean)}",
            "filas": start - len(clean),
        }
    )
    return clean.reset_index(drop=True), log


def flag_sensor_outliers(frame: pd.DataFrame) -> tuple:
    """Marca lecturas de sensor anomalas sin eliminarlas.

    Entrada:
        frame: tabla de movimientos con columnas de sensor.

    Salida:
        Tupla (tabla con la columna sensor_outlier anadida, bitacora).

    Funcionalidad:
        Se marca en lugar de descartar a proposito. Una vibracion o temperatura
        extrema suele ser justamente la senal de que la maquina esta fallando, es
        decir el evento que anticipa el consumo de refacciones. Eliminar esas
        filas borraria la informacion mas valiosa del conjunto.

        La deteccion usa desviacion absoluta mediana, que no se desplaza por la
        presencia de los propios extremos.
    """
    clean = frame.copy()
    available = [column for column in SENSOR_COLUMNS if column in clean.columns]

    marks = pd.DataFrame(index=clean.index)
    for column in available:
        marks[column] = detect_outliers_mad(clean[column])

    clean["sensor_outlier"] = marks.any(axis=1).astype(int) if available else 0
    flagged = int(clean["sensor_outlier"].sum())

    log = [
        {
            "regla": "Marcar lecturas de sensor atipicas",
            "motivo": "Se conservan porque una lectura extrema anticipa la falla",
            "filas": flagged,
        }
    ]
    return clean, log


def demand_outlier_report(demand: pd.DataFrame) -> pd.DataFrame:
    """Identifica meses de consumo atipico por serie.

    Entrada:
        demand: historico mensual con sku_id, city_id, period_month y qty_issued.

    Salida:
        DataFrame con los meses marcados como atipicos y su puntaje.

    Funcionalidad:
        Evalua cada serie contra si misma, no contra el conjunto, porque una
        pieza que consume 100 unidades al mes y otra que consume 2 tienen escalas
        incomparables. Estos meses no se corrigen: se reportan para que
        mantenimiento confirme si hubo un evento real, como una parada mayor, o
        si fue un error de captura.
    """
    rows = []
    for (sku, city), group in demand.groupby(["sku_id", "city_id"]):
        values = group["qty_issued"]
        flagged = detect_outliers_mad(values)
        rows.extend(
            {
                "sku_id": sku,
                "city_id": city,
                "period_month": group.loc[index, "period_month"],
                "qty_issued": int(values.loc[index]),
                "median_series": float(values.median()),
            }
            for index in values.index[flagged]
        )

    report = pd.DataFrame(
        rows,
        columns=[
            "sku_id",
            "city_id",
            "period_month",
            "qty_issued",
            "median_series",
        ],
    )
    if len(report):
        report["ratio_vs_median"] = (
            report["qty_issued"] / report["median_series"].replace(0, np.nan)
        ).round(2)
    return report
