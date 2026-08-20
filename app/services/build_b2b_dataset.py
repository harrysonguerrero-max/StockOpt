"""Construccion del dataset MVP desde el libro de pedidos B2B-Parts-Rec.

Funcionalidad:
    Sustituye la fuente del proyecto. Publica exactamente las mismas siete
    tablas que el constructor anterior y con las mismas columnas, de modo que
    todo lo que viene despues —patrones, proyeccion, optimizacion, interfaz—
    siga funcionando sin tocar una linea.

    Que cambia y por que importa. La fuente anterior era consumo de una planta
    con veinte piezas que se movian todos los meses: perfil de insumo de
    produccion, no de refaccion. La nueva es el libro de pedidos real de
    repuestos industriales de empresas de alimentos y bebidas, con miles de
    referencias y una cola larga de piezas que se piden dos veces al ano. Es la
    diferencia entre un dato que valida la arquitectura de decision y un dato
    que ademas ejercita el problema.

    Que se conserva de la fuente y que se construye esta declarado pieza por
    pieza en `app.core.catalog`. En resumen: el precio, las maquinas y el mes de
    cada pedido son observados; la familia y la criticidad se derivan de ellos
    con una regla declarada; la cantidad y la descripcion son sinteticas porque
    la fuente no las trae.

    Las dos plantas salen de partir un unico cliente por sus lineas de
    produccion, no de tomar dos clientes distintos. Dos clientes cualesquiera
    comparten menos de la mitad del catalogo, asi que darian dos catalogos
    disjuntos en vez de dos plantas de la misma empresa, y se perderia la
    comparacion entre Nava y Obregon para la misma pieza, que es justo lo que la
    interfaz muestra.

    Uso: python -m app.services.build_b2b_dataset
"""

import numpy as np
import pandas as pd

from app.core.catalog import (
    SEED,
    SHELF_LIFE_BY_FAMILY,
    assign_families,
    build_description,
    derive_criticality,
    sku_from_item,
    synthesize_quantities,
)
from app.core.dataset import (
    CITY_IDS,
    OUT_DIR,
    RAW_DIR,
    build_cities,
    build_inventory_current,
    build_supplier_coverage,
)
from app.services.dictionary import write_data_dictionary

SOURCE_TEMPLATE = "{year}_full_anonymus_v2_final.csv"

SOURCE_COLUMNS = ["CUSTOMER_ID", "REQUEST_DATE", "ITEM_ID", "LINE_ID", "MACHINE_ID", "PRICE_EXACT"]

CUSTOMER_ID = "7478E086CC"

MIN_EVENTS_PER_SKU = 8

MIN_EVENTS_PER_SERIES = 3

MIN_UNIT_COST_USD = 0.5

SUPPLY_TIERS = [
    (150.0, ["SUP-LOC-01", "SUP-LOC-02", "SUP-NAT-01"]),
    (1500.0, ["SUP-NAT-01", "SUP-NAT-02", "SUP-LOC-01"]),
    (float("inf"), ["SUP-OEM-01", "SUP-OEM-02", "SUP-NAT-01"]),
]

TIER_MARKUP = {"SUP-LOC": 1.06, "SUP-NAT": 1.12, "SUP-OEM": 1.22}

SUPPLIERS = [
    ("SUP-OEM-01", "Rheinpack Systems", "NAVA", 180.0, 62.0, 34, 118, 21.0),
    ("SUP-OEM-02", "Nordfill Technik", "OBRE", 210.0, 71.0, 40, 132, 25.0),
    ("SUP-NAT-01", "Industrial Bajio", "NAVA", 55.0, 16.0, 7, 34, 6.5),
    ("SUP-NAT-02", "Refacciones del Norte", "OBRE", 60.0, 18.0, 8, 38, 7.2),
    ("SUP-LOC-01", "Suministros Coahuila", "NAVA", 22.0, 6.0, 2, 14, 3.1),
    ("SUP-LOC-02", "Servicios Yaqui", "OBRE", 26.0, 7.0, 3, 16, 3.6),
]


def available_years(raw_dir=RAW_DIR) -> list:
    """Determina el tramo contiguo de anos descargados de la fuente.

    Entrada:
        raw_dir: carpeta con los archivos crudos.

    Salida:
        Lista de anos consecutivos disponibles, empezando por el mas antiguo.

    Funcionalidad:
        Corta en el primer hueco en lugar de tomar todo lo que exista. Un ano
        ausente en medio no produce una serie mas corta sino doce meses de ceros
        que nadie observo, y esos ceros falsos se leerian como demanda que se
        detuvo: contaminarian la clasificacion de patrones y el calculo del
        inventario minimo de todas las series a la vez.
    """
    present = sorted(
        year
        for year in range(2020, 2040)
        if (raw_dir / SOURCE_TEMPLATE.format(year=year)).exists()
    )
    if not present:
        return []

    span = [present[0]]
    for year in present[1:]:
        if year != span[-1] + 1:
            break
        span.append(year)
    return span


def load_orders(years: list, raw_dir=RAW_DIR) -> pd.DataFrame:
    """Lee las lineas de pedido del cliente elegido.

    Entrada:
        years: anos a cargar.
        raw_dir: carpeta con los archivos crudos.

    Salida:
        DataFrame con una fila por linea de pedido del cliente.

    Funcionalidad:
        Lee solo las seis columnas que hacen falta. Las cuatro columnas de
        descripcion de la fuente son vectores cuantizados de treinta y dos bytes
        que multiplican por diez el tamano del archivo y no aportan nada: sus
        codigos son casi unicos por pieza, asi que no sirven ni para agrupar.
    """
    frames = []
    for year in years:
        path = raw_dir / SOURCE_TEMPLATE.format(year=year)
        part = pd.read_csv(path, sep=";", usecols=SOURCE_COLUMNS, parse_dates=["REQUEST_DATE"])
        frames.append(part[part.CUSTOMER_ID == CUSTOMER_ID])
    return pd.concat(frames, ignore_index=True)


def split_into_plants(orders: pd.DataFrame) -> pd.DataFrame:
    """Reparte las lineas de pedido entre las dos plantas del alcance.

    Entrada:
        orders: lineas de pedido del cliente.

    Salida:
        El mismo DataFrame con las columnas sku_id, city_id y machine_id.

    Funcionalidad:
        La linea de produccion mas grande concentra la mitad de la actividad, asi
        que hace de complejo mayor y se asigna a Nava; el resto va a Ciudad
        Obregon. Es el mismo reparto de tamanos que ya describia el proyecto y
        deja mas de mil referencias presentes en ambas plantas, que es lo que
        permite comparar la misma pieza en las dos.
    """
    biggest = orders.groupby("LINE_ID").size().idxmax()
    return orders.assign(
        sku_id=orders.ITEM_ID.map(sku_from_item),
        city_id=np.where(orders.LINE_ID == biggest, CITY_IDS[0], CITY_IDS[1]),
        machine_id=orders.MACHINE_ID,
        period_month=orders.REQUEST_DATE.dt.strftime("%Y-%m"),
    )


def select_catalogue(lines: pd.DataFrame) -> pd.DataFrame:
    """Recorta el catalogo a las referencias con actividad suficiente.

    Entrada:
        lines: lineas de pedido ya asignadas a planta.

    Salida:
        Las lineas de las piezas que superan el minimo de eventos.

    Funcionalidad:
        Dos tercios de las referencias de la fuente se piden una sola vez en
        varios anos. Son reales y son la cola del catalogo, pero con un solo
        evento no hay nada que proyectar: el clasificador las marcaria todas como
        insuficientes y el resto del sistema no tendria sobre que decidir.

        El corte se aplica dos veces. Primero sobre la pieza, para fijar el
        tamano del catalogo; despues sobre cada combinacion de pieza y planta,
        porque una referencia activa en un complejo puede aparecer una vez
        suelta en el otro y esa serie tampoco es proyectable.

        Antes de eso se descartan las referencias sin precio. La fuente trae
        lineas con importe cero —muestras, garantias o cargos ya facturados
        aparte— y sobre ellas el sistema no puede decidir nada: el costo de
        mantener sale del valor de la pieza, asi que con valor cero la cantidad
        economica se dispara y la comparacion entre ofertas pierde sentido.
    """
    priced = lines.groupby("sku_id").PRICE_EXACT.median()
    lines = lines[lines.sku_id.isin(priced[priced >= MIN_UNIT_COST_USD].index)]

    by_sku = lines.groupby("sku_id").size()
    keep = by_sku[by_sku >= MIN_EVENTS_PER_SKU].index
    lines = lines[lines.sku_id.isin(keep)]

    by_series = lines.groupby(["sku_id", "city_id"]).size()
    pairs = set(by_series[by_series >= MIN_EVENTS_PER_SERIES].index)
    mask = [(sku, city) in pairs for sku, city in zip(lines.sku_id, lines.city_id, strict=False)]
    return lines[mask].reset_index(drop=True)


def build_parts_master(lines: pd.DataFrame) -> pd.DataFrame:
    """Compone el maestro de piezas del catalogo seleccionado.

    Entrada:
        lines: lineas de pedido del catalogo ya recortado.

    Salida:
        DataFrame con las mismas columnas que el maestro anterior.

    Funcionalidad:
        El costo unitario es el precio mediano observado, sin tocar. La familia
        sale del rango de precio contra la composicion de catalogo declarada. La
        criticidad sale del numero de maquinas distintas a las que sirve la
        pieza. La descripcion y la vida util son sinteticas.
    """
    items = (
        lines.groupby("sku_id")
        .agg(
            unit_cost_usd=("PRICE_EXACT", "median"),
            machine_count=("machine_id", "nunique"),
            events=("sku_id", "size"),
        )
        .reset_index()
    )

    items["category"] = assign_families(items)
    items["criticality"] = derive_criticality(items)

    return pd.DataFrame(
        {
            "sku_id": items.sku_id,
            "description": [
                build_description(sku, family)
                for sku, family in zip(items.sku_id, items.category, strict=False)
            ],
            "category": items.category,
            "criticality": items.criticality,
            "uom": "EA",
            "unit_cost_usd": items.unit_cost_usd.round(2),
            "currency": "USD",
            "shelf_life_days": items.category.map(SHELF_LIFE_BY_FAMILY).astype(int),
        }
    ).sort_values("sku_id").reset_index(drop=True)


def build_demand_history(lines: pd.DataFrame, rng) -> pd.DataFrame:
    """Agrega las lineas de pedido a demanda mensual por pieza y planta.

    Entrada:
        lines: lineas de pedido del catalogo seleccionado.
        rng: generador aleatorio ya sembrado.

    Salida:
        DataFrame denso con una fila por pieza, planta y mes del periodo.

    Funcionalidad:
        La rejilla es densa a proposito: los meses sin pedido tienen que
        aparecer con cero y no ausentarse. En un catalogo de refacciones esos
        ceros son la mitad del dato —tres de cada cuatro meses no se mueve
        nada— y son justo lo que decide en que patron cae la serie y cuanta
        holgura necesita su inventario minimo.

        `issue_events` cuenta las lineas de pedido del mes y es dato observado:
        es la senal de intermitencia. `qty_issued` es sintetica, porque la
        fuente registra que se pidio una pieza pero no cuantas.

        `is_synthetic` queda en cero en todas las filas. Es el cambio de fondo
        respecto del dataset anterior, donde la mitad de la historia se habia
        simulado hacia atras para alcanzar los meses que exige detectar
        estacionalidad. Aqui los meses son todos observados.
    """
    lines = lines.assign(qty=synthesize_quantities(lines.PRICE_EXACT.to_numpy(), rng))

    observed = (
        lines.groupby(["sku_id", "city_id", "period_month"])
        .agg(qty_issued=("qty", "sum"), issue_events=("qty", "size"))
        .reset_index()
    )

    months = sorted(lines.period_month.unique())
    series = observed[["sku_id", "city_id"]].drop_duplicates()
    grid = series.merge(pd.DataFrame({"period_month": months}), how="cross")

    dense = grid.merge(observed, on=["sku_id", "city_id", "period_month"], how="left")
    dense["qty_issued"] = dense.qty_issued.fillna(0).astype(int)
    dense["issue_events"] = dense.issue_events.fillna(0).astype(int)
    dense["breakdown_events"] = 0
    dense["is_synthetic"] = 0

    return dense.sort_values(["sku_id", "city_id", "period_month"]).reset_index(drop=True)


def build_suppliers() -> pd.DataFrame:
    """Construye el catalogo de proveedores con plazos realistas.

    Entrada:
        Ninguna.

    Salida:
        DataFrame con las mismas columnas que el catalogo anterior.

    Funcionalidad:
        Tres niveles de suministro, que es como compra de verdad una planta de
        proceso. El fabricante del equipo entrega en dos o tres meses desde
        Europa y cobra un flete alto; el distribuidor nacional entrega en dos o
        tres semanas; el proveedor local entrega en dias pero no tiene todo.

        El plazo es el parametro mas influyente de la politica de inventario y
        el anterior lo aplanaba: diez dias para todos. Con plazos de sesenta o
        setenta dias en el material de fabricante, la demanda durante el plazo y
        su varianza crecen mucho, el inventario minimo sube con ellas, y la
        restriccion de continuidad de produccion empieza a apretar de verdad en
        lugar de quedar como una funcionalidad que nunca se dispara.
    """
    return pd.DataFrame(
        [
            {
                "supplier_id": supplier_id,
                "name": name,
                "city_id": city_id,
                "active": True,
                "contact_email": f"ordenes@{name.lower().replace(' ', '-')}.com",
                "base_freight_usd": freight,
                "lead_time_avg_days": average,
                "lead_time_min_days": minimum,
                "lead_time_max_days": maximum,
                "lead_time_std_days": deviation,
            }
            for supplier_id, name, city_id, freight, average, minimum, maximum, deviation
            in SUPPLIERS
        ]
    )


def build_offers(parts: pd.DataFrame, demand: pd.DataFrame, rng) -> pd.DataFrame:
    """Asigna proveedores a cada pieza segun su gama de precio.

    Entrada:
        parts: maestro de piezas.
        demand: demanda mensual, para dimensionar la capacidad.
        rng: generador aleatorio ya sembrado.

    Salida:
        DataFrame de ofertas con las mismas columnas que el catalogo anterior.

    Funcionalidad:
        No se sortea el proveedor al azar entre los seis, que es lo que hacia el
        constructor anterior y con este catalogo produce disparates: una junta de
        dos dolares podia quedar surtida solo por el fabricante europeo, con
        ciento ochenta de flete y dos meses de plazo. Nadie compra asi, y el
        efecto sobre el modelo no es cosmetico: el flete entra entero en el costo
        de la orden, de modo que un flete mal asignado vuelve antieconomica una
        reposicion que en la realidad es trivial.

        El reparto sigue como compra una planta de proceso. El consumible barato
        se pide al distribuidor local, que entrega en dias y cobra poco flete. La
        pieza de gama media va al distribuidor nacional. El material caro solo lo
        tiene el fabricante del equipo, que cobra mas caro, cobra mas flete y
        tarda meses, y ahi no hay alternativa: es justo el caso donde el
        inventario minimo se dispara y la continuidad de produccion se vuelve
        cara de garantizar.

        El margen acompana al nivel: el fabricante cobra mas por la misma pieza
        que un distribuidor, que es lo que hace que el optimizador prefiera al
        local siempre que este disponible.
    """
    unit_costs = dict(zip(parts["sku_id"], parts["unit_cost_usd"], strict=False))
    max_demand = demand.groupby("sku_id")["qty_issued"].max().to_dict()

    rows = []
    for sku in sorted(parts["sku_id"]):
        unit_cost = unit_costs[sku]
        pool = next(members for ceiling, members in SUPPLY_TIERS if unit_cost < ceiling)
        chosen = pool[: int(rng.integers(2, len(pool) + 1))]

        moq = min(100, max(1, round(200 / max(unit_cost, 1))))
        capacity = max(int(max_demand.get(sku, 0)), moq) * 3
        rows.extend(
            {
                "offer_id": f"{supplier_id}_{sku}",
                "supplier_id": supplier_id,
                "sku_id": sku,
                "unit_price_usd": round(unit_cost * TIER_MARKUP[supplier_id[:7]], 2),
                "moq": moq,
                "capacity_per_month": capacity,
                "currency": "USD",
            }
            for supplier_id in chosen
        )
    return pd.DataFrame(rows).sort_values(["sku_id", "supplier_id"]).reset_index(drop=True)


def main() -> None:
    """Genera y publica el dataset MVP desde la fuente B2B.

    Entrada:
        Ninguna. Requiere los archivos anuales en la carpeta de datos crudos.

    Salida:
        Ninguna. Escribe las siete tablas y el diccionario de datos.

    Funcionalidad:
        Aborta indicando que falta si no encuentra la fuente, y al terminar
        resume el tamano del catalogo, la intermitencia conseguida y el reparto
        de criticidad, que son las tres cifras con las que se juzga si el
        dataset sirve.
    """
    years = available_years()
    if not years:
        raise SystemExit(
            f"No hay archivos {SOURCE_TEMPLATE.format(year='YYYY')} en {RAW_DIR}"
        )

    rng = np.random.default_rng(SEED)
    orders = load_orders(years)
    lines = select_catalogue(split_into_plants(orders))

    parts = build_parts_master(lines)
    demand = build_demand_history(lines, rng)
    cities = build_cities()
    suppliers = build_suppliers()
    coverage = build_supplier_coverage(suppliers)
    offers = build_offers(parts, demand, rng)
    inventory = build_inventory_current(parts, demand, suppliers, rng)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tables = {
        "cities.csv": cities,
        "parts_master.csv": parts,
        "inventory_current.csv": inventory,
        "demand_history.csv": demand,
        "suppliers.csv": suppliers,
        "supplier_offers.csv": offers,
        "supplier_coverage.csv": coverage,
    }
    for name, frame in tables.items():
        frame.to_csv(OUT_DIR / name, index=False)
    write_data_dictionary(OUT_DIR)

    months = sorted(demand.period_month.unique())
    series = demand.groupby(["sku_id", "city_id"]).ngroups
    zero_share = (demand.qty_issued == 0).mean()

    print(f"Dataset B2B generado en {OUT_DIR}")
    print(f"  anos usados      : {years[0]}-{years[-1]}  ({len(months)} meses, 0 % sintetico)")
    print(f"  cliente          : {CUSTOMER_ID}")
    print(f"  piezas           : {len(parts):,}")
    print(f"  series           : {series:,}   ({len(demand):,} filas de historia)")
    print(f"  meses en cero    : {zero_share:.0%}")
    print()
    print("  criticidad:")
    for level, count in parts.criticality.value_counts().sort_index().items():
        print(f"    {level}: {count:>4}  ({count / len(parts):.0%})")
    print()
    print("  familias:")
    for family, count in parts.category.value_counts().items():
        cost = parts[parts.category == family].unit_cost_usd.median()
        print(f"    {family:<16} {count:>4} piezas   costo mediano {cost:>10,.2f} USD")
    print()
    annual = float(
        (demand.groupby("sku_id").qty_issued.sum() / (len(months) / 12))
        .mul(parts.set_index("sku_id").unit_cost_usd)
        .sum()
    )
    print(f"  consumo anual proyectado: {annual:,.0f} USD/ano")
    print(f"  valor del inventario    : {inventory.stock_value_usd.sum():,.0f} USD")


if __name__ == "__main__":
    main()
