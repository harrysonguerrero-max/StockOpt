"""Validacion del dataset MVP antes de publicarlo.

Funcionalidad:
    Aplica los controles de calidad exigidos por la etapa de ingesta: integridad
    referencial entre tablas, rangos operativos, ausencia de nulos, duplicados de
    llave y reglas de negocio minimas. Separa lo que impide procesar de lo que
    solo requiere revision humana.
"""


def validate(tables: dict) -> list:
    """Valida el conjunto de tablas generadas.

    Entrada:
        tables: diccionario con las claves cities, parts, inventory, demand,
            suppliers y offers, cada una con su DataFrame.

    Salida:
        Lista de advertencias que no bloquean el proceso. Levanta ValueError con
        el detalle de todos los fallos si encuentra algun error critico.

    Funcionalidad:
        Comprueba que las llaves sku_id, city_id y supplier_id existan en sus
        catalogos, que precios y cantidades esten en rango, que ninguna tabla
        traiga nulos ni llaves repetidas, y que cada pieza tenga al menos dos
        ofertas, ya que sin alternativas el optimizador no tiene nada que
        decidir. Como advertencias reporta las existencias agotadas, las piezas bajo el
        punto de reorden y los proveedores con entregas especialmente lentas.
    """
    errors = []
    warnings = []

    parts = tables["parts"]
    cities = tables["cities"]
    inventory = tables["inventory"]
    demand = tables["demand"]
    suppliers = tables["suppliers"]
    offers = tables["offers"]

    sku_set = set(parts["sku_id"])
    city_set = set(cities["city_id"])
    supplier_set = set(suppliers["supplier_id"])

    def check_subset(values, reference, label):
        """Comprueba que una columna de llaves exista en su catalogo.

        Entrada:
            values: valores de la llave foranea a verificar.
            reference: conjunto de llaves validas del catalogo.
            label: nombre de la columna, para el mensaje de error.

        Salida:
            Ninguna. Añade un error a la lista si encuentra huerfanos.

        Funcionalidad:
            Solo reporta los cinco primeros huerfanos. Si la integridad esta
            rota, el patron se ve con cinco ejemplos y listarlos todos taparia el
            resto de los errores.
        """
        orphans = set(values) - reference
        if orphans:
            errors.append(f"Integridad {label}: huerfanos {sorted(orphans)[:5]}")

    check_subset(inventory["sku_id"], sku_set, "inventory.sku_id")
    check_subset(demand["sku_id"], sku_set, "demand.sku_id")
    check_subset(offers["sku_id"], sku_set, "offers.sku_id")
    check_subset(inventory["city_id"], city_set, "inventory.city_id")
    check_subset(demand["city_id"], city_set, "demand.city_id")
    check_subset(offers["supplier_id"], supplier_set, "offers.supplier_id")

    if (parts["unit_cost_usd"] < 0).any():
        errors.append("parts.unit_cost_usd < 0")
    if (offers["unit_price_usd"] < 0).any():
        errors.append("offers.unit_price_usd < 0")
    if (offers["moq"] < 1).any():
        errors.append("offers.moq < 1")
    if (suppliers["lead_time_min_days"] <= 0).any():
        errors.append("suppliers.lead_time_min_days <= 0")
    if (demand["qty_issued"] < 0).any():
        errors.append("demand.qty_issued < 0")
    if (inventory["on_hand_qty"] < 0).any():
        errors.append("inventory.on_hand_qty < 0")

    counts = offers.groupby("sku_id").size()
    without_options = sku_set - set(counts[counts >= 2].index)
    if without_options:
        errors.append(f"SKUs con menos de 2 ofertas: {sorted(without_options)[:5]}")

    for name, frame in tables.items():
        if frame.isna().any().any():
            errors.append(f"{name}: contiene nulos")

    if not parts["sku_id"].is_unique:
        errors.append("parts.sku_id duplicado")
    if not offers["offer_id"].is_unique:
        errors.append("offers.offer_id duplicado")
    if inventory.duplicated(["sku_id", "city_id"]).any():
        errors.append("inventory: llave (sku_id, city_id) duplicada")
    if demand.duplicated(["sku_id", "city_id", "period_month"]).any():
        errors.append("demand: llave (sku_id, city_id, period_month) duplicada")

    depleted = int((inventory["on_hand_qty"] == 0).sum())
    if depleted:
        warnings.append(f"{depleted} combinaciones sku/ciudad con existencias en cero")

    below = int(inventory["below_reorder"].sum())
    if below:
        warnings.append(f"{below} combinaciones sku/ciudad por debajo del punto de reorden")

    slow = suppliers.loc[suppliers["lead_time_max_days"] > 30, "supplier_id"].tolist()
    if slow:
        warnings.append(f"Proveedores con lead time maximo mayor a 30 dias: {slow}")

    if errors:
        raise ValueError("Errores criticos de validacion:\n- " + "\n- ".join(errors))
    return warnings
