/* Modelo y pipeline: de donde sale cada numero.
 *
 * Dos piezas. Arriba el recorrido completo —limpieza, dataset, patrones,
 * proyeccion, optimizacion— donde cada etapa declara que entra, que sale, que
 * hizo con lo que recibio y, ahora, con que formulas lo hizo. Abajo el
 * trazador, que recorre esas mismas cinco etapas para una sola pieza en una
 * sola planta.
 *
 * La narrativa por etapa se conserva porque es donde esta el criterio de
 * dominio: que un mes con un solo dia registrado se leeria como caida de
 * demanda, que la mitad de la historia es simulada, o que las filas en revision
 * no son un fallo del solver. Eso no se reescribe.
 *
 * Las formulas viven en `formulas.js` y los valores de sus parametros llegan del
 * informe, que los lee del codigo Python. La pantalla no los escribe a mano.
 */

import { api, apiUrl, state } from "./api.js";
import { count, decisionWord, escape, pattern as patternWord, percent } from "./format.js";
import { renderTheory } from "./formulas.js";

const money = (value) => Number(value || 0).toLocaleString("en-US", { maximumFractionDigits: 0 });
const pct = (value, digits = 1) => `${((value || 0) * 100).toFixed(digits)}%`;

const figureCard = (label, value, sub, tone = "") => `
  <div class="fig">
    <span class="label">${escape(label)}</span>
    <strong class="fig__n ${tone ? `fig__n--${tone}` : ""}">${value}</strong>
    <span class="meta">${escape(sub || "")}</span>
  </div>`;

const dataTable = (headers, rows) => `
  <table class="mini">
    <thead><tr>${headers.map((h) => `<th>${escape(h)}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((row) => `<tr>${row.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody>
  </table>`;

const panel = (title, inner) => `
  <section class="subpanel"><h3>${escape(title)}</h3>${inner}</section>`;

function verdict(metrics) {
  const gain = metrics.mejora_vs_promedio_movil || 0;
  const naive = metrics.mejora_vs_ultimo_mes || 0;
  if (gain < 0.05) {
    return `The model improves ${pct(naive, 0)} over repeating last month, but only `
      + `${pct(gain, 1)} over the moving average. That is an honest result: two thirds of `
      + `the series are flat and there is no structure to learn there. That is why the `
      + `final forecast averages both methods instead of betting everything on the model.`;
  }
  return `The model improves ${pct(gain, 0)} over the moving average and ${pct(naive, 0)} `
    + `over repeating last month. The final forecast combines both methods.`;
}

const CHART_INFO = {
  limpieza: ["What was discarded and why",
    "Rows removed from each source, grouped by the rule that removed them."],
  dataset: ["The history available",
    "Aggregate monthly consumption, separating observed months from simulated ones."],
  patrones: ["Pattern map", "Each series placed by its variability and its seasonal strength."],
  decisiones: ["Where each series ended up",
    "How the forty combinations split across the decisions."],
  ahorro: ["What choosing the supplier saved",
    "Difference between the chosen offer and the worst applicable one, per purchase."],
  comparison: ["Error against the baselines",
    "The model against repeating last month and against the moving average."],
  series: ["Forecast against actual consumption",
    "Month by month on the highest-volume series during validation."],
  scatter: ["Predicted against observed",
    "Each point is a month. Above the diagonal it overestimates; below, it underestimates."],
  errors: ["Error distribution",
    "Centred on zero means it does not systematically buy too much or too little."],
  importance: ["Weight of each feature", "How much the error worsens when each one is shuffled."],
};

/* ---------- La narrativa de cada etapa ---------- */

const STAGE_INFO = {
  limpieza: {
    step: "0",
    carries: "clean sources",
    headline: (s) => `−${count(s.discarded)} rows`,
    note: () => "This is the only stage whose value lies in what it removed. What matters "
      + "is not the number of rows discarded but the reason: cancelled orders counted as "
      + "deliveries were biasing the lead time downwards, and a month with a single day "
      + "recorded would have read as a collapse in demand.",
    figures: (s) => [
      figureCard("Raw rows", count(s.rows_before), `${s.sources.length} sources`),
      figureCard("Usable rows", count(s.rows_after), "enter the dataset", "go"),
      figureCard("Discarded", count(s.discarded), "evidence nothing", "hold"),
      figureCard("Adjusted", count(s.adjusted), "corrected without removing"),
    ],
    detail: (s) => s.sources.map((source) => panel(
      `${source.name} · ${count(source.rows_before)} → ${count(source.rows_after)} rows`,
      dataTable(["Rule", "Reason", "Rows", "Effect"],
        source.rules.filter((rule) => rule.kind !== "resultado").map((rule) => [
          escape(rule.rule),
          `<span class="meta">${escape(rule.reason)}</span>`,
          `<span class="mono num">${count(rule.rows)}</span>`,
          `<span class="badge badge--${rule.kind}">${
            rule.kind === "descarte" ? "discards" : "adjusts"}</span>`,
        ]))
    )).join(""),
  },

  dataset: {
    step: "1",
    carries: "72 months × 40 series",
    headline: (s) => `${s.months} months · ${s.series} series`,
    note: (s) => `Of the ${count(s.synthetic_rows + s.real_rows)} rows of history, `
      + `${count(s.synthetic_rows)} are months simulated backwards. They were generated `
      + "because detecting seasonality needs at least two full cycles and the observed "
      + "data did not reach that far. Worth saying before anyone asks: the decisions are "
      + "correct given that data, but half of the history did not happen.",
    figures: (s) => [
      figureCard("Months of history", s.months, `${s.first_month} to ${s.last_month}`),
      figureCard("Series", s.series, `${s.parts} parts × ${s.cities} plants`),
      figureCard("Simulated rows", count(s.synthetic_rows),
        `of ${count(s.synthetic_rows + s.real_rows)}`, "hold"),
      figureCard("Suppliers", s.suppliers, `${s.offers} offers`),
    ],
    detail: (s) => panel("Tables generated", dataTable(["Table", "Rows"],
      s.tables.map((t) => [escape(t.name), `<span class="mono num">${count(t.rows)}</span>`]))),
  },

  patrones: {
    step: "2",
    carries: "pattern per series",
    headline: (s) => `${Object.keys(s.counts).length} patterns`,
    note: (s) => "Classification is per part and plant, not per part alone: the same spare "
      + "can be stable in Nava and volatile in Obregón. Seasonal requires two conditions "
      + `at once, strength ≥ ${s.thresholds.seasonal_strength} and a significant month `
      + `effect (p < ${s.thresholds.seasonal_pvalue}), because strength on its own labels `
      + "even pure noise as seasonal.",
    figures: (s) => {
      const tones = { Estable: "go", Volatil: "hold", Estacional: "" };
      return Object.entries(s.counts)
        .map(([name, value]) =>
          figureCard(patternWord(name), value, "series", tones[name]))
        .concat(figureCard("Volatility threshold",
          `CV > ${s.thresholds.cv_volatile}`, "σ over μ"));
    },
    detail: (s) => panel("Most volatile series", dataTable(
      ["Series", "Pattern", "CV", "Seasonal strength", "p-value", "Confidence"],
      s.points.slice().sort((a, b) => b.cv - a.cv).slice(0, 10).map((p) => [
        `<span class="mono">${escape(p.sku_id)} · ${escape(p.city_id)}</span>`,
        `<span class="pill">${escape(patternWord(p.pattern))}</span>`,
        `<span class="mono num">${p.cv.toFixed(2)}</span>`,
        `<span class="mono num">${p.seasonal_strength.toFixed(2)}</span>`,
        `<span class="mono num">${p.seasonal_pvalue.toFixed(3)}</span>`,
        `<span class="mono num">${p.confidence.toFixed(2)}</span>`,
      ]))),
  },

  modelo: {
    step: "3",
    carries: "forecast and reorder point",
    headline: (s) => (s.metrics.wmape ? `WMAPE ${pct(s.metrics.wmape)}` : "not trained"),
    note: (s) => (s.metrics.wmape
      ? `${verdict(s.metrics)} This stage also settles the reorder point of every part: `
        + `${s.policy.demand_lead_time_avg} units of demand during the `
        + `${s.policy.lead_time_days}-day lead time plus a buffer of `
        + `${s.policy.safety_stock_avg} units on average. Half of that buffer is not there `
        + `for the demand but for the supplier: the lead time swings with a deviation of `
        + `${s.policy.lead_time_std_days} days.`
      : "The model has not been trained yet. Run: python -m app.services.train_model"),
    figures: (s) => [
      figureCard("Model error", s.metrics.wmape ? pct(s.metrics.wmape) : "—",
        "WMAPE on validation", "go"),
      figureCard("Over last month", pct(s.metrics.mejora_vs_ultimo_mes, 0), "trivial baseline"),
      figureCard("Over moving average", pct(s.metrics.mejora_vs_promedio_movil, 1),
        "method in production", "hold"),
      figureCard("Bias", (s.metrics.bias || 0).toFixed(2), "units per month"),
      figureCard("Planning lead time", `${s.policy.lead_time_days} d`,
        `± ${s.policy.lead_time_std_days} d of deviation`),
      figureCard("Total reorder point", count(s.policy.inventory_min_total),
        "units across the catalogue"),
    ],
    detail: (s) => panel(`What goes in · ${s.features.length} features`, dataTable(
      ["Family", "Features"],
      s.families.map((f) => [escape(f.family),
        `<span class="mono meta">${f.features.map(escape).join(", ")}</span>`])))
      + panel("What comes out · one forecast per series and month", dataTable(
        ["Method", "WMAPE", "MAE", "Bias"],
        [["Global model", s.metrics.wmape, s.metrics.mae, s.metrics.bias]]
          .concat(Object.entries(s.baselines).map(([name, r]) =>
            [name.replace(/_/g, " "), r.wmape, r.mae, r.bias]))
          .map(([name, wmape, mae, bias]) => [
            escape(name),
            `<span class="mono num">${pct(wmape)}</span>`,
            `<span class="mono num">${(mae || 0).toFixed(2)}</span>`,
            `<span class="mono num">${(bias || 0).toFixed(2)}</span>`,
          ])))
      + panel("Where the final figure comes from", dataTable(
        ["Source", "Series"],
        Object.entries(s.policy.sources).map(([name, value]) => [
          escape(name.replace("modelo+estadistico", "model and statistics combined")
            .replace("estadistico", "statistics only")),
          `<span class="mono num">${value}</span>`,
        ]))),
  },

  optimizacion: {
    step: "4",
    carries: "decision and reason",
    headline: (s) => `${s.counts.COMPRAR} purchases`,
    note: (s) => "The model is solved per part and plant: it minimises price times quantity "
      + "plus freight, subject to covering the shortfall, not exceeding the order-up-to "
      + "level, respecting the supplier minimum lot and its capacity, and a single "
      + `supplier per order. The ${s.counts.REVISAR} rows in review are not a solver `
      + "failure: they are cases where the minimum lot exceeds what the part can hold, and "
      + "a person settles that tension."
      + (s.budget_usd ? ` ${allocationNote(s)}`
        : " No budget is configured, so each part is decided without looking at what the "
          + "others spend."),
    figures: (s) => [
      figureCard("Escalate", s.counts.ESCALAR || 0,
        `${money(s.escalated_usd)} USD of extra budget`,
        (s.counts.ESCALAR || 0) > 0 ? "stop" : "go"),
      figureCard("Buy", s.counts.COMPRAR, `${count(s.units)} units`, "go"),
      figureCard("Review", s.counts.REVISAR, "minimum lot exceeds the ceiling", "hold"),
      figureCard("Deferred", s.counts.APLAZADO || 0,
        `${money(s.deferred_usd)} USD unfunded`, "stop"),
      figureCard("Investment", `${money(s.investment_usd)} USD`,
        s.allocation.overrun_usd > 0
          ? `${money(s.budget_usd)} + ${money(s.allocation.overrun_usd)} of overrun`
          : `of ${money(s.budget_usd)} USD of budget`),
      figureCard("Stockout avoided", `${money(s.stockout_avoided_usd)} USD`,
        `return ${s.stockout_return}×`, "go"),
      figureCard("Average lot", `${s.eoq_units_avg}`, "units per economic order"),
    ],
    detail: (s) => panel("Service level reached against the declared floor", dataTable(
      ["Criticality", "Replenishments due", "Funded", "Reached", "Declared floor", "Met"],
      s.allocation.service.map((level) => [
        `<span class="crit crit--${escape(level.criticality)}">${escape(level.criticality)}</span>`,
        `<span class="mono num">${level.needed}</span>`,
        `<span class="mono num">${level.funded}</span>`,
        `<span class="mono num">${level.achieved === null ? "—" : percent(level.achieved)}</span>`,
        `<span class="mono num meta">${percent(level.floor)}</span>`,
        level.met ? '<span class="badge badge--ajuste">yes</span>'
          : '<span class="badge badge--descarte">no</span>',
      ])))
      + panel("Why each decision", dataTable(
        ["Cause", "Decision", "Cases", "Example"],
        s.reasons.map((r) => [
          escape(r.reason),
          `<span class="tag tag--${escape(r.decision)}">${escape(decisionWord(r.decision))}</span>`,
          `<span class="mono num">${r.count}</span>`,
          `<span class="meta mono">${escape(r.examples.map((e) => `${e.sku_id}·${e.city_id}`).join(", "))}</span>`,
        ])))
      + (s.savings && s.savings.length ? panel("What each purchase saved", dataTable(
        ["Series", "Offers", "Chosen", "Worst applicable", "Difference"],
        s.savings.map((i) => [
          `<span class="mono">${escape(i.sku_id)} · ${escape(i.city_id)}</span>`,
          `<span class="mono num">${i.offers}</span>`,
          `<span class="mono num">${money(i.chosen_cost_usd)}</span>`,
          `<span class="mono num meta">${money(i.worst_cost_usd)}</span>`,
          `<span class="mono num gain">−${money(i.saving_usd)}</span>`,
        ]))) : ""),
  },
};

/** El parrafo que cuenta como se repartio el dinero. Es la parte que cambio de
 *  raiz: el presupuesto dejo de mandar sobre todo, asi que la narrativa ya no
 *  puede empezar por el. */
function allocationNote(s) {
  const a = s.allocation;
  const escalated = s.counts.ESCALAR || 0;

  const head = escalated > 0
    ? `Production continuity did not fit: ${escalated} criticality-A `
      + `${escalated === 1 ? "replenishment needs" : "replenishments need"} `
      + `${money(s.escalated_usd)} USD beyond the ${money(a.budget_usd)} USD of budget and `
      + `its ${money(a.overrun_max_usd)} USD of authorised overrun, so ${
        escalated === 1 ? "it is" : "they are"} returned as ESCALATE instead of quietly `
      + "deferred."
    : "Every criticality-A replenishment is funded before anything discretionary "
      + "competes, which is what keeps a stockout from stopping a line for the sake of a "
      + "purchase that returned more per dollar.";

  const cost = a.overrun_usd > 0
    ? ` Achieving it consumed ${money(a.overrun_usd)} USD of the `
      + `${money(a.overrun_max_usd)} USD authorised overrun, reported rather than hidden.`
    : ` It fits inside the ${money(a.budget_usd)} USD of the run.`;

  const rest = ` What is left is shared out by a knapsack that maximises net benefit — the `
    + `stockout avoided minus the cost of avoiding it — subject to a minimum service level `
    + `per criticality class. That money avoids ${money(s.stockout_avoided_usd)} USD of `
    + `stockout, a return of ${s.stockout_return}×, and leaves `
    + `${money(s.stockout_exposed_usd)} USD of risk uncovered in ${s.counts.APLAZADO} `
    + `deferred replenishments.`;

  return head + cost + rest;
}

/* ---------- El recorrido ---------- */

const pipeline = { stages: [], current: null };
const el = (id) => document.getElementById(id);

function paintTrack() {
  const track = el("pipe-track");
  track.innerHTML = pipeline.stages.map((stage, index) => {
    const info = STAGE_INFO[stage.id];
    if (!info) return "";
    const link = index < pipeline.stages.length - 1
      ? `<li class="pipe__link" aria-hidden="true"><span>${escape(info.carries)}</span></li>` : "";
    return `<li class="pipe__step">
      <button type="button" class="pipe__btn${stage.id === pipeline.current ? " pipe__btn--on" : ""}"
              data-stage="${stage.id}" aria-current="${stage.id === pipeline.current}">
        <span class="pipe__num">${info.step}</span>
        <span class="pipe__name">${escape(stage.title)}</span>
        <span class="pipe__fig">${escape(info.headline(stage))}</span>
      </button>
    </li>${link}`;
  }).join("");

  track.querySelectorAll(".pipe__btn").forEach((button) => {
    button.addEventListener("click", () => selectStage(button.dataset.stage));
  });
}

function selectStage(id) {
  const stage = pipeline.stages.find((item) => item.id === id);
  const info = STAGE_INFO[id];
  if (!stage || !info) return;
  pipeline.current = id;

  el("stage-title").textContent = stage.title;
  el("stage-in").textContent = stage.input;
  el("stage-out").textContent = stage.output;
  el("stage-figures").innerHTML = info.figures(stage).join("");
  el("stage-note").textContent = info.note(stage);
  el("stage-detail").innerHTML = info.detail(stage);
  el("stage-theory").innerHTML = renderTheory(stage.id, stage.parameters);

  el("stage-charts").innerHTML = (stage.charts || []).map((chart) => {
    const [title, note] = CHART_INFO[chart.key] || [chart.key, ""];
    return `<section class="card"><h3>${escape(title)}</h3>
      <p class="meta">${escape(note)}</p>
      <img src="${apiUrl(`/${chart.source}/charts/${chart.key}`)}" alt="${escape(title)}" loading="lazy">
    </section>`;
  }).join("");

  paintTrack();
}

export async function loadPipeline() {
  if (pipeline.stages.length) return;
  try {
    const data = await api("/pipeline/stages");
    pipeline.stages = data.stages;
    pipeline.current = data.stages[0].id;
    paintTrack();
    selectStage(pipeline.current);
    fillTracer();
  } catch (error) {
    el("stage-note").textContent = error.message;
  }
}

/* ---------- Seguir una pieza por el pipeline ----------
 * Las mismas cinco etapas, pero para una sola serie. Responde de donde salio un
 * numero concreto, que es lo que pregunta cualquiera que revise una compra.
 */

/* Consumo mensual de una serie.
 *
 * Dos decisiones sobre la escala. La primera: el eje deja holgura por encima del
 * maximo en vez de ajustarse a el, porque una serie que roza el techo del marco
 * parece descontrolada aunque varie poco. La segunda: sobre el trazo real, mas
 * claro, va la media movil de tres meses en trazo firme.
 *
 * Ninguna de las dos toca el dato: el maximo y el minimo siguen dibujados donde
 * corresponde. Lo que cambia es que la tendencia se lee por encima del ruido, en
 * lugar de quedar enterrada bajo el.
 */
function sparkline(history) {
  const values = history.map((point) => point.qty_issued);
  const top = Math.max(...values, 1) * 1.25;
  const width = 640;
  const height = 72;
  const step = width / Math.max(values.length - 1, 1);

  const at = (value, index) =>
    `${(index * step).toFixed(1)},${(height - (value / top) * height).toFixed(1)}`;
  const line = (series) =>
    series.map((value, index) => `${index ? "L" : "M"}${at(value, index)}`).join(" ");

  const window = 3;
  const smooth = values.map((_, index) => {
    const from = Math.max(0, index - window + 1);
    const slice = values.slice(from, index + 1);
    return slice.reduce((total, v) => total + v, 0) / slice.length;
  });

  const boundary = history.findIndex((point) => !point.is_synthetic);
  const shade = boundary > 0
    ? `<rect x="0" y="0" width="${(boundary * step).toFixed(1)}" height="${height}" class="spark__sim"/>`
    : "";

  /* El consumo de cada mes va en barra y la tendencia en linea. Dos lineas
     superpuestas competian entre si y la mas clara parecia un fantasma; una
     barra y una linea no se confunden nunca, porque dicen cosas distintas: la
     barra es lo que paso ese mes, la linea es hacia donde va. */
  const bars = values.map((value, index) => {
    const x = index * step;
    const y = height - (value / top) * height;
    return `<rect x="${(x - step * 0.32).toFixed(1)}" y="${y.toFixed(1)}"
      width="${Math.max(1.5, step * 0.64).toFixed(1)}" height="${(height - y).toFixed(1)}"
      class="spark__bar"/>`;
  }).join("");

  return `<svg class="sparkline" viewBox="0 0 ${width} ${height}"
    role="img" aria-label="Monthly consumption of the series">${shade}
    ${bars}
    <path d="${line(smooth)}" class="spark__line"/></svg>
    <span class="spark__key">
      <span><i class="k-bar"></i>consumption of the month</span>
      <span><i class="k-real"></i>3-month trend</span>
      ${boundary > 0 ? '<span><i class="k-sint"></i>simulated stretch</span>' : ""}
    </span>`;
}

const traceStep = (step, title, inner, wide) => `
  <section class="trace__step${wide ? " trace__step--wide" : ""}">
    <header><span class="trace__num">${escape(step)}</span><h3>${escape(title)}</h3></header>
    ${inner}
  </section>`;

const pairs = (entries) => `<dl class="kv kv--wide">${entries
  .map(([term, value]) => `<dt>${escape(term)}</dt><dd>${value}</dd>`).join("")}</dl>`;

function renderTrace(trace) {
  const forecast = trace.forecast || {};
  const pattern = trace.pattern || {};
  const decision = trace.decision;
  const synthetic = trace.history.filter((point) => point.is_synthetic).length;
  const observed = trace.history.length - synthetic;

  return traceStep("1", "Consumption history", `
    ${sparkline(trace.history)}
    ${pairs([
      ["Months", `${trace.history.length} (${observed} observed, ${synthetic} simulated)`],
      ["Mean consumption", `${(pattern.mean_monthly || 0).toFixed(1)} units/month`],
      ["Months with no consumption", pct(pattern.zero_ratio, 0)],
    ])}`)

    + traceStep("2", "Pattern classification", pairs([
      ["Pattern", `<span class="pill">${escape(patternWord(pattern.pattern) || "—")}</span>`],
      ["Coefficient of variation", (pattern.cv || 0).toFixed(2)],
      ["Seasonal strength", `${(pattern.seasonal_strength || 0).toFixed(2)} (p ${(pattern.seasonal_pvalue || 0).toFixed(3)})`],
      ["Recommended method", escape(pattern.recommended_model || "—")],
      ["Pattern confidence", (pattern.confidence || 0).toFixed(2)],
    ]))

    + traceStep("3", "What comes out of the model", pairs([
      ["ML model forecast", `${(forecast.forecast_model || 0).toFixed(2)} units/month`],
      ["Statistical method", escape(forecast.method || "—")],
      ["Final forecast", `<strong>${(forecast.forecast_q50 || 0).toFixed(2)}</strong> units/month`],
      ["Scenarios", `${(forecast.forecast_q25 || 0).toFixed(1)} to ${(forecast.forecast_q75 || 0).toFixed(1)}`],
      ["Origin of the figure", escape(forecast.forecast_source || "—")],
      ["Final confidence", (forecast.confidence_final || 0).toFixed(2)],
    ]))

    + traceStep("4", "How the reorder point is built", pairs([
      ["Replenishment lead time", `${(forecast.lead_time_days || 0).toFixed(1)} days`],
      ["Demand during the lead time", `${(forecast.demand_lead_time || 0).toFixed(2)} units`],
      ["Safety buffer", `${(forecast.safety_stock || 0).toFixed(2)} units`],
      ["Reorder point", `<strong>${decision.inventory_min}</strong> units`],
      ["Stock on hand today", `${decision.on_hand_qty} units`],
      ["Refill level", `${decision.inventory_max} units`],
    ]))

    + traceStep("5", "Where the order quantity comes from", pairs([
      ["Freight per order (K)", `${(decision.order_cost_usd || 0).toFixed(2)} USD`],
      ["Holding cost (h)", `${(decision.holding_cost_usd || 0).toFixed(2)} USD/unit/year`],
      ["Annual demand (D)", `${((decision.demand_monthly || 0) * 12).toFixed(0)} units/year`],
      ["Economic order quantity", `<strong>${decision.eoq_units || 0}</strong> units`],
      ["Refill level", `${decision.inventory_min} + ${decision.eoq_units || 0} = `
        + `<strong>${decision.inventory_max}</strong> units`],
      ["Cap from shelf life", `${decision.max_allowed_qty} units`],
    ]))

    + traceStep("6", "Offers that competed", trace.offers.length
      ? dataTable(["Supplier", "Price", "Min. lot", "Freight", "Delivery", "Units", "Total"],
          trace.offers.map((offer) => [
            `${escape(offer.supplier_name)}${offer.chosen ? ' <span class="offer__tag">chosen</span>' : ""}`,
            `<span class="mono num">${(offer.unit_price_usd).toFixed(2)}</span>`,
            `<span class="mono num">${offer.moq}</span>`,
            `<span class="mono num">${money(offer.freight_cost_usd)}</span>`,
            `<span class="mono num">${offer.lead_time_days}d</span>`,
            `<span class="mono num">${offer.units}</span>`,
            `<span class="mono num">${money(offer.total_cost_usd)}</span>`,
          ]))
      : '<p class="meta">No offer covers this part at this plant.</p>', true)

    + traceStep("7", "Decision", `
      <p class="trace__decision">
        <span class="tag tag--${escape(decision.decision)}">${escape(decisionWord(decision.decision))}</span>
        ${decision.recommended_qty ? `<strong>${decision.recommended_qty} units</strong>` : ""}
        ${decision.supplier_name ? `from ${escape(decision.supplier_name)}` : ""}
        ${decision.total_cost_usd ? `for ${money(decision.total_cost_usd)} USD` : ""}
      </p>
      <p class="meta">${escape(decision.reason)}</p>`);
}

function fillTracer() {
  const skuSelect = el("tr-sku");
  const citySelect = el("tr-city");
  if (skuSelect.dataset.ready || !state.items.length) return;

  const parts = new Map();
  const cities = new Map();
  state.items.forEach((item) => {
    parts.set(item.sku_id, `${item.sku_id} · ${item.description}`);
    cities.set(item.city_id, item.city_name);
  });

  const fill = (node, entries) => {
    node.innerHTML = entries
      .map(([value, label]) => `<option value="${escape(value)}">${escape(label)}</option>`).join("");
  };

  fill(skuSelect, [...parts.entries()].sort());
  fill(citySelect, [...cities.entries()].sort());
  skuSelect.dataset.ready = "1";
  loadTrace();
}

export async function loadTrace() {
  const sku = el("tr-sku").value;
  const city = el("tr-city").value;
  if (!sku || !city) return;

  const box = el("trace");
  box.innerHTML = '<p class="meta">Walking the pipeline…</p>';
  try {
    box.innerHTML = renderTrace(await api(
      `/pipeline/trace/${encodeURIComponent(sku)}/${encodeURIComponent(city)}`));
  } catch (error) {
    box.innerHTML = `<p class="meta">${escape(error.message)}</p>`;
  }
}

export function initPipeline() {
  el("tr-sku").addEventListener("change", loadTrace);
  el("tr-city").addEventListener("change", loadTrace);
}

export function refreshTracer() { fillTracer(); }
