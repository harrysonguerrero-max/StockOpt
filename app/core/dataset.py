"""Construccion de las tablas del dataset MVP de inventario.

Funcionalidad:
    Transforma los CSV crudos de app/data en las cuatro entradas de datos del
    proyecto: maestro de piezas, inventario actual, demanda historica y
    proveedores con su catalogo de ofertas. Cada funcion es pura: recibe
    DataFrames y devuelve un DataFrame, sin escribir en disco ni alterar las
    fuentes.

    Las constantes de construccion viven al inicio de este archivo por ser su
    unico duenno. El nivel de servicio por criticidad y la politica de minimos
    se importan de core.inventory, que es donde se definen una sola vez.
"""

import math
from pathlib import Path

import pandas as pd

from app.core.cleaning import clean_procurement, clean_spine
from app.core.inventory import Z_BY_CRITICALITY, inventory_minimum, planning_lead_time

SEED = 20260803
INR_TO_USD = 1 / 83

RAW_DIR = Path(__file__).resolve().parents[1] / "data"
OUT_DIR = RAW_DIR / "mvp"

CITY_MAP = {
    "PUN-01": {
        "city_id": "NAVA",
        "city_name": "Nava, Coahuila",
        "country": "Mexico",
        "warehouse_id": "NAVA-01",
    },
    "DHR-03": {
        "city_id": "NAVA",
        "city_name": "Nava, Coahuila",
        "country": "Mexico",
        "warehouse_id": "NAVA-01",
    },
    "CHN-02": {
        "city_id": "OBRE",
        "city_name": "Ciudad Obregon, Sonora",
        "country": "Mexico",
        "warehouse_id": "OBRE-01",
    },
}

CITY_IDS = ["NAVA", "OBRE"]

SHELF_LIFE_BY_FAMILY = {
    "Lubrication": 180,
    "Filter": 365,
    "Seal & Gasket": 730,
    "Drive Belt": 1095,
    "Bearing": 1825,
    "Coupling": 2555,
    "Electrical": 1825,
    "Sensor": 1825,
    "Fastener": 3650,
}

COVERAGE_RANGE = (0.35, 1.75)

DEMAND_HORIZON = "2026-01"

MIN_DAYS_PER_MONTH = 20

SYNTHETIC_EXTRA_YEARS = 3

REMOTE_FREIGHT_MULTIPLIER = 2.5
REMOTE_LEAD_TIME_EXTRA_DAYS = 4

CITY_TO_WAREHOUSE = {v["city_id"]: v["warehouse_id"] for v in CITY_MAP.values()}


def load_spine(raw_dir: Path) -> pd.DataFrame:
    """Carga el historico de consumo de repuestos por planta.

    Entrada:
        raw_dir: carpeta que contiene los CSV crudos.

    Salida:
        DataFrame con el consumo diario por planta y pieza, con
        transaction_date convertida a fecha y breakdown_flag como entero.

    Funcionalidad:
        Aplica las reglas de limpieza antes de devolver los datos: normaliza
        tipos, elimina duplicados por llave y descarta los meses con cobertura
        insuficiente.
    """
    raw = pd.read_csv(raw_dir / "synthetic_industrial_machine_data.csv")
    clean, _ = clean_spine(raw)
    return clean


def load_procurement(raw_dir: Path) -> pd.DataFrame:
    """Carga el historico de ordenes de compra.

    Entrada:
        raw_dir: carpeta que contiene los CSV crudos.

    Salida:
        DataFrame de ordenes con Order_Date y Delivery_Date convertidas a fecha.

    Funcionalidad:
        Aplica las reglas de limpieza antes de devolver los datos: descarta
        ordenes sin fechas, conserva solo las realmente entregadas y valida el
        plazo. Devuelve la columna lead_days ya calculada.
    """
    raw = pd.read_csv(raw_dir / "Procurement KPI Analysis Dataset.csv")
    clean, _ = clean_procurement(raw)
    return clean


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
    for entry in CITY_MAP.values():
        seen.setdefault(entry["city_id"], entry)
    rows = [seen[city_id] for city_id in CITY_IDS]
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
    return pd.DataFrame(
        {
            "sku_id": parts["part_no"],
            "description": parts["part_description"],
            "category": parts["part_family"],
            "criticality": parts["criticality"],
            "uom": parts["uom"],
            "unit_cost_usd": (parts["unit_cost_inr"] * INR_TO_USD).round(2),
            "currency": "USD",
            "shelf_life_days": parts["part_family"].map(SHELF_LIFE_BY_FAMILY).astype(int),
        }
    )


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
    df["city_id"] = df["plant_code"].map(lambda p: CITY_MAP[p]["city_id"])
    df["period_month"] = df["transaction_date"].dt.strftime("%Y-%m")

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


def build_inventory_current(
    parts: pd.DataFrame, demand: pd.DataFrame, suppliers: pd.DataFrame, rng
) -> pd.DataFrame:
    """Construye la foto de inventario por pieza y ciudad.

    Entrada:
        parts: maestro de piezas.
        demand: demanda mensual por pieza y ciudad.
        suppliers: catalogo de proveedores, del que sale el plazo de entrega.
        rng: generador aleatorio de numpy, para reproducibilidad.

    Salida:
        DataFrame con una fila por pieza y ciudad: existencias, punto de
        reorden, cantidad de reorden, valor de las existencias y bandera de
        reposicion.

    Funcionalidad:
        El dato crudo registra consumo, no existencias, de modo que el nivel y
        los puntos de reorden se derivan de la estadistica mensual de demanda.

        El punto de reorden usa la misma politica que la proyeccion de demanda,
        es decir cubrir el consumo durante el plazo de entrega mas el colchon de
        seguridad. Antes se cubria un mes completo de demanda, lo que producia
        un umbral casi el doble de alto y hacia que ambas etapas dieran
        respuestas opuestas sobre que piezas reponer.

        Las existencias se sortean como multiplo del punto de reorden, para que
        el dataset traiga tanto piezas que requieren compra como piezas que no y
        el motor de reglas ejercite ambos caminos.
    """
    snapshot = demand["period_month"].max() + "-28"
    criticality = dict(zip(parts["sku_id"], parts["criticality"], strict=False))
    unit_costs = dict(zip(parts["sku_id"], parts["unit_cost_usd"], strict=False))
    lead_time, lead_time_std = planning_lead_time(suppliers)

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
        z = Z_BY_CRITICALITY[criticality[sku]]
        _, _, reorder_point = inventory_minimum(mu, sigma, lead_time, lead_time_std, z)
        reorder_point = max(1, reorder_point)
        reorder_qty = max(1, math.ceil(mu))
        coverage = float(rng.uniform(*COVERAGE_RANGE))
        on_hand = round(reorder_point * coverage)
        unit_cost = unit_costs[sku]
        rows.append(
            {
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
            }
        )
    return pd.DataFrame(rows)


def build_suppliers(procurement: pd.DataFrame) -> pd.DataFrame:
    """Construye el catalogo de proveedores con sus tiempos de entrega.

    Entrada:
        procurement: DataFrame de ordenes devuelto por load_procurement.

    Salida:
        DataFrame con supplier_id, nombre, ciudad sede, contacto, flete base y
        las cuatro metricas de lead time: promedio, minimo, maximo y desviacion.

    Funcionalidad:
        Calcula los tiempos de entrega a partir de ordenes realmente entregadas,
        descartando las que no tienen ambas fechas. Reparte los proveedores
        entre las ciudades de la operacion de forma ciclica.
    """
    df = procurement
    rows = []
    for index, name in enumerate(sorted(procurement["Supplier"].unique())):
        lead = df.loc[df["Supplier"] == name, "lead_days"]
        slug = name.lower().replace("_", "-")
        rows.append(
            {
                "supplier_id": f"SUP-{index + 1:02d}",
                "name": name,
                "city_id": CITY_IDS[index % len(CITY_IDS)],
                "active": True,
                "contact_email": f"ordenes@{slug}.com",
                "base_freight_usd": round(10 + 5 * index, 2),
                "lead_time_avg_days": round(float(lead.mean()), 1),
                "lead_time_min_days": int(lead.min()),
                "lead_time_max_days": int(lead.max()),
                "lead_time_std_days": round(float(lead.std(ddof=0)), 2),
            }
        )
    return pd.DataFrame(rows)


def build_supplier_coverage(suppliers: pd.DataFrame) -> pd.DataFrame:
    """Construye la cobertura geografica de cada proveedor.

    Entrada:
        suppliers: catalogo de proveedores con su ciudad sede.

    Salida:
        DataFrame con supplier_id, city_id, is_home, freight_cost_usd y
        lead_time_extra_days: una fila por cada ciudad que el proveedor atiende.

    Funcionalidad:
        Un proveedor no atiende solo su ciudad sede. Puede despachar a las demas
        pagando mas flete y tardando algunos dias mas.

        Esta tabla existe para resolver un bloqueante detectado antes de la
        optimizacion. Al asignar una sola ciudad por proveedor, 7 de las 40
        combinaciones pieza-ciudad se quedaban sin ninguna opcion de compra y el
        modelo era infactible para ellas. Modelar la cobertura como muchos a
        muchos convierte esa restriccion rigida en un compromiso economico, que
        es lo que el optimizador sabe resolver: comprar fuera de plaza es
        posible, simplemente cuesta mas y tarda mas.
    """
    rows = []
    for _, supplier in suppliers.iterrows():
        for city_id in CITY_IDS:
            is_home = city_id == supplier["city_id"]
            rows.append(
                {
                    "supplier_id": supplier["supplier_id"],
                    "city_id": city_id,
                    "is_home": int(is_home),
                    "freight_cost_usd": round(
                        supplier["base_freight_usd"]
                        if is_home
                        else supplier["base_freight_usd"] * REMOTE_FREIGHT_MULTIPLIER,
                        2,
                    ),
                    "lead_time_extra_days": 0 if is_home else REMOTE_LEAD_TIME_EXTRA_DAYS,
                }
            )
    return pd.DataFrame(rows)


def build_supplier_offers(
    parts: pd.DataFrame, demand: pd.DataFrame, suppliers: pd.DataFrame, rng
) -> pd.DataFrame:
    """Construye el catalogo de ofertas de proveedor por pieza.

    Entrada:
        parts: maestro de piezas.
        demand: demanda mensual, para dimensionar la capacidad.
        suppliers: catalogo de proveedores.
        rng: generador aleatorio de numpy, para reproducibilidad.

    Salida:
        DataFrame con offer_id, supplier_id, sku_id, precio unitario, cantidad
        minima de orden y capacidad mensual. El flete no vive aqui porque depende
        de la ciudad de destino: esta en supplier_coverage.

    Funcionalidad:
        Asigna dos o tres proveedores a cada pieza para que el optimizador tenga
        alternativas reales de compra. El precio parte del costo con un margen
        propio de cada proveedor. La cantidad minima es alta en piezas baratas y
        baja en piezas caras, y la capacidad mensual se dimensiona por encima del
        pico de demanda observado para no volver infactible el modelo.
    """
    supplier_ids = list(suppliers["supplier_id"])
    markup = {sid: round(1.05 + 0.03 * i, 4) for i, sid in enumerate(supplier_ids)}
    unit_costs = dict(zip(parts["sku_id"], parts["unit_cost_usd"], strict=False))
    max_demand = demand.groupby("sku_id")["qty_issued"].max().to_dict()

    rows = []
    for sku in sorted(parts["sku_id"]):
        n_offers = int(rng.integers(2, 4))
        chosen = rng.choice(supplier_ids, size=n_offers, replace=False)
        unit_cost = unit_costs[sku]
        moq = min(100, max(1, round(200 / max(unit_cost, 1))))
        capacity = max(int(max_demand.get(sku, 0)), moq) * 3
        rows.extend(
            {
                "offer_id": f"{supplier_id}_{sku}",
                "supplier_id": supplier_id,
                "sku_id": sku,
                "unit_price_usd": round(unit_cost * markup[supplier_id], 2),
                "moq": moq,
                "capacity_per_month": capacity,
                "currency": "USD",
            }
            for supplier_id in chosen
        )
    return pd.DataFrame(rows).sort_values(["sku_id", "supplier_id"]).reset_index(drop=True)
