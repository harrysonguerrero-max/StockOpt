"""Resumen de lo que hace cada etapa del pipeline.

Funcionalidad:
    Traduce lo que ya produjo cada etapa en una descripcion de que entro, que
    salio y por que, para que la interfaz pueda mostrar el recorrido completo
    del dato en lugar de solo su resultado final.

    No recalcula nada ni vuelve a correr ninguna etapa: lee lo que quedo en las
    tablas y en los informes, y lo agrega. Esa restriccion es deliberada, porque
    un resumen que recalculara podria contradecir a la recomendacion que el
    comprador tiene delante.

    Todas las funciones son puras: reciben DataFrames y diccionarios ya cargados
    y devuelven estructuras serializables. La lectura de disco vive en la capa de
    servicios.
"""

from pathlib import Path

import pandas as pd

from app.core.cleaning import MIN_DAYS_PER_MONTH
from app.core.forecast import QUANTILE_Z
from app.core.inventory import DAYS_PER_MONTH, Z_BY_CRITICALITY, planning_lead_time
from app.core.optimization import (
    BUDGET_OVERRUN_MAX_USD,
    DECISION_BUY,
    DECISION_DEFERRED,
    DECISION_ESCALATE,
    DECISION_HOLD,
    DECISION_REVIEW,
    EOQ_MAX_COVERAGE_MONTHS,
    HOLDING_COST_RATE_ANNUAL,
    MONTHS_PER_YEAR,
    PLANNING_PERIOD_DAYS,
    REASON_ABOVE_MINIMUM,
    REASON_ESCALATE,
    REASON_INFEASIBLE,
    REASON_LOW_CONFIDENCE,
    REASON_NO_SUPPLIER,
    REASON_OVER_BUDGET,
    REASON_SHELF_LIFE_BLOCK,
    SCENARIO_BUDGET_USD,
    SERVICE_FLOOR_BY_CRITICALITY,
    SHELF_LIFE_SAFETY_RATIO,
    STOCKOUT_COST_PER_DAY_USD,
    budget_allocation_summary,
    offer_costs,
)
from app.core.patterns import (
    CV_VOLATILE,
    MIN_PERIODS,
    SEASONAL_PERIOD,
    SEASONAL_PVALUE_MAX,
    SEASONAL_STRENGTH_MIN,
    W_RECENT,
    W_VOLATILITY,
    W_VOLUME,
)
from app.core.profiling import IQR_FACTOR, MAD_SCALE, MAD_THRESHOLD

ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "artifacts" / "pipeline"

SUMMARY_FILE = "pipeline_summary.json"

CHART_FILES = {
    "limpieza": "limpieza_descartes.png",
    "dataset": "dataset_historia.png",
    "patrones": "patrones_mapa.png",
    "decisiones": "optimizacion_decisiones.png",
    "ahorro": "optimizacion_ahorro.png",
}

STAGE_CLEANING = "limpieza"
STAGE_DATASET = "dataset"
STAGE_PATTERNS = "patrones"
STAGE_MODEL = "modelo"
STAGE_OPTIMIZATION = "optimizacion"

STAGE_ORDER = [STAGE_CLEANING, STAGE_DATASET, STAGE_PATTERNS, STAGE_MODEL, STAGE_OPTIMIZATION]

SOURCE_PIPELINE = "pipeline"
SOURCE_TRAINING = "training"

STAGE_CHARTS = {
    STAGE_CLEANING: [(SOURCE_PIPELINE, "limpieza")],
    STAGE_DATASET: [(SOURCE_PIPELINE, "dataset")],
    STAGE_PATTERNS: [(SOURCE_PIPELINE, "patrones")],
    STAGE_MODEL: [
        (SOURCE_TRAINING, "comparison"),
        (SOURCE_TRAINING, "series"),
        (SOURCE_TRAINING, "scatter"),
        (SOURCE_TRAINING, "errors"),
        (SOURCE_TRAINING, "importance"),
    ],
    STAGE_OPTIMIZATION: [(SOURCE_PIPELINE, "decisiones"), (SOURCE_PIPELINE, "ahorro")],
}

STAGE_TITLES = {
    STAGE_CLEANING: "Source cleaning",
    STAGE_DATASET: "Relational dataset",
    STAGE_PATTERNS: "Demand patterns",
    STAGE_MODEL: "Demand forecast",
    STAGE_OPTIMIZATION: "Replenishment optimisation",
}

RESULT_RULE = "RESULTADO"

DISCARD_PREFIXES = ("Descartar", "Conservar solo")

KIND_DISCARD = "descarte"
KIND_ADJUST = "ajuste"
KIND_RESULT = "resultado"

CAUSE_BY_DECISION = {
    DECISION_BUY: "Stock is below the operating minimum",
    DECISION_REVIEW: "The supplier minimum order quantity exceeds the warehouse ceiling",
    DECISION_DEFERRED: REASON_OVER_BUDGET,
    DECISION_ESCALATE: REASON_ESCALATE,
}

HOLD_CAUSES = (REASON_ABOVE_MINIMUM, REASON_NO_SUPPLIER, REASON_SHELF_LIFE_BLOCK, REASON_INFEASIBLE)

FEATURE_FAMILIES = [
    ("Lags of the series itself", ("lag_",)),
    ("Rolling means and deviations", ("roll_",)),
    ("Operating signal", ("issue_events", "breakdown_")),
    ("Calendar", ("month_",)),
    ("Part attributes", ("unit_cost", "shelf_life", "criticality")),
    ("Location", ("is_nava",)),
    ("Data origin", ("is_synthetic",)),
]

OTHER_FAMILY = "Other"


def _rule_kind(label: str) -> str:
    """Clasifica una regla de limpieza segun lo que le hace al dato.

    Entrada:
        label: enunciado de la regla tal como lo escribio la etapa de limpieza.

    Salida:
        Una de las tres clases: descarte, ajuste o resultado.

    Funcionalidad:
        Distinguirlas importa para no mentir en la grafica. Solo las reglas de
        descarte reducen filas; rellenar un nulo o marcar una lectura atipica
        toca muchas filas sin eliminar ninguna, y sumarlas al embudo daria la
        impresion de que se tiro la mitad del dato.
    """
    if label == RESULT_RULE:
        return KIND_RESULT
    if label.startswith(DISCARD_PREFIXES):
        return KIND_DISCARD
    return KIND_ADJUST


def cleaning_summary(quality_report: dict) -> dict:
    """Resume que se descarto de las fuentes crudas y por que.

    Entrada:
        quality_report: informe de calidad con las claves antes, despues y
            limpieza, tal como lo escribe la etapa de perfilado.

    Salida:
        Diccionario con una entrada por fuente, sus filas antes y despues, y las
        reglas aplicadas ya clasificadas.

    Funcionalidad:
        Es la unica etapa cuyo valor esta en lo que quito, no en lo que produjo.
        Por eso el resumen conserva el enunciado y el motivo de cada regla: sin
        el motivo, un descarte de 130 ordenes parece una perdida de dato en lugar
        de la correccion de un sesgo.
    """
    before = quality_report.get("antes", {})
    after = quality_report.get("despues", {})
    rules = quality_report.get("limpieza", {})

    sources = []
    for key, detail in before.items():
        rows_before = int(detail.get("rows", 0))
        rows_after = int(after.get(key, {}).get("rows", rows_before))
        classified = [
            {
                "rule": str(rule.get("regla", "")),
                "reason": str(rule.get("motivo", "")),
                "rows": int(rule.get("filas", 0)),
                "kind": _rule_kind(str(rule.get("regla", ""))),
            }
            for rule in rules.get(key, [])
        ]
        sources.append(
            {
                "key": key,
                "name": detail.get("name", key),
                "rows_before": rows_before,
                "rows_after": rows_after,
                "discarded": rows_before - rows_after,
                "columns_before": int(detail.get("columns", 0)),
                "columns_after": int(after.get(key, {}).get("columns", 0)),
                "rules": classified,
            }
        )

    sources.sort(key=lambda source: -source["rows_before"])
    flagged = sum(
        rule["rows"]
        for source in sources
        for rule in source["rules"]
        if rule["kind"] == KIND_ADJUST
    )

    return {
        "id": STAGE_CLEANING,
        "title": STAGE_TITLES[STAGE_CLEANING],
        "input": "Raw sources exactly as they arrived",
        "output": "The same sources, without the rows that evidence nothing",
        "parameters": {
            "iqr_factor": IQR_FACTOR,
            "mad_threshold": MAD_THRESHOLD,
            "mad_scale": MAD_SCALE,
            "min_days_per_month": MIN_DAYS_PER_MONTH,
        },
        "sources": sources,
        "rows_before": sum(source["rows_before"] for source in sources),
        "rows_after": sum(source["rows_after"] for source in sources),
        "discarded": sum(source["discarded"] for source in sources),
        "adjusted": flagged,
    }


def dataset_summary(tables: dict) -> dict:
    """Resume el dataset relacional que consume el resto del sistema.

    Entrada:
        tables: diccionario de DataFrames con las claves demand_history,
            parts_master, inventory_current, suppliers, supplier_offers,
            supplier_coverage y cities.

    Salida:
        Diccionario con el tamaño de cada tabla, el rango de meses, cuantas
        series hay y la demanda total de cada mes marcando si fue simulado.

    Funcionalidad:
        La cifra que importa aqui no es cuantas filas hay sino cuanta historia es
        real. La mitad de los meses se simularon para alcanzar los 72 que exige
        detectar estacionalidad, y esa proporcion condiciona como leer todo lo
        que viene despues.
    """
    demand = tables["demand_history"]
    months = sorted(demand["period_month"].unique())
    has_flag = "is_synthetic" in demand.columns

    monthly = []
    for month, block in demand.groupby("period_month", sort=True):
        share = float(block["is_synthetic"].mean()) if has_flag else 0.0
        monthly.append(
            {
                "period_month": str(month),
                "qty_issued": int(block["qty_issued"].sum()),
                "is_synthetic": int(share > 0.5),
            }
        )

    synthetic_rows = int(demand["is_synthetic"].sum()) if has_flag else 0

    return {
        "id": STAGE_DATASET,
        "title": STAGE_TITLES[STAGE_DATASET],
        "input": "Clean sources",
        "output": "Related, validated tables by part, city and supplier",
        "tables": [{"name": name, "rows": len(frame)} for name, frame in tables.items()],
        "months": len(months),
        "first_month": str(months[0]) if months else "",
        "last_month": str(months[-1]) if months else "",
        "series": int(demand.groupby(["sku_id", "city_id"]).ngroups),
        "parts": len(tables["parts_master"]),
        "cities": len(tables["cities"]),
        "suppliers": len(tables["suppliers"]),
        "offers": len(tables["supplier_offers"]),
        "synthetic_rows": synthetic_rows,
        "real_rows": len(demand) - synthetic_rows,
        "monthly": monthly,
    }


def pattern_summary(patterns: pd.DataFrame) -> dict:
    """Resume como quedo clasificada cada serie de demanda.

    Entrada:
        patterns: tabla de patrones con cv, fuerza estacional, significancia y
            la etiqueta asignada.

    Salida:
        Diccionario con el reparto de patrones, un punto por serie y los umbrales
        que se aplicaron.

    Funcionalidad:
        Devolver los umbrales junto a los puntos es lo que hace auditable la
        clasificacion: se puede ver que serie quedo cerca de la frontera y por
        cual de las dos condiciones de estacionalidad no paso.
    """
    counts = patterns["pattern"].value_counts()

    points = [
        {
            "sku_id": row["sku_id"],
            "city_id": row["city_id"],
            "cv": float(row["cv"]),
            "seasonal_strength": float(row["seasonal_strength"]),
            "seasonal_pvalue": float(row["seasonal_pvalue"]),
            "confidence": float(row["confidence"]),
            "pattern": row["pattern"],
        }
        for row in patterns.to_dict(orient="records")
    ]

    return {
        "id": STAGE_PATTERNS,
        "title": STAGE_TITLES[STAGE_PATTERNS],
        "input": "72 months of consumption per series",
        "output": "One pattern label and one confidence score per series",
        "counts": {str(name): int(value) for name, value in counts.items()},
        "points": points,
        "thresholds": {
            "cv_volatile": CV_VOLATILE,
            "seasonal_strength": SEASONAL_STRENGTH_MIN,
            "seasonal_pvalue": SEASONAL_PVALUE_MAX,
        },
        "parameters": {
            "cv_volatile": CV_VOLATILE,
            "seasonal_strength_min": SEASONAL_STRENGTH_MIN,
            "seasonal_pvalue_max": SEASONAL_PVALUE_MAX,
            "seasonal_period": SEASONAL_PERIOD,
            "min_periods": MIN_PERIODS,
            "weight_volume": W_VOLUME,
            "weight_volatility": W_VOLATILITY,
            "weight_recent": W_RECENT,
        },
    }


def feature_families(features: list) -> list:
    """Agrupa las variables del modelo por el tipo de informacion que aportan.

    Entrada:
        features: nombres de las columnas que entran al modelo.

    Salida:
        Lista de diccionarios con la familia y las variables que contiene, en el
        orden en que se declararon las familias.

    Funcionalidad:
        Dieciocho nombres tecnicos no explican nada a un revisor de negocio.
        Agrupados en cinco o seis familias si: el modelo mira su propio pasado,
        el calendario, la señal de averias y los atributos de la pieza.
    """
    remaining = list(features)
    grouped = []

    for family, prefixes in FEATURE_FAMILIES:
        members = [name for name in remaining if name.startswith(prefixes)]
        if members:
            grouped.append({"family": family, "features": members})
            remaining = [name for name in remaining if name not in members]

    if remaining:
        grouped.append({"family": OTHER_FAMILY, "features": remaining})
    return grouped


def model_summary(
    training_metrics: dict,
    forecast: pd.DataFrame,
    suppliers: pd.DataFrame,
    blend_weight: float,
) -> dict:
    """Resume que recibe y que entrega la etapa de proyeccion.

    Entrada:
        training_metrics: contenido del informe de entrenamiento, con metricas,
            referencias, variables e importancia.
        forecast: proyeccion por serie con su inventario minimo ya compuesto.
        suppliers: catalogo de proveedores, de donde sale el plazo de
            planificacion y su variabilidad.
        blend_weight: peso que se dio al modelo al combinarlo con la
            proyeccion estadistica.

    Salida:
        Diccionario con las variables agrupadas por familia, las metricas del
        modelo, las de las referencias, el reparto temporal del entrenamiento y
        la politica de inventario que esta etapa deja fijada.

    Funcionalidad:
        Deja explicito lo que la pantalla anterior daba por supuesto: que entra
        al modelo, que sale, y contra que se comparo para decidir si aporta algo.

        Publica ademas los parametros de la politica de inventario. El inventario
        minimo se calcula aqui, no en la optimizacion, y sin el plazo de entrega,
        su variabilidad y el factor de servicio de cada criticidad la cifra no se
        puede reconstruir a mano ni comprobar.
    """
    metrics = training_metrics.get("metrics", {})
    features = training_metrics.get("features", [])
    lead_time, lead_time_std = planning_lead_time(suppliers)

    sources = forecast["forecast_source"].value_counts() if len(forecast) else {}

    return {
        "id": STAGE_MODEL,
        "title": STAGE_TITLES[STAGE_MODEL],
        "input": f"{len(features)} features derived from each series and its part",
        "output": "A monthly demand forecast and a reorder point per series",
        "features": features,
        "families": feature_families(features),
        "metrics": metrics,
        "baselines": training_metrics.get("baselines", {}),
        "importance": training_metrics.get("importance", []),
        "series": training_metrics.get("n_series", 0),
        "train_months": training_metrics.get("train_months", ""),
        "validation_months": training_metrics.get("validation_months", ""),
        "rows_train": metrics.get("n_train", 0),
        "rows_validation": metrics.get("n_val", 0),
        "policy": {
            "lead_time_days": round(lead_time, 2),
            "lead_time_std_days": round(lead_time_std, 2),
            "demand_lead_time_avg": round(float(forecast["demand_lead_time"].mean()), 2)
            if len(forecast)
            else 0.0,
            "safety_stock_avg": round(float(forecast["safety_stock"].mean()), 2)
            if len(forecast)
            else 0.0,
            "inventory_min_total": int(forecast["inventory_min"].sum()) if len(forecast) else 0,
            "confidence_avg": round(float(forecast["confidence_final"].mean()), 2)
            if len(forecast)
            else 0.0,
            "sources": {str(name): int(value) for name, value in dict(sources).items()},
        },
        "parameters": {
            "days_per_month": DAYS_PER_MONTH,
            "z_by_criticality": dict(Z_BY_CRITICALITY),
            "quantile_z": QUANTILE_Z,
            "blend_weight": blend_weight,
            "lead_time_days": round(lead_time, 2),
            "lead_time_std_days": round(lead_time_std, 2),
        },
    }


def reason_cause(decision: str, reason: str) -> str:
    """Reduce el motivo de una fila a la causa generica que la explica.

    Entrada:
        decision: decision tomada para esa combinacion.
        reason: motivo completo tal como lo escribio el optimizador.

    Salida:
        Enunciado de la causa, sin las cifras propias de la fila.

    Funcionalidad:
        El motivo de una compra o de una revision incluye cantidades, precios y
        nombres de proveedor, de modo que cada fila tiene un texto distinto y
        agruparlas por el literal daria tantos grupos como filas. La causa de una
        compra siempre es la misma, que las existencias no alcanzan el minimo, y
        la de una revision que el lote minimo no cabe en bodega.

        Las no compras si se distinguen por su motivo, porque ahi el optimizador
        usa enunciados fijos y la diferencia entre no necesitar reposicion y no
        tener proveedor es justo lo que hay que ver.
    """
    if decision in CAUSE_BY_DECISION:
        return CAUSE_BY_DECISION[decision]
    for cause in HOLD_CAUSES:
        if reason.startswith(cause):
            return cause
    return reason


def optimization_summary(
    recommendations: pd.DataFrame,
    offers: pd.DataFrame,
    coverage: pd.DataFrame,
    suppliers: pd.DataFrame,
) -> dict:
    """Resume como se reparten las decisiones de compra y que ahorran.

    Entrada:
        recommendations: tabla de decisiones ya resueltas.
        offers: catalogo de ofertas proveedor-pieza.
        coverage: cobertura geografica de los proveedores.
        suppliers: catalogo de proveedores.

    Salida:
        Diccionario con el reparto por decision, el detalle por motivo, el
        ahorro frente a la peor oferta de cada caso y los totales.

    Funcionalidad:
        El reparto por motivo es lo que convierte una tabla de cuarenta filas en
        una explicacion: no basta con saber que hay 22 no compras, hay que saber
        que todas lo son por estar por encima del minimo.

        El ahorro se mide contra la oferta mas cara que podia haber surtido el
        mismo caso. Es la lectura honesta de que aporta el optimizador, ya que
        comparar contra no comprar nada no tendria sentido.
    """
    counts = recommendations["decision"].value_counts()

    grouped = {}
    for record in recommendations.to_dict(orient="records"):
        key = (record["decision"], reason_cause(record["decision"], record["reason"]))
        entry = grouped.setdefault(
            key, {"decision": key[0], "reason": key[1], "count": 0, "examples": []}
        )
        entry["count"] += 1
        if len(entry["examples"]) < 3:
            entry["examples"].append(
                {
                    "sku_id": record["sku_id"],
                    "city_id": record["city_id"],
                    "reason": record["reason"],
                }
            )

    reasons = sorted(grouped.values(), key=lambda item: -item["count"])

    low_confidence = int(recommendations["reason"].str.endswith(REASON_LOW_CONFIDENCE).sum())

    savings = []
    for record in recommendations.to_dict(orient="records"):
        if record["decision"] != DECISION_BUY:
            continue
        quotes = offer_costs(
            record["sku_id"],
            record["city_id"],
            record["recommended_qty"],
            offers,
            coverage,
            suppliers,
            chosen_supplier=record["supplier_id"],
        )
        if len(quotes) < 2:
            continue
        chosen = next((quote for quote in quotes if quote["chosen"]), quotes[0])
        worst = quotes[-1]
        savings.append(
            {
                "sku_id": record["sku_id"],
                "city_id": record["city_id"],
                "chosen_cost_usd": chosen["total_cost_usd"],
                "worst_cost_usd": worst["total_cost_usd"],
                "saving_usd": round(worst["total_cost_usd"] - chosen["total_cost_usd"], 2),
                "offers": len(quotes),
            }
        )

    savings.sort(key=lambda item: -item["saving_usd"])
    buying = recommendations[recommendations["decision"] == DECISION_BUY]
    deferring = recommendations[recommendations["decision"] == DECISION_DEFERRED]
    escalating = recommendations[recommendations["decision"] == DECISION_ESCALATE]
    exposed = pd.concat([deferring, escalating])

    return {
        "id": STAGE_OPTIMIZATION,
        "title": STAGE_TITLES[STAGE_OPTIMIZATION],
        "input": "Forecast, stock on hand, offers, business rules and budget",
        "output": "One decision per part and city, with its reason",
        "counts": {
            DECISION_BUY: int(counts.get(DECISION_BUY, 0)),
            DECISION_REVIEW: int(counts.get(DECISION_REVIEW, 0)),
            DECISION_DEFERRED: int(counts.get(DECISION_DEFERRED, 0)),
            DECISION_ESCALATE: int(counts.get(DECISION_ESCALATE, 0)),
            DECISION_HOLD: int(counts.get(DECISION_HOLD, 0)),
        },
        "budget_usd": SCENARIO_BUDGET_USD,
        "deferred_usd": round(float(deferring["total_cost_usd"].sum()), 2),
        "escalated_usd": round(float(escalating["total_cost_usd"].sum()), 2),
        "stockout_avoided_usd": round(float(buying["stockout_cost_usd"].sum()), 2),
        "stockout_exposed_usd": round(float(exposed["stockout_cost_usd"].sum()), 2),
        "stockout_return": round(
            float(buying["stockout_cost_usd"].sum() / buying["total_cost_usd"].sum()), 1
        )
        if float(buying["total_cost_usd"].sum()) > 0
        else 0.0,
        "reasons": reasons,
        "savings": savings,
        "investment_usd": round(float(buying["total_cost_usd"].sum()), 2),
        "units": int(buying["recommended_qty"].sum()),
        "saving_usd": round(sum(item["saving_usd"] for item in savings), 2),
        "allocation": budget_allocation_summary(recommendations, SCENARIO_BUDGET_USD),
        "eoq_units_avg": round(float(buying["eoq_units"].mean()), 1) if len(buying) else 0.0,
        "parameters": {
            "budget_usd": SCENARIO_BUDGET_USD,
            "overrun_max_usd": BUDGET_OVERRUN_MAX_USD,
            "service_floor": dict(SERVICE_FLOOR_BY_CRITICALITY),
            "stockout_cost_per_day_usd": dict(STOCKOUT_COST_PER_DAY_USD),
            "planning_period_days": PLANNING_PERIOD_DAYS,
            "holding_cost_rate_annual": HOLDING_COST_RATE_ANNUAL,
            "months_per_year": MONTHS_PER_YEAR,
            "eoq_max_coverage_months": EOQ_MAX_COVERAGE_MONTHS,
            "shelf_life_safety_ratio": SHELF_LIFE_SAFETY_RATIO,
            "days_per_month": DAYS_PER_MONTH,
        },
        "needs_review": int(recommendations["needs_review"].sum()),
        "low_confidence": low_confidence,
    }


def trace_part(
    sku_id: str,
    city_id: str,
    demand: pd.DataFrame,
    patterns: pd.DataFrame,
    forecast: pd.DataFrame,
    recommendations: pd.DataFrame,
    offers: pd.DataFrame,
    coverage: pd.DataFrame,
    suppliers: pd.DataFrame,
) -> dict:
    """Sigue una pieza concreta por todas las etapas del pipeline.

    Entrada:
        sku_id: identificador de la pieza.
        city_id: identificador de la ciudad.
        demand: historico mensual completo.
        patterns: clasificacion de patrones.
        forecast: proyeccion e inventario minimo por serie.
        recommendations: decisiones de compra.
        offers: catalogo de ofertas proveedor-pieza.
        coverage: cobertura geografica de los proveedores.
        suppliers: catalogo de proveedores.

    Salida:
        Diccionario con la historia de la serie, su patron, lo que proyecto el
        modelo, como se compuso su inventario minimo, las ofertas que compitieron
        y la decision final. Devuelve None si la combinacion no existe.

    Funcionalidad:
        Los resumenes agregados dicen que hace el sistema; esto dice que le paso
        a una pieza. Es la vista que responde a la pregunta de donde salio un
        numero concreto, que es la que se hace cualquiera que revise una compra.

        Las ofertas se cotizan aunque la decision haya sido no comprar, porque
        parte de la explicacion es justamente que alternativas habia y por que
        ninguna hizo falta.
    """
    decision_rows = recommendations[
        (recommendations["sku_id"] == sku_id) & (recommendations["city_id"] == city_id)
    ]
    if decision_rows.empty:
        return None

    decision = decision_rows.iloc[0].to_dict()

    history = demand[(demand["sku_id"] == sku_id) & (demand["city_id"] == city_id)].sort_values(
        "period_month"
    )
    has_flag = "is_synthetic" in history.columns

    pattern_rows = patterns[(patterns["sku_id"] == sku_id) & (patterns["city_id"] == city_id)]
    forecast_rows = forecast[(forecast["sku_id"] == sku_id) & (forecast["city_id"] == city_id)]

    return {
        "sku_id": sku_id,
        "city_id": city_id,
        "description": decision.get("description", ""),
        "criticality": decision.get("criticality", ""),
        "history": [
            {
                "period_month": str(row["period_month"]),
                "qty_issued": int(row["qty_issued"]),
                "is_synthetic": int(row["is_synthetic"]) if has_flag else 0,
            }
            for row in history.to_dict(orient="records")
        ],
        "pattern": pattern_rows.iloc[0].to_dict() if not pattern_rows.empty else None,
        "forecast": forecast_rows.iloc[0].to_dict() if not forecast_rows.empty else None,
        "decision": decision,
        "offers": offer_costs(
            sku_id,
            city_id,
            decision.get("recommended_qty") or 0,
            offers,
            coverage,
            suppliers,
            chosen_supplier=decision.get("supplier_id"),
        ),
    }


def build_stages(
    quality_report: dict,
    tables: dict,
    patterns: pd.DataFrame,
    training_metrics: dict,
    forecast: pd.DataFrame,
    recommendations: pd.DataFrame,
    blend_weight: float,
) -> list:
    """Compone el recorrido completo del pipeline.

    Entrada:
        quality_report: informe de calidad de la etapa de limpieza.
        tables: DataFrames del dataset relacional.
        patterns: clasificacion de patrones.
        training_metrics: informe del ultimo entrenamiento.
        forecast: proyeccion por serie con su inventario minimo.
        recommendations: decisiones de compra.
        blend_weight: peso del modelo en la combinacion de proyecciones.

    Salida:
        Lista de resumenes de etapa en el orden en que se ejecutan.

    Funcionalidad:
        Da a la interfaz el recorrido entero en una sola estructura, de modo que
        el diagrama de etapas y el detalle de cada una se pinten a partir de la
        misma fuente y no puedan desincronizarse.

        Cada etapa declara que graficas la ilustran y de que endpoint salen. Las
        del modelo las produce el entrenamiento y las demas el informe de
        pipeline, distincion que la interfaz necesita para componer la ruta.
    """
    stages = [
        cleaning_summary(quality_report),
        dataset_summary(tables),
        pattern_summary(patterns),
        model_summary(training_metrics, forecast, tables["suppliers"], blend_weight),
        optimization_summary(
            recommendations,
            tables["supplier_offers"],
            tables["supplier_coverage"],
            tables["suppliers"],
        ),
    ]

    for stage in stages:
        stage["charts"] = [
            {"source": source, "key": key} for source, key in STAGE_CHARTS[stage["id"]]
        ]
    return stages
