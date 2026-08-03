"""Validacion de las tablas del MVP (Etapa 1.1 del spec).

Levanta ValueError ante errores criticos; devuelve la lista de advertencias.
"""


def validate(tables: dict) -> list:
    errors: list = []
    warnings: list = []

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
        orphans = set(values) - reference
        if orphans:
            errors.append(f"Integridad {label}: huerfanos {sorted(orphans)[:5]}")

    # Integridad referencial
    check_subset(inventory["sku_id"], sku_set, "inventory.sku_id")
    check_subset(demand["sku_id"], sku_set, "demand.sku_id")
    check_subset(offers["sku_id"], sku_set, "offers.sku_id")
    check_subset(inventory["city_id"], city_set, "inventory.city_id")
    check_subset(demand["city_id"], city_set, "demand.city_id")
    check_subset(offers["supplier_id"], supplier_set, "offers.supplier_id")

    # Rangos operativos
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

    # Cada pieza necesita alternativas para que el optimizador pueda elegir
    counts = offers.groupby("sku_id").size()
    without_options = sku_set - set(counts[counts >= 2].index)
    if without_options:
        errors.append(f"SKUs con menos de 2 ofertas: {sorted(without_options)[:5]}")

    # Nulos
    for name, df in tables.items():
        if df.isna().any().any():
            errors.append(f"{name}: contiene nulos")

    # Duplicados de llave
    if not parts["sku_id"].is_unique:
        errors.append("parts.sku_id duplicado")
    if not offers["offer_id"].is_unique:
        errors.append("offers.offer_id duplicado")
    if inventory.duplicated(["sku_id", "city_id"]).any():
        errors.append("inventory: llave (sku_id, city_id) duplicada")
    if demand.duplicated(["sku_id", "city_id", "period_month"]).any():
        errors.append("demand: llave (sku_id, city_id, period_month) duplicada")

    # Advertencias: no bloquean, requieren revision humana
    stockouts = int((inventory["on_hand_qty"] == 0).sum())
    if stockouts:
        warnings.append(f"{stockouts} combinaciones sku/ciudad con stock en cero")
    below = int(inventory["below_reorder"].sum())
    if below:
        warnings.append(f"{below} combinaciones sku/ciudad por debajo del punto de reorden")
    high_lead = suppliers.loc[suppliers["lead_time_max_days"] > 30, "supplier_id"].tolist()
    if high_lead:
        warnings.append(f"Proveedores con lead time maximo > 30 dias: {high_lead}")

    if errors:
        raise ValueError("Errores criticos de validacion:\n- " + "\n- ".join(errors))
    return warnings
