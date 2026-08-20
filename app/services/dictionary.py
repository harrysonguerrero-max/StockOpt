"""Catalogo y diccionario de datos del dataset MVP.

Funcionalidad:
    Describe cada tabla generada, sus columnas, la unidad en que estan
    expresadas, si el dato proviene de las fuentes crudas o fue sintetizado, y
    que significa cada campo.

    La descripcion vive aqui una sola vez y se consume de dos formas: el
    constructor del dataset la vuelca como documento markdown, y la interfaz la
    usa para rotular las columnas del explorador de tablas. Mantener una sola
    definicion evita que el documento y la pantalla se contradigan, que es lo que
    ocurria cuando el diccionario era una cadena de texto suelta.

    El texto esta en ingles porque se ve en pantalla. Los nombres de columna y
    los codigos de decision no se traducen: viajan dentro de los CSV y cambiarlos
    romperia todo lo que los consume.
"""

from pathlib import Path

DICTIONARY_FILE = "data_dictionary.md"

STAGE_DATASET = "Dataset"
STAGE_ANALYSIS = "Analysis"
STAGE_DECISION = "Decision"
STAGE_QUALITY = "Quality"

INTRO = """Amounts in USD.
Source: B2B-Parts-Rec, the order book of industrial spare parts for food and
beverage manufacturers (Zenodo 19492687, CC-BY-4.0). One customer is used as the
company and split by production line into two plants.
Cities: Nava (Coahuila) and Ciudad Obregon (Sonora).
History is 72 observed months. Nothing is simulated backwards, so `is_synthetic`
is zero on every row.

What comes from the source and what is built on top:
  OBSERVED   unit price, machines the part is used on, month of each order
  DERIVED    criticality (from how many machines depend on the part) and family
             (from the price rank against a declared catalogue composition)
  SYNTHETIC  order quantity and commercial description, which the source does
             not carry. The original descriptions were anonymised into quantized
             embeddings and cannot be recovered."""

SOURCES = [
    ("parts_master, demand_history", "20NN_full_anonymus_v2_final.csv (B2B-Parts-Rec)"),
    ("inventory_current", "derived from the demand statistics of each series"),
    ("suppliers, supplier_offers, supplier_coverage", "declared supply tiers: OEM, national, local"),
    ("cities", "fixed LINE_ID split of one customer"),
]

KEYS = [
    "`sku_id` -> parts_master (PK). Referenced by inventory, demand and offers.",
    "`city_id` -> cities (PK). Referenced by inventory, demand and suppliers.",
    "`supplier_id` -> suppliers (PK). Referenced by offers and coverage.",
    "`offer_id` = `supplier_id` + `_` + `sku_id` (PK of supplier_offers).",
]

TABLES = {
    "cities.csv": {
        "title": "Cities",
        "stage": STAGE_DATASET,
        "summary": "The two plants in scope and the warehouse that serves each one.",
        "columns": [
            (
                "city_id",
                "str",
                "-",
                "Derived from plant_code",
                "Short city code. Primary key.",
            ),
            ("city_name", "str", "-", "Fixed mapping", "Display name."),
            ("country", "str", "-", "Fixed", "Country of the plant."),
            ("warehouse_id", "str", "-", "plant_code", "Warehouse serving that city."),
        ],
        "notes": [
            (
                "The 3 plants in the raw data are consolidated into 2 cities: two go to "
                "Nava, the larger complex, and one to Obregon."
            ),
        ],
    },
    "parts_master.csv": {
        "title": "Parts master",
        "stage": STAGE_DATASET,
        "summary": "Catalogue of the spare parts in scope, filtered to those with enough activity.",
        "columns": [
            (
                "sku_id",
                "str",
                "-",
                "ITEM_ID of the source, anonymised",
                "Part code. Primary key. Keeps the anonymous hash on purpose: it is not "
                "a manufacturer part number and should not be looked up as one.",
            ),
            (
                "description",
                "str",
                "-",
                "synthetic, generated within the family",
                "Plausible commercial name. The real one was lost when the source "
                "encoded descriptions as irreversible embeddings.",
            ),
            (
                "category",
                "str",
                "-",
                "derived from the price rank",
                "Family. Assigned by splitting the catalogue by unit cost against a "
                "declared composition, from fasteners up to control gear.",
            ),
            (
                "criticality",
                "str A/B/C",
                "-",
                "derived from machine coverage",
                "Operating criticality. Sets the service level and the stockout cost. A "
                "part serving many machines stops more when it is missing, so the number "
                "of machines that depend on it ranks the catalogue: top 8 % A, next 30 % B.",
            ),
            ("uom", "str", "-", "fixed EA", "Unit of measure it is bought in."),
            (
                "unit_cost_usd",
                "float",
                "USD",
                "real, median PRICE_EXACT of the source",
                "Book unit cost. Drives the holding cost in the economic order quantity.",
            ),
            ("currency", "str", "-", "fixed USD", "Currency of the amounts."),
            (
                "shelf_life_days",
                "int",
                "days",
                "synthetic, by family",
                "Shelf life. Caps how much can be bought at once.",
            ),
        ],
        "notes": [
            (
                "Shelf life by family: Lubrication 180, Filter 365, Seal & Gasket 730, "
                "Drive Belt 1095, Bearing 1825, Coupling 2555, Electrical 1825, Sensor "
                "1825, Fastener 3650."
            ),
            (
                "Parts with no price in the source are dropped before anything else. "
                "Holding cost derives from the value of the part, so with a value of zero "
                "the economic order quantity diverges and comparing offers loses meaning."
            ),
        ],
    },
    "inventory_current.csv": {
        "title": "Current inventory",
        "stage": STAGE_DATASET,
        "summary": "Stock on hand by part and city at the last month of history.",
        "columns": [
            ("sku_id", "str", "-", "FK parts_master", "Part."),
            ("city_id", "str", "-", "FK cities", "City."),
            ("warehouse_id", "str", "-", "derived from city_id", "Warehouse holding the parts."),
            (
                "snapshot_date",
                "str",
                "date",
                "last month of history",
                "Date the count refers to.",
            ),
            ("on_hand_qty", "int", "units", "synthetic", "Units available today."),
            (
                "reorder_point",
                "int",
                "units",
                "synthetic",
                "Level at which it is worth replenishing.",
            ),
            ("reorder_qty", "int", "units", "synthetic", "Usual replenishment quantity."),
            ("unit_cost_usd", "float", "USD", "real", "Unit cost of the part."),
            (
                "stock_value_usd",
                "float",
                "USD",
                "on_hand_qty * unit_cost_usd",
                "Capital tied up in that combination.",
            ),
            (
                "below_reorder",
                "int 0/1",
                "-",
                "on_hand_qty < reorder_point",
                "Flags whether it is already below the reorder point.",
            ),
        ],
        "notes": [
            "on_hand_qty = round(reorder_point * coverage), with coverage ~ U(0.35, 1.75). "
            "The source is an order book and carries no stock levels, so the snapshot is "
            "derived from the demand statistics of each series.",
            (
                "reorder_point = ceil(mu + z*sigma), where mu and sigma are the mean and "
                "standard deviation of monthly qty_issued per sku x city, and z is 1.65 "
                "for criticality A, 1.28 for B and 0.84 for C."
            ),
        ],
    },
    "demand_history.csv": {
        "title": "Demand history",
        "stage": STAGE_DATASET,
        "summary": "Monthly consumption by part and city, with the operating signal beside it.",
        "columns": [
            ("sku_id", "str", "-", "FK parts_master", "Part."),
            ("city_id", "str", "-", "FK cities", "City."),
            ("period_month", "str", "YYYY-MM", "real", "Month the consumption belongs to."),
            (
                "qty_issued",
                "int",
                "units",
                "synthetic, negative binomial on the price",
                "Units consumed in the month. The source records that a part was ordered "
                "but not how many, so the size of each event is generated.",
            ),
            (
                "issue_events",
                "int",
                "events",
                "real, order lines of the month",
                "Order lines recorded in the month. This is the observed intermittency "
                "signal and the reason for using this source.",
            ),
            (
                "breakdown_events",
                "int",
                "events",
                "not available in the source",
                "Always zero. The source has no breakdown flag, so the model feature that "
                "reads it is inert.",
            ),
            (
                "is_synthetic",
                "int 0/1",
                "-",
                "always 0",
                "Every month is observed. Nothing is simulated backwards any more.",
            ),
        ],
        "notes": [
            (
                "The grid is dense on purpose: months with no order appear with a zero "
                "instead of being absent. In a spare-parts catalogue those zeros are most "
                "of the data —around three in four months nothing moves— and they are "
                "what decides the demand pattern and how much buffer the part needs."
            ),
        ],
    },
    "suppliers.csv": {
        "title": "Suppliers",
        "stage": STAGE_DATASET,
        "summary": "The 5 suppliers with lead times measured on real purchase orders.",
        "columns": [
            ("supplier_id", "str", "-", "assigned", "Supplier code. Primary key."),
            ("name", "str", "-", "real", "Legal name."),
            ("city_id", "str", "-", "assigned cyclically", "City where it is based."),
            ("active", "bool", "-", "fixed True", "Whether it can receive orders."),
            ("contact_email", "str", "-", "synthetic", "Address the order is sent to."),
            (
                "base_freight_usd",
                "float",
                "USD",
                "synthetic",
                "Base freight before the destination-city surcharge.",
            ),
            (
                "lead_time_avg_days",
                "float",
                "days",
                "real",
                "Mean time between order and delivery.",
            ),
            ("lead_time_min_days", "int", "days", "real", "Best observed lead time."),
            ("lead_time_max_days", "int", "days", "real", "Worst observed lead time."),
            (
                "lead_time_std_days",
                "float",
                "days",
                "real",
                "Lead-time variability. Feeds the safety stock.",
            ),
        ],
        "notes": [
            (
                "The four lead times come from Delivery_Date minus Order_Date over "
                "delivered orders. Variability is high: sigma over mean is around 0.53, "
                "so the lead-time half of the safety stock is not cosmetic."
            ),
        ],
    },
    "supplier_offers.csv": {
        "title": "Supplier-part offers",
        "stage": STAGE_DATASET,
        "summary": "Price, minimum order quantity and capacity of each supplier for each part.",
        "columns": [
            ("offer_id", "str", "-", "supplier_id + sku_id", "Primary key of the offer."),
            ("supplier_id", "str", "-", "FK suppliers", "Supplier making the offer."),
            ("sku_id", "str", "-", "FK parts_master", "Part being offered."),
            ("unit_price_usd", "float", "USD", "synthetic", "Price per unit."),
            (
                "moq",
                "int",
                "units",
                "synthetic",
                "Minimum order quantity. It is the constraint that produces review cases.",
            ),
            ("capacity_per_month", "int", "units", "synthetic", "How much it can supply per month."),
            ("currency", "str", "-", "fixed USD", "Currency of the price."),
        ],
        "notes": [
            (
                "The supplier margin runs from 1.05 to 1.17 in steps of 0.03 over book "
                "cost. Each part gets 2 or 3 offers, so the optimiser always has "
                "something to compare against."
            ),
            (
                "Freight does not live here but in supplier_coverage, because it depends "
                "on the destination city and not on the part."
            ),
        ],
    },
    "supplier_coverage.csv": {
        "title": "Geographic coverage",
        "stage": STAGE_DATASET,
        "summary": "Which supplier can serve which city, and at what surcharge.",
        "columns": [
            ("supplier_id", "str", "-", "FK suppliers", "Supplier."),
            ("city_id", "str", "-", "FK cities", "City it serves."),
            ("is_home", "int 0/1", "-", "derived", "Whether it is its home city."),
            (
                "freight_cost_usd",
                "float",
                "USD",
                "derived from base freight",
                "Freight to that city. It is the fixed order cost in the Wilson formula.",
            ),
            (
                "lead_time_extra_days",
                "int",
                "days",
                "derived",
                "Extra days when supplying outside its home city.",
            ),
        ],
        "notes": [
            (
                "Without this table the optimiser was infeasible for one in four "
                "combinations, because no supplier served the city."
            ),
        ],
    },
    "demand_patterns.csv": {
        "title": "Demand patterns",
        "stage": STAGE_ANALYSIS,
        "summary": "Classification of each series and the measurements behind it.",
        "columns": [
            ("sku_id", "str", "-", "FK parts_master", "Part."),
            ("city_id", "str", "-", "FK cities", "City."),
            ("n_periods", "int", "months", "computed", "Months of history available."),
            ("mean_monthly", "float", "units", "computed", "Mean monthly consumption."),
            ("std_monthly", "float", "units", "computed", "Monthly standard deviation."),
            (
                "cv",
                "float",
                "-",
                "std / mean",
                "Coefficient of variation. Decides whether the series is volatile.",
            ),
            ("zero_ratio", "float", "-", "computed", "Share of months with no consumption."),
            (
                "adi",
                "float",
                "months",
                "periods / periods with demand",
                "Average inter-demand interval. Above 1.32 the series is intermittent.",
            ),
            (
                "cv_squared",
                "float",
                "-",
                "computed on periods with demand only",
                "Squared coefficient of variation of the event size. Above 0.49 the series "
                "is lumpy as well as intermittent.",
            ),
            (
                "seasonal_strength",
                "float",
                "-",
                "seasonal_decompose",
                "Strength of the seasonal component.",
            ),
            (
                "seasonal_pvalue",
                "float",
                "-",
                "Kruskal-Wallis",
                "Significance of the month effect.",
            ),
            ("trend_tau", "float", "-", "Mann-Kendall", "Direction and strength of the trend."),
            ("trend_pvalue", "float", "-", "Mann-Kendall", "Significance of the trend."),
            (
                "pattern",
                "str",
                "-",
                "classification rules",
                "Final label: Estacional, Tendencia, Estable, Volatil or Insuficiente.",
            ),
            (
                "confidence",
                "float 0-1",
                "-",
                "computed",
                "How much confidence that label deserves.",
            ),
            (
                "recommended_model",
                "str",
                "-",
                "derived from the pattern",
                "Forecasting method that matches the pattern.",
            ),
        ],
        "notes": [
            (
                "Classification is per part and city, not per part alone: 8 of 20 parts "
                "change pattern depending on the plant."
            ),
            (
                "Seasonal requires two conditions at once, strength of at least 0.45 and "
                "a significant month effect, because strength on its own labels even "
                "pure noise as seasonal."
            ),
        ],
    },
    "demand_forecast.csv": {
        "title": "Demand forecast",
        "stage": STAGE_ANALYSIS,
        "summary": "What comes out of the model per series, and the reorder point derived from it.",
        "columns": [
            ("sku_id", "str", "-", "FK parts_master", "Part."),
            ("city_id", "str", "-", "FK cities", "City."),
            ("pattern", "str", "-", "demand_patterns", "Pattern detected for the series."),
            ("method", "str", "-", "derived from the pattern", "Statistical method applied."),
            ("n_periods", "int", "months", "computed", "Months used to forecast."),
            ("forecast_q25", "float", "units", "computed", "Low monthly demand scenario."),
            (
                "forecast_q50",
                "float",
                "units",
                "computed",
                "Expected monthly demand. This is what enters the optimiser.",
            ),
            ("forecast_q75", "float", "units", "computed", "High monthly demand scenario."),
            (
                "wmape_backtest",
                "float",
                "-",
                "backtest",
                "Error of the method on the series itself.",
            ),
            (
                "confidence_pattern",
                "float 0-1",
                "-",
                "demand_patterns",
                "Confidence contributed by the pattern.",
            ),
            (
                "confidence_final",
                "float 0-1",
                "-",
                "computed",
                "Combined confidence. Below the threshold it flags a review.",
            ),
            (
                "lead_time_days",
                "float",
                "days",
                "suppliers",
                "Replenishment lead time used for planning.",
            ),
            (
                "demand_lead_time",
                "float",
                "units",
                "inventory_policy",
                "Expected demand while the replenishment is in transit.",
            ),
            (
                "safety_stock",
                "float",
                "units",
                "inventory_policy",
                "Buffer absorbing both demand and lead-time variability.",
            ),
            (
                "inventory_min",
                "int",
                "units",
                "demand_lead_time + safety_stock",
                "Reorder point: the minimum operating level of the part.",
            ),
            (
                "issue_rate",
                "float 0-1",
                "-",
                "issue_events / 30",
                "How often the part is requested. Scales the stockout cost.",
            ),
            (
                "forecast_model",
                "float",
                "units",
                "ML model",
                "Forecast from the trained global model.",
            ),
            (
                "forecast_source",
                "str",
                "-",
                "computed",
                "Whether the final figure comes from the model, the statistics or both.",
            ),
            (
                "needs_review",
                "int 0/1",
                "-",
                "computed",
                "Flags series whose forecast is not reliable.",
            ),
        ],
        "notes": [
            (
                "The minimum was unified here: the dataset used to cover a full month "
                "and the forecast only the actual lead time, so both stages gave "
                "opposite answers about what to replenish."
            ),
            (
                "issue_rate captures the intermittency of consumption: the median series "
                "moves on eleven days out of thirty. A day without stock only costs "
                "money if somebody asks for the part that day."
            ),
        ],
    },
    "purchase_recommendations.csv": {
        "title": "Purchase recommendations",
        "stage": STAGE_DECISION,
        "summary": "The final decision per part and city, with its reason.",
        "columns": [
            ("sku_id", "str", "-", "FK parts_master", "Part."),
            ("city_id", "str", "-", "FK cities", "City."),
            ("description", "str", "-", "parts_master", "Description of the part."),
            ("criticality", "str A/B/C", "-", "parts_master", "Operating criticality."),
            ("on_hand_qty", "int", "units", "inventory_current", "Stock on hand."),
            (
                "inventory_min",
                "int",
                "units",
                "demand_forecast",
                "Reorder point that has to be sustained.",
            ),
            (
                "inventory_max",
                "int",
                "units",
                "inventory_min + eoq_units",
                "Order-up-to level. In an (s, S) policy it is also the inventory ceiling.",
            ),
            (
                "demand_monthly",
                "float",
                "units",
                "demand_forecast",
                "Forecast monthly demand.",
            ),
            (
                "forecast_source",
                "str",
                "-",
                "demand_forecast",
                "Where the forecast used comes from.",
            ),
            ("shelf_life_days", "int", "days", "parts_master", "Shelf life of the part."),
            (
                "order_cost_usd",
                "float",
                "USD",
                "mean freight of applicable offers",
                "Fixed cost of bringing one order. It is K in the Wilson formula.",
            ),
            (
                "holding_cost_usd",
                "float",
                "USD/unit/year",
                "annual rate * unit_cost_usd",
                "Cost of keeping one unit idle for a year. It is h in the Wilson formula.",
            ),
            (
                "eoq_units",
                "int",
                "units",
                "sqrt(2*K*D/h), capped by coverage",
                "Economic order quantity: what balances freight against holding cost.",
            ),
            (
                "target_qty",
                "int",
                "units",
                "computed",
                "Level the purchase brings stock up to.",
            ),
            (
                "max_allowed_qty",
                "int",
                "units",
                "computed",
                "Cap from the order-up-to level and from shelf life.",
            ),
            (
                "coverage_months",
                "float",
                "months",
                "computed",
                "Months of stock the purchase would leave.",
            ),
            (
                "decision",
                "str",
                "-",
                "optimiser",
                "COMPRAR, NO_COMPRAR, REVISAR, APLAZADO or ESCALAR.",
            ),
            ("recommended_qty", "int", "units", "optimiser", "Units to order."),
            ("supplier_id", "str", "-", "optimiser", "Chosen supplier."),
            ("supplier_name", "str", "-", "suppliers", "Name of the chosen supplier."),
            ("unit_price_usd", "float", "USD", "supplier_offers", "Unit price applied."),
            ("freight_cost_usd", "float", "USD", "supplier_coverage", "Freight for the order."),
            ("lead_time_days", "float", "days", "suppliers", "Lead time of the chosen supplier."),
            (
                "total_cost_usd",
                "float",
                "USD",
                "price * quantity + freight",
                "Total cost of the order.",
            ),
            (
                "alternatives_evaluated",
                "int",
                "offers",
                "optimiser",
                "How many offers competed.",
            ),
            (
                "confidence",
                "float 0-1",
                "-",
                "demand_forecast",
                "Confidence of the forecast the decision rests on.",
            ),
            (
                "stockout_cost_usd",
                "float",
                "USD",
                "computed",
                "Cost of the stockout avoided by ordering now instead of waiting.",
            ),
            (
                "net_benefit_usd",
                "float",
                "USD",
                "stockout avoided - cost",
                "What the purchase returns. If negative, it is not made.",
            ),
            (
                "needs_review",
                "int 0/1",
                "-",
                "computed",
                "Flags rows that require human judgement.",
            ),
            ("reason", "str", "-", "optimiser", "Explicit reason for the decision."),
        ],
        "notes": [
            (
                "REVISAR is not a solver failure: it appears when the supplier minimum "
                "order quantity exceeds the order-up-to level of the part, which is a "
                "real purchasing tension and a person decides it."
            ),
            (
                "APLAZADO marks a technically correct replenishment that does not fit in "
                "the discretionary budget. It keeps quantity, supplier and cost, because "
                "that is the figure a budget increase is asked with."
            ),
            (
                "ESCALAR marks a criticality A replenishment that does not fit even "
                "after stretching the budget by the authorised overrun. Production "
                "continuity is a hard constraint, so the model does not silently drop "
                "it: it reports how much extra money the decision needs."
            ),
            (
                "The order quantity comes from the Wilson formula and not from a fixed "
                "coverage in months, so freight and the value of the part decide how "
                "much is brought in one go. The obsolescence cap keeps a cheap part with "
                "expensive freight from ordering more than half a year of consumption."
            ),
            (
                "The stockout cost is estimated as the days the part would be out of "
                "stock times the daily cost of its criticality, and that daily cost is a "
                "business parameter that has to be validated with maintenance: its "
                "magnitude alone decides how much criticality weighs against price."
            ),
            (
                "The estimate is deterministic and assumes demand happens at the "
                "forecast rate, so it understates the risk on volatile series."
            ),
        ],
    },
    "quality/demand_outliers.csv": {
        "title": "Outlier consumption months",
        "stage": STAGE_QUALITY,
        "summary": "Months that depart from their own series and need confirmation from maintenance.",
        "columns": [
            ("sku_id", "str", "-", "FK parts_master", "Part."),
            ("city_id", "str", "-", "FK cities", "City."),
            ("period_month", "str", "YYYY-MM", "demand_history", "Flagged month."),
            ("qty_issued", "int", "units", "demand_history", "Consumption observed that month."),
            (
                "median_series",
                "float",
                "units",
                "computed",
                "Typical consumption of that same series.",
            ),
            (
                "ratio_vs_median",
                "float",
                "-",
                "qty_issued / median_series",
                "How many times it departs from the usual level.",
            ),
        ],
        "notes": [
            (
                "They are evaluated against their own series and not against the whole "
                "catalogue: a part moving 100 units a month and one moving 2 have "
                "incomparable scales."
            ),
            "They are reported, not corrected. It may have been a real major shutdown.",
        ],
    },
}


def table_names() -> list:
    """Enumera las tablas del dataset en orden de pipeline.

    Entrada:
        Ninguna.

    Salida:
        Lista con el nombre de archivo de cada tabla, relativo a la carpeta del
        dataset.

    Funcionalidad:
        Es la lista blanca que usa la interfaz para decidir que se puede leer.
        Al derivarse del catalogo, una tabla nueva queda disponible con solo
        describirla aqui.
    """
    return list(TABLES)


def describe_table(name: str) -> dict:
    """Devuelve la descripcion catalogada de una tabla.

    Entrada:
        name: nombre de archivo de la tabla.

    Salida:
        Diccionario con titulo, etapa, resumen, columnas y notas, o None si la
        tabla no esta catalogada.

    Funcionalidad:
        Da a la interfaz el texto que rotula cada tabla y cada columna sin que
        tenga que mantener su propia copia de las definiciones.
    """
    spec = TABLES.get(name)
    if spec is None:
        return None

    return {
        "name": name,
        "title": spec["title"],
        "stage": spec["stage"],
        "summary": spec["summary"],
        "notes": list(spec["notes"]),
        "columns": [
            {
                "name": column,
                "type": kind,
                "unit": unit,
                "origin": origin,
                "description": description,
            }
            for column, kind, unit, origin, description in spec["columns"]
        ],
    }


def render_markdown() -> str:
    """Compone el documento del diccionario de datos.

    Entrada:
        Ninguna.

    Salida:
        Texto markdown completo del diccionario.

    Funcionalidad:
        Recorre el catalogo y genera una seccion por tabla con su cabecera de
        columnas y sus notas. Al derivarse del mismo catalogo que consume la
        interfaz, el documento no puede quedar desfasado respecto de lo que ve
        el usuario en pantalla.
    """
    lines = [
        "# Data dictionary - MRO Spare Parts Optimizer MVP",
        "",
        INTRO,
        "",
        "## Sources",
        "| Generated table | Raw source |",
        "|---|---|",
    ]
    lines += [f"| {generated} | `{raw}` |" for generated, raw in SOURCES]

    lines += ["", "## Keys"]
    lines += [f"- {key}" for key in KEYS]

    for name, spec in TABLES.items():
        lines += [
            "",
            "---",
            "",
            f"## {name} - {spec['title']}",
            "",
            spec["summary"],
            "",
            "| Column | Type | Unit | Origin | Description |",
            "|---|---|---|---|---|",
        ]
        lines += [
            f"| {column} | {kind} | {unit} | {origin} | {description} |"
            for column, kind, unit, origin, description in spec["columns"]
        ]
        for note in spec["notes"]:
            lines += ["", note]

    return "\n".join(lines) + "\n"


def write_data_dictionary(out_dir: Path) -> Path:
    """Escribe el diccionario de datos en la carpeta de salida.

    Entrada:
        out_dir: carpeta donde se publica el dataset.

    Salida:
        Ruta del archivo data_dictionary.md escrito.

    Funcionalidad:
        Crea la carpeta si no existe y vuelca el documento generado a partir del
        catalogo.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / DICTIONARY_FILE
    path.write_text(render_markdown(), encoding="utf-8")
    return path
