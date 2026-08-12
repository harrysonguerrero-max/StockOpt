"""Consulta de recomendaciones para la interfaz de compras.

Funcionalidad:
    Reune en un solo registro por pieza y ciudad todo lo que el comprador
    necesita ver: la recomendacion del optimizador, el patron de demanda que la
    sustenta, los datos de contacto del proveedor, la justificacion redactada y
    el estado del flujo de aprobacion.

    Los archivos generados se leen una vez y se conservan en memoria, ya que el
    pipeline es por lotes y el dataset no cambia mientras la aplicacion corre.
"""

import pandas as pd

from app.core.dataset import OUT_DIR
from app.core.explanation import build_explanation
from app.core.optimization import (
    DECISION_BUY,
    DECISION_DEFERRED,
    DECISION_HOLD,
    DECISION_REVIEW,
    SCENARIO_BUDGET_USD,
    offer_costs,
)
from app.services.approvals import (
    ALLOWED_TRANSITIONS,
    REJECTION_REASONS,
    STATE_APPROVED,
    STATE_CONFIRMED,
    STATE_CONTACTED,
    STATE_PENDING,
    STATE_REJECTED,
    WORKFLOW_STATES,
    load_states,
)

SOURCES = [
    "purchase_recommendations.csv",
    "demand_patterns.csv",
    "suppliers.csv",
    "cities.csv",
    "supplier_offers.csv",
    "supplier_coverage.csv",
    "demand_history.csv",
    "demand_forecast.csv",
]

_cache = {}


def dataset_is_available() -> bool:
    """Indica si el pipeline ya genero los archivos necesarios.

    Entrada:
        Ninguna.

    Salida:
        True si todas las fuentes existen en la carpeta de salida.

    Funcionalidad:
        Permite que la interfaz muestre un mensaje util en lugar de fallar
        cuando alguien la abre antes de correr el pipeline.
    """
    return all((OUT_DIR / name).exists() for name in SOURCES)


def load_sources(refresh: bool = False) -> dict:
    """Carga los archivos generados por el pipeline.

    Entrada:
        refresh: fuerza releer desde disco descartando lo cacheado.

    Salida:
        Diccionario de DataFrames indexado por nombre de archivo.

    Funcionalidad:
        Mantiene los datos en memoria entre peticiones y solo vuelve a disco
        cuando se pide expresamente, por ejemplo tras regenerar el dataset.
    """
    if refresh or not _cache:
        _cache.clear()
        for name in SOURCES:
            _cache[name] = pd.read_csv(OUT_DIR / name)
    return _cache


def _supply_gauge(record: dict) -> dict:
    """Calcula la lectura del medidor de existencias de una fila.

    Entrada:
        record: recomendacion con existencias, minimo y maximo.

    Salida:
        Diccionario con el porcentaje de llenado, la posicion del minimo y la
        zona en que caen las existencias.

    Funcionalidad:
        Traduce tres numeros a una sola lectura visual. La escala llega hasta el
        maximo permitido, de modo que la posicion del minimo dentro de la barra
        indique de un vistazo si la pieza esta en zona critica, ajustada o
        holgada, que es la tension que decide cada fila.
    """
    ceiling = max(record["inventory_max"], record["on_hand_qty"], 1)
    on_hand_ratio = min(1.0, record["on_hand_qty"] / ceiling)
    minimum_ratio = min(1.0, record["inventory_min"] / ceiling)

    if record["on_hand_qty"] < record["inventory_min"]:
        zone = "critico"
    elif record["on_hand_qty"] < record["inventory_min"] * 1.25:
        zone = "ajustado"
    else:
        zone = "holgado"

    return {
        "fill_pct": round(on_hand_ratio * 100, 1),
        "minimum_pct": round(minimum_ratio * 100, 1),
        "zone": zone,
    }


def build_alternatives(record: dict, offers, coverage, suppliers) -> list:
    """Reune las ofertas que compitieron por una recomendacion.

    Entrada:
        record: recomendacion de una pieza en una ciudad.
        offers: catalogo de ofertas proveedor-pieza.
        coverage: cobertura geografica de los proveedores.
        suppliers: catalogo de proveedores.

    Salida:
        Lista de diccionarios ordenada de menor a mayor costo, cada uno con el
        proveedor, su precio, su lote minimo, su flete, su plazo, lo que
        costaria la compra con el y si fue el elegido.

    Funcionalidad:
        Hace visible por que se descarto cada alternativa. Sin esto la
        recomendacion pide un acto de fe: dice que un proveedor es el mas
        conveniente sin mostrar contra que se comparo.

        La cotizacion la resuelve el dominio, de modo que esta pantalla y el
        resumen del pipeline no puedan discrepar en el costo de una misma oferta.
    """
    return offer_costs(
        record["sku_id"],
        record["city_id"],
        record.get("recommended_qty") or 0,
        offers,
        coverage,
        suppliers,
        chosen_supplier=record.get("supplier_id"),
    )


def build_queue(refresh: bool = False) -> list:
    """Arma la cola de decisiones que muestra la interfaz.

    Entrada:
        refresh: fuerza recargar los archivos del pipeline.

    Salida:
        Lista de diccionarios, uno por pieza y ciudad, listos para serializar.

    Funcionalidad:
        Cruza la recomendacion con el patron de demanda, el contacto del
        proveedor y el estado de aprobacion guardado, y adjunta la explicacion
        deterministica. Ordena poniendo primero lo que exige atencion: las
        compras y las revisiones pendientes por delante de lo que ya no requiere
        accion.

        La redaccion con modelo de lenguaje no ocurre aqui a proposito. Generar
        las cuarenta explicaciones al construir la pantalla suponia cuarenta
        llamadas HTTP en serie por cada carga y por cada aprobacion. La tabla se
        arma con la version deterministica, que es inmediata, y la interfaz pide
        la redaccion del modelo solo para la fila que el comprador abre.
    """
    sources = load_sources(refresh)
    recommendations = sources["purchase_recommendations.csv"]
    patterns = sources["demand_patterns.csv"][["sku_id", "city_id", "pattern"]]
    suppliers = sources["suppliers.csv"]
    cities = sources["cities.csv"]

    merged = recommendations.merge(patterns, on=["sku_id", "city_id"], how="left")
    merged = merged.merge(
        cities[["city_id", "city_name", "warehouse_id"]], on="city_id", how="left"
    )
    merged = merged.merge(
        suppliers[["supplier_id", "contact_email", "lead_time_min_days", "lead_time_max_days"]],
        on="supplier_id",
        how="left",
    )

    states = load_states()
    priority = {
        DECISION_REVIEW: 0,
        DECISION_BUY: 1,
        DECISION_DEFERRED: 2,
        DECISION_HOLD: 3,
    }

    queue = []
    for record in merged.to_dict(orient="records"):
        clean = {key: (None if pd.isna(value) else value) for key, value in record.items()}
        clean["pattern"] = clean.get("pattern") or "Sin clasificar"
        stored = states.get((clean["sku_id"], clean["city_id"]))

        clean["state"] = stored["state"] if stored else STATE_PENDING
        clean["rejection_reason"] = stored["rejection_reason"] if stored else None
        clean["comment"] = stored["comment"] if stored else None
        clean["purchase_order"] = stored["purchase_order"] if stored else None
        clean["updated_at"] = stored["updated_at"] if stored else None
        clean["updated_by"] = stored["updated_by"] if stored else None
        clean["gauge"] = _supply_gauge(clean)
        clean["alternatives"] = build_alternatives(
            clean,
            sources["supplier_offers.csv"],
            sources["supplier_coverage.csv"],
            suppliers,
        )
        clean["explanation"] = {**build_explanation(clean), "source": "plantilla"}
        clean["next_states"] = ALLOWED_TRANSITIONS.get(clean["state"], [])
        clean["sort_key"] = priority.get(clean["decision"], 3)
        queue.append(clean)

    queue.sort(key=lambda item: (item["sort_key"], -item["total_cost_usd"]))
    return queue


def build_summary(queue: list) -> dict:
    """Resume el estado global de la cola.

    Entrada:
        queue: lista de recomendaciones ya construida.

    Salida:
        Diccionario con los totales que encabezan la pantalla.

    Funcionalidad:
        Cuenta las decisiones por tipo, la inversion pendiente de aprobar y
        cuantas filas siguen esperando accion del comprador, que es lo que
        indica cuanto trabajo queda por delante.

        Lo aplazado se reporta aparte de la inversion aprobada. Sumarlo seria
        engañoso, porque no es gasto de esta corrida; restarlo del todo tambien,
        porque es la cifra con la que el comprador defiende una ampliacion del
        presupuesto.
    """
    pending = [item for item in queue if item["state"] == STATE_PENDING]
    to_buy = [item for item in queue if item["decision"] == DECISION_BUY]
    to_review = [item for item in queue if item["decision"] == DECISION_REVIEW]
    deferred = [item for item in queue if item["decision"] == DECISION_DEFERRED]
    approved = [
        item
        for item in queue
        if item["state"] in (STATE_APPROVED, STATE_CONTACTED, STATE_CONFIRMED)
    ]

    return {
        "total": len(queue),
        "to_buy": len(to_buy),
        "to_review": len(to_review),
        "deferred": len(deferred),
        "no_action": len([i for i in queue if i["decision"] == DECISION_HOLD]),
        "pending_decision": len(pending),
        "approved": len(approved),
        "investment_usd": round(sum(item["total_cost_usd"] for item in to_buy), 2),
        "deferred_usd": round(sum(item["total_cost_usd"] for item in deferred), 2),
        "budget_usd": SCENARIO_BUDGET_USD,
        "stockout_avoided_usd": round(sum(item["stockout_cost_usd"] or 0 for item in to_buy), 2),
        "stockout_exposed_usd": round(sum(item["stockout_cost_usd"] or 0 for item in deferred), 2),
        "units": int(sum(item["recommended_qty"] for item in to_buy)),
        "needs_review": len([i for i in queue if i["needs_review"] == 1]),
    }


def filter_options(queue: list) -> dict:
    """Extrae los valores disponibles para los filtros de la interfaz.

    Entrada:
        queue: lista de recomendaciones ya construida.

    Salida:
        Diccionario con las ciudades, decisiones, estados y criticidades
        presentes en los datos.

    Funcionalidad:
        Deja que la interfaz construya los filtros a partir de lo que realmente
        hay, en lugar de mantener listas duplicadas en el frontend.
    """
    cities = sorted({(item["city_id"], item["city_name"]) for item in queue})
    return {
        "cities": [{"id": city_id, "name": name} for city_id, name in cities],
        "decisions": [DECISION_BUY, DECISION_REVIEW, DECISION_DEFERRED, DECISION_HOLD],
        "states": [*WORKFLOW_STATES, STATE_REJECTED],
        "criticalities": sorted({item["criticality"] for item in queue}),
        "rejection_reasons": REJECTION_REASONS,
    }


def demand_series(sku_id: str, city_id: str, months: int = 48,
                  refresh: bool = False) -> dict:
    """Reune el consumo pasado y la proyeccion de una pieza en una ciudad.

    Entrada:
        sku_id: identificador de la pieza.
        city_id: identificador de la ciudad.
        months: cuantos meses de historia devolver, contando desde el mas
            reciente hacia atras.
        refresh: fuerza recargar los archivos del pipeline.

    Salida:
        Diccionario con la serie mensual, la proyeccion con sus cuartiles y los
        parametros de la politica de inventario. None si la pieza no existe.

    Funcionalidad:
        Es lo que permite mostrar la decision como una consecuencia y no como un
        numero suelto: primero lo que la planta consumio de verdad, despues lo
        que se espera que consuma, y con eso el minimo que debe haber en bodega.

        Cada mes viaja con su marca de sintetico, de modo que la interfaz pueda
        distinguir el historico real del que genero el build para dar
        profundidad al entrenamiento. Taparlo seria presentar como observacion
        algo que es un supuesto.
    """
    sources = load_sources(refresh)

    history = sources["demand_history.csv"]
    rows = history[(history["sku_id"] == sku_id) & (history["city_id"] == city_id)]
    if rows.empty:
        return None
    rows = rows.sort_values("period_month").tail(months)

    forecast = sources["demand_forecast.csv"]
    projection = forecast[(forecast["sku_id"] == sku_id)
                          & (forecast["city_id"] == city_id)]
    horizon = projection.iloc[0].to_dict() if not projection.empty else {}

    def number(key, digits=2):
        """Redondea un campo de la proyeccion respetando la ausencia de valor.

        Entrada:
            key: nombre del campo en la fila de proyeccion.
            digits: decimales a conservar.

        Salida:
            El valor redondeado, o None si la proyeccion no lo trae.

        Funcionalidad:
            Distingue el cero del dato ausente. Convertir un nulo en cero haria
            que la interfaz mostrara una proyeccion de cero unidades donde en
            realidad no hay proyeccion, que son cosas distintas.
        """
        value = horizon.get(key)
        return None if value is None or pd.isna(value) else round(float(value), digits)

    return {
        "sku_id": sku_id,
        "city_id": city_id,
        "history": [
            {
                "month": record["period_month"],
                "qty": int(record["qty_issued"]),
                "is_synthetic": int(record["is_synthetic"]),
            }
            for record in rows.to_dict(orient="records")
        ],
        "forecast": {
            "q25": number("forecast_q25"),
            "q50": number("forecast_q50"),
            "q75": number("forecast_q75"),
            "pattern": horizon.get("pattern"),
            "method": horizon.get("method"),
            "source": horizon.get("forecast_source"),
            "confidence": number("confidence_final"),
            "wmape_backtest": number("wmape_backtest", 3),
        },
        "policy": {
            "inventory_min": number("inventory_min", 0),
            "safety_stock": number("safety_stock"),
            "demand_lead_time": number("demand_lead_time"),
            "lead_time_days": number("lead_time_days", 1),
        },
    }


def find_recommendation(sku_id: str, city_id: str, refresh: bool = False) -> dict:
    """Recupera una recomendacion concreta de la cola.

    Entrada:
        sku_id: identificador de la pieza.
        city_id: identificador de la ciudad.
        refresh: fuerza recargar los archivos del pipeline.

    Salida:
        Diccionario de la recomendacion, o None si no existe.

    Funcionalidad:
        Da soporte a la redaccion bajo demanda, que necesita los datos de una
        sola fila y no de la cola completa.
    """
    for item in build_queue(refresh=refresh):
        if item["sku_id"] == sku_id and item["city_id"] == city_id:
            return item
    return None
