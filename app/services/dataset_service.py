"""Construccion de las tablas del dataset MVP de inventario.

Funcionalidad:
    Transforma los CSV crudos de app/data en las cuatro entradas de datos del
    proyecto: maestro de piezas, inventario actual, demanda historica y
    proveedores con su catalogo de ofertas. Cada funcion es pura: recibe
    DataFrames y devuelve un DataFrame, sin escribir en disco ni alterar las
    fuentes.
"""

import math
from pathlib import Path

import pandas as pd

from app.core import dataset_config as config

CITY_TO_WAREHOUSE = {v["city_id"]: v["warehouse_id"] for v in config.CITY_MAP.values()}


def load_spine(raw_dir: Path) -> pd.DataFrame:
    """Carga el historico de consumo de repuestos por planta.

    Entrada:
        raw_dir: carpeta que contiene los CSV crudos.

    Salida:
        DataFrame con el consumo diario por planta y pieza, con
        transaction_date convertida a fecha y breakdown_flag como entero.

    Funcionalidad:
        Lee el dataset columna vertebral del proyecto, del que salen las piezas,
        su criticidad, su costo y toda la serie de demanda.
    """
    df = pd.read_csv(raw_dir / "synthetic_industrial_machine_data.csv")
    df["transaction_date"] = pd.to_datetime(df["transaction_date"])
    df["breakdown_flag"] = df["breakdown_flag"].fillna(0).astype(int)
    return df


def load_procurement(raw_dir: Path) -> pd.DataFrame:
    """Carga el historico de ordenes de compra.

    Entrada:
        raw_dir: carpeta que contiene los CSV crudos.

    Salida:
        DataFrame de ordenes con Order_Date y Delivery_Date convertidas a fecha.

    Funcionalidad:
        Provee la fuente de proveedores y de los tiempos de entrega reales, que
        se calculan como la diferencia entre ambas fechas.
    """
    df = pd.read_csv(raw_dir / "Procurement KPI Analysis Dataset.csv")
    df["Order_Date"] = pd.to_datetime(df["Order_Date"], errors="coerce")
    df["Delivery_Date"] = pd.to_datetime(df["Delivery_Date"], errors="coerce")
    return df


def build_cities() -> pd.DataFrame:
    """Construye el catalogo de ciudades y bodegas.

    Entrada:
        Ninguna. Toma el mapeo declarado en la configuracion.

    Salida:
        DataFrame con city_id, city_name, country y warehouse_id.

    Funcionalidad:
        Deduplica el mapeo de plantas a ciudades, ya que varias plantas del dato
        crudo pueden consolidarse en una misma ciudad de la operacion.
    """
    seen = {}
    for entry in config.CITY_MAP.values():
        seen.setdefault(entry["city_id"], entry)
    rows = [seen[city_id] for city_id in config.CITY_IDS]
    return pd.DataFrame(rows)[["city_id", "city_name", "country", "warehouse_id"]]


def build_parts_master(spine: pd.DataFrame) -> pd.DataFrame:
    """Construye el maestro de piezas.

    Entrada:
        spine: DataFrame de consumo devuelto por load_spine.

    Salida:
        DataFrame con una fila por pieza: sku_id, description, category,
        criticality, uom, unit_cost_usd, currency y shelf_life_days.

    Funcionalidad:
        Extrae los atributos estables de cada pieza, convierte el costo de rupias
        a dolares y asigna la vida util segun la familia a la que pertenece.
    """
    columns = ["part_no", "part_description", "part_family", "criticality", "uom", "unit_cost_inr"]
    parts = spine[columns].drop_duplicates("part_no").sort_values("part_no").reset_index(drop=True)
    return pd.DataFrame({
        "sku_id": parts["part_no"],
        "description": parts["part_description"],
        "category": parts["part_family"],
        "criticality": parts["criticality"],
        "uom": parts["uom"],
        "unit_cost_usd": (parts["unit_cost_inr"] * config.INR_TO_USD).round(2),
        "currency": "USD",
        "shelf_life_days": parts["part_family"].map(config.SHELF_LIFE_BY_FAMILY).astype(int),
    })


def build_demand_history(spine: pd.DataFrame) -> pd.DataFrame:
    """Agrega el consumo diario a grano mensual por pieza y ciudad.

    Entrada:
        spine: DataFrame de consumo devuelto por load_spine.

    Salida:
        DataFrame con sku_id, city_id, period_month, qty_issued, issue_events y
        breakdown_events, ordenado cronologicamente dentro de cada serie.

    Funcionalidad:
        Suma el consumo del mes, cuenta los dias con salida de material como
        medida de intermitencia y acumula los eventos de falla como señal
        operativa. Descarta los meses incompletos del extremo de la serie, ya
        que un mes con un solo dia registrado se leeria como una caida de la
        demanda a cero.
    """
    df = spine.copy()
    df["city_id"] = df["plant_code"].map(lambda p: config.CITY_MAP[p]["city_id"])
    df["period_month"] = df["transaction_date"].dt.strftime("%Y-%m")

    days_per_month = df.groupby("period_month")["transaction_date"].nunique()
    complete = days_per_month[days_per_month >= config.MIN_DAYS_PER_MONTH].index
    df = df[df["period_month"].isin(complete)]

    grouped = df.groupby(["part_no", "city_id", "period_month"], as_index=False).agg(
        qty_issued=("qty_issued", "sum"),
        issue_events=("qty_issued", lambda s: int((s > 0).sum())),
        breakdown_events=("breakdown_flag", "sum"),
    )
    grouped = grouped.rename(columns={"part_no": "sku_id"})
    grouped = grouped.sort_values(["sku_id", "city_id", "period_month"]).reset_index(drop=True)
    grouped["qty_issued"] = grouped["qty_issued"].astype(int)
    grouped["breakdown_events"] = grouped["breakdown_events"].astype(int)
    return grouped


def shift_demand_to_horizon(demand: pd.DataFrame, horizon: str) -> pd.DataFrame:
    """Desplaza la serie de demanda para que termine en el mes indicado.

    Entrada:
        demand: DataFrame de demanda mensual.
        horizon: ultimo mes deseado en formato YYYY-MM.

    Salida:
        DataFrame con los mismos registros y period_month recalculado.

    Funcionalidad:
        El dato crudo termina antes del horizonte que necesita la operacion. En
        lugar de generar meses sinteticos se corre el calendario completo, de
        modo que se conservan todas las observaciones reales y solo cambia la
        etiqueta del periodo.

        Se descarto extender la serie con meses generados. Las variantes
        probadas, tanto usar la media por mes del calendario como remuestrear el
        mismo mes, corrompian la clasificacion de patrones: los meses añadidos
        no son evidencia nueva sino copias de las mismas observaciones, e inflar
        asi la muestra fabrica poder estadistico. El test de estacionalidad
        pasaba de detectar 6 series a detectar 20 sin que la demanda real
        hubiera cambiado.
    """
    last_month = demand["period_month"].max()
    offset = (pd.Period(horizon, freq="M") - pd.Period(last_month, freq="M")).n
    if offset == 0:
        return demand

    shifted = demand.copy()
    periods = pd.PeriodIndex(shifted["period_month"], freq="M") + offset
    shifted["period_month"] = periods.astype(str)
    return shifted.sort_values(["sku_id", "city_id", "period_month"]).reset_index(drop=True)


def build_inventory_current(parts: pd.DataFrame, demand: pd.DataFrame, rng) -> pd.DataFrame:
    """Construye la foto de inventario por pieza y ciudad.

    Entrada:
        parts: maestro de piezas.
        demand: demanda mensual por pieza y ciudad.
        rng: generador aleatorio de numpy, para reproducibilidad.

    Salida:
        DataFrame con una fila por pieza y ciudad: existencias, punto de
        reorden, cantidad de reorden, valor del stock y bandera de reposicion.

    Funcionalidad:
        El dato crudo registra consumo, no existencias, de modo que el stock y
        los puntos de reorden se derivan de la estadistica mensual de demanda.
        El punto de reorden usa un nivel de servicio mayor cuanto mas critica es
        la pieza. Las existencias se sortean como multiplo del punto de reorden
        y no de la media, para que el dataset traiga tanto piezas que requieren
        compra como piezas que no, y el motor de reglas ejercite ambos caminos.
    """
    snapshot = demand["period_month"].max() + "-28"
    criticality = dict(zip(parts["sku_id"], parts["criticality"]))
    unit_costs = dict(zip(parts["sku_id"], parts["unit_cost_usd"]))

    stats = (
        demand.groupby(["sku_id", "city_id"])["qty_issued"]
        .agg(mu="mean", sigma=lambda s: float(s.std(ddof=0)))
        .reset_index()
        .sort_values(["sku_id", "city_id"])
        .reset_index(drop=True)
    )

    rows = []
    for _, record in stats.iterrows():
        sku, city = record["sku_id"], record["city_id"]
        mu, sigma = record["mu"], record["sigma"]
        z = config.Z_BY_CRITICALITY[criticality[sku]]
        reorder_point = math.ceil(mu + z * sigma)
        reorder_qty = max(1, math.ceil(mu))
        coverage = float(rng.uniform(*config.COVERAGE_RANGE))
        on_hand = int(round(reorder_point * coverage))
        unit_cost = unit_costs[sku]
        rows.append({
            "sku_id": sku,
            "city_id": city,
            "warehouse_id": CITY_TO_WAREHOUSE[city],
            "snapshot_date": snapshot,
            "on_hand_qty": on_hand,
            "reorder_point": reorder_point,
            "reorder_qty": reorder_qty,
            "unit_cost_usd": unit_cost,
            "stock_value_usd": round(on_hand * unit_cost, 2),
            "below_reorder": int(on_hand < reorder_point),
        })
    return pd.DataFrame(rows)


def build_suppliers(procurement: pd.DataFrame) -> pd.DataFrame:
    """Construye el catalogo de proveedores con sus tiempos de entrega.

    Entrada:
        procurement: DataFrame de ordenes devuelto por load_procurement.

    Salida:
        DataFrame con supplier_id, nombre, ciudad donde opera, contacto y las
        cuatro metricas de lead time: promedio, minimo, maximo y desviacion.

    Funcionalidad:
        Calcula los tiempos de entrega a partir de ordenes realmente entregadas,
        descartando las que no tienen ambas fechas. Reparte los proveedores
        entre las ciudades de la operacion de forma ciclica.
    """
    df = procurement.dropna(subset=["Order_Date", "Delivery_Date"]).copy()
    df["lead_days"] = (df["Delivery_Date"] - df["Order_Date"]).dt.days
    df = df[df["lead_days"] > 0]

    rows = []
    for index, name in enumerate(sorted(procurement["Supplier"].unique())):
        lead = df.loc[df["Supplier"] == name, "lead_days"]
        slug = name.lower().replace("_", "-")
        rows.append({
            "supplier_id": f"SUP-{index + 1:02d}",
            "name": name,
            "city_id": config.CITY_IDS[index % len(config.CITY_IDS)],
            "active": True,
            "contact_email": f"ordenes@{slug}.com",
            "lead_time_avg_days": round(float(lead.mean()), 1),
            "lead_time_min_days": int(lead.min()),
            "lead_time_max_days": int(lead.max()),
            "lead_time_std_days": round(float(lead.std(ddof=0)), 2),
        })
    return pd.DataFrame(rows)


def build_supplier_offers(parts: pd.DataFrame, demand: pd.DataFrame,
                          suppliers: pd.DataFrame, rng) -> pd.DataFrame:
    """Construye el catalogo de ofertas de proveedor por pieza.

    Entrada:
        parts: maestro de piezas.
        demand: demanda mensual, para dimensionar la capacidad.
        suppliers: catalogo de proveedores.
        rng: generador aleatorio de numpy, para reproducibilidad.

    Salida:
        DataFrame con offer_id, supplier_id, sku_id, precio unitario, cantidad
        minima de orden, capacidad mensual y costo de flete.

    Funcionalidad:
        Asigna dos o tres proveedores a cada pieza para que el optimizador tenga
        alternativas reales de compra. El precio parte del costo con un margen
        propio de cada proveedor. La cantidad minima es alta en piezas baratas y
        baja en piezas caras, y la capacidad mensual se dimensiona por encima del
        pico de demanda observado para no volver infactible el modelo.
    """
    supplier_ids = list(suppliers["supplier_id"])
    markup = {sid: round(1.05 + 0.03 * i, 4) for i, sid in enumerate(supplier_ids)}
    freight = {sid: round(10 + 5 * i, 2) for i, sid in enumerate(supplier_ids)}
    unit_costs = dict(zip(parts["sku_id"], parts["unit_cost_usd"]))
    max_demand = demand.groupby("sku_id")["qty_issued"].max().to_dict()

    rows = []
    for sku in sorted(parts["sku_id"]):
        n_offers = int(rng.integers(2, 4))
        chosen = rng.choice(supplier_ids, size=n_offers, replace=False)
        unit_cost = unit_costs[sku]
        moq = min(100, max(1, int(round(200 / max(unit_cost, 1)))))
        capacity = max(int(max_demand.get(sku, 0)), moq) * 3
        for supplier_id in chosen:
            rows.append({
                "offer_id": f"{supplier_id}_{sku}",
                "supplier_id": supplier_id,
                "sku_id": sku,
                "unit_price_usd": round(unit_cost * markup[supplier_id], 2),
                "moq": moq,
                "capacity_per_month": capacity,
                "freight_cost_usd": freight[supplier_id],
                "currency": "USD",
            })
    return pd.DataFrame(rows).sort_values(["sku_id", "supplier_id"]).reset_index(drop=True)
