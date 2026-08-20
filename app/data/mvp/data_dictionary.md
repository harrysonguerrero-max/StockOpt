# Data dictionary - MRO Spare Parts Optimizer MVP

Amounts in USD (1 USD = 83 INR).
Scope: 20 MRO parts x 2 cities x 5 suppliers, monthly demand.
Cities: Nava (Coahuila) and Ciudad Obregon (Sonora).
History is shifted to end at the configured horizon and extended backwards with
simulated months, flagged with `is_synthetic`, up to 72 months.

## Sources
| Generated table | Raw source |
|---|---|
| parts_master, demand_history, inventory_current | `synthetic_industrial_machine_data.csv` |
| suppliers, supplier_offers | `Procurement KPI Analysis Dataset.csv` |
| cities | `fixed plant_code mapping` |

## Keys
- `sku_id` -> parts_master (PK). Referenced by inventory, demand and offers.
- `city_id` -> cities (PK). Referenced by inventory, demand and suppliers.
- `supplier_id` -> suppliers (PK). Referenced by offers and coverage.
- `offer_id` = `supplier_id` + `_` + `sku_id` (PK of supplier_offers).

---

## cities.csv - Cities

The two plants in scope and the warehouse that serves each one.

| Column | Type | Unit | Origin | Description |
|---|---|---|---|---|
| city_id | str | - | Derived from plant_code | Short city code. Primary key. |
| city_name | str | - | Fixed mapping | Display name. |
| country | str | - | Fixed | Country of the plant. |
| warehouse_id | str | - | plant_code | Warehouse serving that city. |

The 3 plants in the raw data are consolidated into 2 cities: two go to Nava, the larger complex, and one to Obregon.

---

## parts_master.csv - Parts master

Catalogue of the 20 spare parts in scope.

| Column | Type | Unit | Origin | Description |
|---|---|---|---|---|
| sku_id | str | - | part_no (real) | Part code. Primary key. |
| description | str | - | real | Commercial description of the part. |
| category | str | - | part_family (real) | Family the part belongs to. |
| criticality | str A/B/C | - | real | Operating criticality. Sets the service level and the stockout cost. |
| uom | str | - | real | Unit of measure it is bought in. |
| unit_cost_usd | float | USD | real, converted from INR | Book unit cost. Drives the holding cost in the economic order quantity. |
| currency | str | - | fixed USD | Currency of the amounts. |
| shelf_life_days | int | days | synthetic, by family | Shelf life. Caps how much can be bought at once. |

Shelf life by family: Lubrication 180, Filter 365, Seal & Gasket 730, Drive Belt 1095, Bearing 1825, Coupling 2555, Electrical 1825, Sensor 1825, Fastener 3650.

---

## inventory_current.csv - Current inventory

Stock on hand by part and city at the last month of history.

| Column | Type | Unit | Origin | Description |
|---|---|---|---|---|
| sku_id | str | - | FK parts_master | Part. |
| city_id | str | - | FK cities | City. |
| warehouse_id | str | - | derived from city_id | Warehouse holding the parts. |
| snapshot_date | str | date | last month of history | Date the count refers to. |
| on_hand_qty | int | units | synthetic | Units available today. |
| reorder_point | int | units | synthetic | Level at which it is worth replenishing. |
| reorder_qty | int | units | synthetic | Usual replenishment quantity. |
| unit_cost_usd | float | USD | real | Unit cost of the part. |
| stock_value_usd | float | USD | on_hand_qty * unit_cost_usd | Capital tied up in that combination. |
| below_reorder | int 0/1 | - | on_hand_qty < reorder_point | Flags whether it is already below the reorder point. |

on_hand_qty = round(reorder_point * coverage), with coverage ~ U(0.35, 1.75).

reorder_point = ceil(mu + z*sigma), where mu and sigma are the mean and standard deviation of monthly qty_issued per sku x city, and z is 1.65 for criticality A, 1.28 for B and 0.84 for C.

---

## demand_history.csv - Demand history

Monthly consumption by part and city, with the operating signal beside it.

| Column | Type | Unit | Origin | Description |
|---|---|---|---|---|
| sku_id | str | - | FK parts_master | Part. |
| city_id | str | - | FK cities | City. |
| period_month | str | YYYY-MM | real | Month the consumption belongs to. |
| qty_issued | int | units | real, monthly sum | Units consumed in the month. |
| issue_events | int | days | real | Days in the month with any consumption. Measures intermittency. |
| breakdown_events | int | events | real | Breakdowns recorded in the month. |
| is_synthetic | int 0/1 | - | extend_history | Flags whether the month was simulated to lengthen the history. |

Half of the rows are simulated months: the real ones end at the configured horizon and the history is extended backwards to reach the 72 months that detecting seasonality requires.

---

## suppliers.csv - Suppliers

The 5 suppliers with lead times measured on real purchase orders.

| Column | Type | Unit | Origin | Description |
|---|---|---|---|---|
| supplier_id | str | - | assigned | Supplier code. Primary key. |
| name | str | - | real | Legal name. |
| city_id | str | - | assigned cyclically | City where it is based. |
| active | bool | - | fixed True | Whether it can receive orders. |
| contact_email | str | - | synthetic | Address the order is sent to. |
| base_freight_usd | float | USD | synthetic | Base freight before the destination-city surcharge. |
| lead_time_avg_days | float | days | real | Mean time between order and delivery. |
| lead_time_min_days | int | days | real | Best observed lead time. |
| lead_time_max_days | int | days | real | Worst observed lead time. |
| lead_time_std_days | float | days | real | Lead-time variability. Feeds the safety stock. |

The four lead times come from Delivery_Date minus Order_Date over delivered orders. Variability is high: sigma over mean is around 0.53, so the lead-time half of the safety stock is not cosmetic.

---

## supplier_offers.csv - Supplier-part offers

Price, minimum order quantity and capacity of each supplier for each part.

| Column | Type | Unit | Origin | Description |
|---|---|---|---|---|
| offer_id | str | - | supplier_id + sku_id | Primary key of the offer. |
| supplier_id | str | - | FK suppliers | Supplier making the offer. |
| sku_id | str | - | FK parts_master | Part being offered. |
| unit_price_usd | float | USD | synthetic | Price per unit. |
| moq | int | units | synthetic | Minimum order quantity. It is the constraint that produces review cases. |
| capacity_per_month | int | units | synthetic | How much it can supply per month. |
| currency | str | - | fixed USD | Currency of the price. |

The supplier margin runs from 1.05 to 1.17 in steps of 0.03 over book cost. Each part gets 2 or 3 offers, so the optimiser always has something to compare against.

Freight does not live here but in supplier_coverage, because it depends on the destination city and not on the part.

---

## supplier_coverage.csv - Geographic coverage

Which supplier can serve which city, and at what surcharge.

| Column | Type | Unit | Origin | Description |
|---|---|---|---|---|
| supplier_id | str | - | FK suppliers | Supplier. |
| city_id | str | - | FK cities | City it serves. |
| is_home | int 0/1 | - | derived | Whether it is its home city. |
| freight_cost_usd | float | USD | derived from base freight | Freight to that city. It is the fixed order cost in the Wilson formula. |
| lead_time_extra_days | int | days | derived | Extra days when supplying outside its home city. |

Without this table the optimiser was infeasible for one in four combinations, because no supplier served the city.

---

## demand_patterns.csv - Demand patterns

Classification of each series and the measurements behind it.

| Column | Type | Unit | Origin | Description |
|---|---|---|---|---|
| sku_id | str | - | FK parts_master | Part. |
| city_id | str | - | FK cities | City. |
| n_periods | int | months | computed | Months of history available. |
| mean_monthly | float | units | computed | Mean monthly consumption. |
| std_monthly | float | units | computed | Monthly standard deviation. |
| cv | float | - | std / mean | Coefficient of variation. Decides whether the series is volatile. |
| zero_ratio | float | - | computed | Share of months with no consumption. |
| seasonal_strength | float | - | seasonal_decompose | Strength of the seasonal component. |
| seasonal_pvalue | float | - | Kruskal-Wallis | Significance of the month effect. |
| trend_tau | float | - | Mann-Kendall | Direction and strength of the trend. |
| trend_pvalue | float | - | Mann-Kendall | Significance of the trend. |
| pattern | str | - | classification rules | Final label: Estacional, Tendencia, Estable, Volatil or Insuficiente. |
| confidence | float 0-1 | - | computed | How much confidence that label deserves. |
| recommended_model | str | - | derived from the pattern | Forecasting method that matches the pattern. |

Classification is per part and city, not per part alone: 8 of 20 parts change pattern depending on the plant.

Seasonal requires two conditions at once, strength of at least 0.45 and a significant month effect, because strength on its own labels even pure noise as seasonal.

---

## demand_forecast.csv - Demand forecast

What comes out of the model per series, and the reorder point derived from it.

| Column | Type | Unit | Origin | Description |
|---|---|---|---|---|
| sku_id | str | - | FK parts_master | Part. |
| city_id | str | - | FK cities | City. |
| pattern | str | - | demand_patterns | Pattern detected for the series. |
| method | str | - | derived from the pattern | Statistical method applied. |
| n_periods | int | months | computed | Months used to forecast. |
| forecast_q25 | float | units | computed | Low monthly demand scenario. |
| forecast_q50 | float | units | computed | Expected monthly demand. This is what enters the optimiser. |
| forecast_q75 | float | units | computed | High monthly demand scenario. |
| wmape_backtest | float | - | backtest | Error of the method on the series itself. |
| confidence_pattern | float 0-1 | - | demand_patterns | Confidence contributed by the pattern. |
| confidence_final | float 0-1 | - | computed | Combined confidence. Below the threshold it flags a review. |
| lead_time_days | float | days | suppliers | Replenishment lead time used for planning. |
| demand_lead_time | float | units | inventory_policy | Expected demand while the replenishment is in transit. |
| safety_stock | float | units | inventory_policy | Buffer absorbing both demand and lead-time variability. |
| inventory_min | int | units | demand_lead_time + safety_stock | Reorder point: the minimum operating level of the part. |
| issue_rate | float 0-1 | - | issue_events / 30 | How often the part is requested. Scales the stockout cost. |
| forecast_model | float | units | ML model | Forecast from the trained global model. |
| forecast_source | str | - | computed | Whether the final figure comes from the model, the statistics or both. |
| needs_review | int 0/1 | - | computed | Flags series whose forecast is not reliable. |

The minimum was unified here: the dataset used to cover a full month and the forecast only the actual lead time, so both stages gave opposite answers about what to replenish.

issue_rate captures the intermittency of consumption: the median series moves on eleven days out of thirty. A day without stock only costs money if somebody asks for the part that day.

---

## purchase_recommendations.csv - Purchase recommendations

The final decision per part and city, with its reason.

| Column | Type | Unit | Origin | Description |
|---|---|---|---|---|
| sku_id | str | - | FK parts_master | Part. |
| city_id | str | - | FK cities | City. |
| description | str | - | parts_master | Description of the part. |
| criticality | str A/B/C | - | parts_master | Operating criticality. |
| on_hand_qty | int | units | inventory_current | Stock on hand. |
| inventory_min | int | units | demand_forecast | Reorder point that has to be sustained. |
| inventory_max | int | units | inventory_min + eoq_units | Order-up-to level. In an (s, S) policy it is also the inventory ceiling. |
| demand_monthly | float | units | demand_forecast | Forecast monthly demand. |
| forecast_source | str | - | demand_forecast | Where the forecast used comes from. |
| shelf_life_days | int | days | parts_master | Shelf life of the part. |
| order_cost_usd | float | USD | mean freight of applicable offers | Fixed cost of bringing one order. It is K in the Wilson formula. |
| holding_cost_usd | float | USD/unit/year | annual rate * unit_cost_usd | Cost of keeping one unit idle for a year. It is h in the Wilson formula. |
| eoq_units | int | units | sqrt(2*K*D/h), capped by coverage | Economic order quantity: what balances freight against holding cost. |
| target_qty | int | units | computed | Level the purchase brings stock up to. |
| max_allowed_qty | int | units | computed | Cap from the order-up-to level and from shelf life. |
| coverage_months | float | months | computed | Months of stock the purchase would leave. |
| decision | str | - | optimiser | COMPRAR, NO_COMPRAR, REVISAR, APLAZADO or ESCALAR. |
| recommended_qty | int | units | optimiser | Units to order. |
| supplier_id | str | - | optimiser | Chosen supplier. |
| supplier_name | str | - | suppliers | Name of the chosen supplier. |
| unit_price_usd | float | USD | supplier_offers | Unit price applied. |
| freight_cost_usd | float | USD | supplier_coverage | Freight for the order. |
| lead_time_days | float | days | suppliers | Lead time of the chosen supplier. |
| total_cost_usd | float | USD | price * quantity + freight | Total cost of the order. |
| alternatives_evaluated | int | offers | optimiser | How many offers competed. |
| confidence | float 0-1 | - | demand_forecast | Confidence of the forecast the decision rests on. |
| stockout_cost_usd | float | USD | computed | Cost of the stockout avoided by ordering now instead of waiting. |
| net_benefit_usd | float | USD | stockout avoided - cost | What the purchase returns. If negative, it is not made. |
| needs_review | int 0/1 | - | computed | Flags rows that require human judgement. |
| reason | str | - | optimiser | Explicit reason for the decision. |

REVISAR is not a solver failure: it appears when the supplier minimum order quantity exceeds the order-up-to level of the part, which is a real purchasing tension and a person decides it.

APLAZADO marks a technically correct replenishment that does not fit in the discretionary budget. It keeps quantity, supplier and cost, because that is the figure a budget increase is asked with.

ESCALAR marks a criticality A replenishment that does not fit even after stretching the budget by the authorised overrun. Production continuity is a hard constraint, so the model does not silently drop it: it reports how much extra money the decision needs.

The order quantity comes from the Wilson formula and not from a fixed coverage in months, so freight and the value of the part decide how much is brought in one go. The obsolescence cap keeps a cheap part with expensive freight from ordering more than half a year of consumption.

The stockout cost is estimated as the days the part would be out of stock times the daily cost of its criticality, and that daily cost is a business parameter that has to be validated with maintenance: its magnitude alone decides how much criticality weighs against price.

The estimate is deterministic and assumes demand happens at the forecast rate, so it understates the risk on volatile series.

---

## quality/demand_outliers.csv - Outlier consumption months

Months that depart from their own series and need confirmation from maintenance.

| Column | Type | Unit | Origin | Description |
|---|---|---|---|---|
| sku_id | str | - | FK parts_master | Part. |
| city_id | str | - | FK cities | City. |
| period_month | str | YYYY-MM | demand_history | Flagged month. |
| qty_issued | int | units | demand_history | Consumption observed that month. |
| median_series | float | units | computed | Typical consumption of that same series. |
| ratio_vs_median | float | - | qty_issued / median_series | How many times it departs from the usual level. |

They are evaluated against their own series and not against the whole catalogue: a part moving 100 units a month and one moving 2 have incomparable scales.

They are reported, not corrected. It may have been a real major shutdown.
