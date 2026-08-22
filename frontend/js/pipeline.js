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
import { whileLoading } from "./cargando.js";
import { count, decisionWord, escape, pattern as patternWord, percent } from "./format.js";
import { renderTheory } from "./formulas.js";

const money = (value) => Number(value || 0).toLocaleString("en-US", { maximumFractionDigits: 0 });

/* Los nombres de las referencias vienen del codigo en castellano, y en la
   pantalla tienen que leerse en el idioma de la pantalla. */
const BASELINE_NAMES = {
  ultimo_mes: "Repeat last month",
  promedio_movil: "Moving average, 6 months",
};

const baselineName = (name) => BASELINE_NAMES[name] || name.replace(/_/g, " ");
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

/* El detalle fila a fila se pliega.
 *
 * Setenta y tres compras, una por linea, no es una explicacion: es el mismo dato
 * que ya esta en la tabla de piezas, repetido aqui y empujando fuera de pantalla
 * lo que si es propio de esta etapa. Y sin embargo hay momentos en que se quiere
 * ver una pieza concreta, asi que borrarlo tampoco vale.
 *
 * Plegado resuelve las dos cosas: por defecto se ve el resumen, que es lo que
 * responde la pregunta de la etapa, y quien quiera bajar al caso lo abre. El
 * contador va en el resumen para que se sepa cuanto hay dentro antes de abrir.
 */
const drilldown = (label, rows, inner) => `
  <details class="drill">
    <summary class="drill__head">
      <span>${escape(label)}</span>
      <span class="drill__count mono">${count(rows)}</span>
    </summary>
    <div class="drill__body">${inner}</div>
  </details>`;

/** Agrupa las compras por planta y las resume. Es la unidad en que se decide:
 *  cada planta tiene sus proveedores y su bodega, y un ahorro total sin repartir
 *  no dice cual de las dos lo consiguio. */
function savingsByPlant(savings) {
  const plants = new Map();
  savings.forEach((item) => {
    const plant = plants.get(item.city_id) || { chosen: 0, worst: 0, orders: 0, choices: 0 };
    plant.chosen += item.chosen_cost_usd;
    plant.worst += item.worst_cost_usd;
    plant.orders += 1;
    plant.choices += item.offers > 1 ? 1 : 0;
    plants.set(item.city_id, plant);
  });

  const rows = [...plants.entries()].sort();
  const all = rows.reduce((sum, [, plant]) => ({
    chosen: sum.chosen + plant.chosen,
    worst: sum.worst + plant.worst,
    orders: sum.orders + plant.orders,
    choices: sum.choices + plant.choices,
  }), { chosen: 0, worst: 0, orders: 0, choices: 0 });

  return [...rows, ["All plants", all]];
}

/* El veredicto sobre el modelo tiene que decir dos cosas a la vez: cuanto mejora
   y por que su error absoluto no se puede leer como se leeria en otro problema.
   Con demanda intermitente el WMAPE supera el 100 % para cualquier metodo,
   incluido no hacer nada, porque lo domina el mes en que se proyecta algo y no
   ocurre nada. Callarlo dejaria una cifra que parece un fracaso. */
function verdict(metrics, baselines) {
  const rivals = Object.entries(baselines || {});
  const best = rivals.reduce(
    (winner, [name, r]) => (r.rmse < winner.rmse ? { name, rmse: r.rmse } : winner),
    { name: null, rmse: Infinity },
  );

  const wins = (metrics.rmse || Infinity) <= best.rmse;
  const worst = rivals.reduce(
    (found, [name, r]) => (Math.abs(r.cumulative_bias || 0) > Math.abs(found.drift || 0)
      ? { name, drift: r.cumulative_bias || 0 } : found),
    { name: null, drift: 0 },
  );

  const scale = (metrics.wmape || 0) > 1
    ? " The weighted error above 100% is not a verdict on the model: on intermittent demand "
      + "every method lands there, including doing nothing, because the error is dominated by "
      + "the months where something is forecast and nothing is ordered."
    : "";

  const drift = worst.name && Math.abs(worst.drift) > Math.abs(metrics.cumulative_bias || 0) * 3
    ? ` And the gap that matters is not the error but the drift: ${baselineName(worst.name)} `
      + `ends the validation ${count(Math.abs(Math.round(worst.drift)))} units `
      + `${worst.drift < 0 ? "short" : "long"}, against `
      + `${count(Math.abs(Math.round(metrics.cumulative_bias || 0)))} for the model. `
      + "Six months of that is a warehouse that does not match the plant."
    : "";

  const head = wins
    ? `The model has the lowest squared error of the three (${(metrics.rmse || 0).toFixed(2)} `
      + `against ${best.rmse.toFixed(2)} for the closest baseline), which is the comparison `
      + "that counts: squared error is minimised by the mean, and the mean is what the "
      + "reorder point is built from."
    : `The model does not have the lowest squared error (${(metrics.rmse || 0).toFixed(2)} `
      + `against ${best.rmse.toFixed(2)}). That is an honest result, and it is why the final `
      + "forecast averages the model with the statistical method instead of betting "
      + "everything on it.";

  return head + drift + scale;
}

const CHART_INFO = {
  limpieza: ["What was discarded and why",
    "Order lines removed from the source, grouped by the rule that removed them. The tail of "
    + "references ordered once in six years is real data, and dropping it is a decision worth "
    + "seeing stated."],
  dataset: ["The history available",
    "Aggregate monthly consumption across the catalogue, month by month."],
  patrones: ["Pattern map",
    "Each series placed on the two figures that decide its pattern: how many months pass "
    + "between consumptions, and how much the size of each consumption varies. The dashed "
    + "lines are the thresholds, so the four quadrants are the classification itself."],
  decisiones: ["Where each series ended up",
    "Each of the 1,283 part-and-plant combinations falls into exactly one cause. The bar "
    + "length is how many, and the label is the reason the optimiser gave."],
  ahorro: ["What choosing the supplier saved",
    "On the left, what each plant committed against what the worst applicable offer would "
    + "have cost. On the right, the individual purchases where that gap was widest."],
  comparison: ["The model against the baselines",
    "On the left the squared error, minimised by the mean the inventory policy consumes. On "
    + "the right where the stock would end up after six months. Both matter; neither is the "
    + "weighted error."],
  series: ["Forecast against actual consumption",
    "Month by month on the highest-volume series of each plant during validation."],
  scatter: ["Predicted against observed",
    "Each point is one month, on log axes so the mass is visible instead of one spike "
    + "stretching everything. Above the diagonal it over-forecasts; below, it falls short."],
  errors: ["Error distribution",
    "Centred on zero means it does not systematically buy too much or too little. The count "
    + "axis is logarithmic so the tails can be seen at all."],
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
    carries: (s) => `${s.months} months × ${s.series} series`,
    headline: (s) => `${s.months} months · ${s.series} series`,
    note: (s) => (s.synthetic_rows
      ? `Of the ${count(s.synthetic_rows + s.real_rows)} rows of history, `
        + `${count(s.synthetic_rows)} are months simulated backwards, generated because `
        + "detecting seasonality needs two full cycles and the observed data did not reach "
        + "that far. Worth saying before anyone asks: the decisions are correct given that "
        + "data, but part of the history did not happen."
      : `All ${count(s.real_rows)} rows of history are observed months — nothing is `
        + "simulated backwards. The source is a real order book of industrial spare parts "
        + `for food and beverage plants, and its ${s.months} months are exactly what the `
        + "pipeline needs to look for a yearly cycle. The grid is dense on purpose: a month "
        + "with no order appears as a zero rather than being absent, and in a spare-parts "
        + "catalogue those zeros are most of the data."),
    figures: (s) => [
      figureCard("Months of history", s.months, `${s.first_month} to ${s.last_month}`),
      figureCard("Series", s.series, `${s.parts} parts × ${s.cities} plants`),
      s.synthetic_rows
        ? figureCard("Simulated rows", count(s.synthetic_rows),
          `of ${count(s.synthetic_rows + s.real_rows)}`, "hold")
        : figureCard("Observed rows", count(s.real_rows), "none simulated", "go"),
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
      + "can behave differently in Nava and in Obregón. Intermittency is asked first, "
      + `before anything else: a series that only moves in ${pct(1 / 4, 0)} of its months `
      + "gives the seasonal and trend tests almost nothing but zeros to work on, so they "
      + "would be measuring the pattern of gaps rather than a cycle. The cut is the one "
      + "from Syntetos, Boylan and Croston — average interval above "
      + `${s.thresholds.adi_intermittent ?? 1.32}, and lumpy on top of that when the size `
      + `of each event varies with CV² above ${s.thresholds.cv2_lumpy ?? 0.49}. Seasonal `
      + `still requires two conditions at once, strength ≥ ${s.thresholds.seasonal_strength} `
      + `and a significant month effect (p < ${s.thresholds.seasonal_pvalue}), because `
      + "strength on its own labels even pure noise as seasonal.",
    figures: (s) => {
      const tones = { Estable: "go", Volatil: "hold", Estacional: "" };
      return Object.entries(s.counts)
        .map(([name, value]) =>
          figureCard(patternWord(name), value, "series", tones[name]))
        .concat(figureCard("Intermittency cut",
          `ADI > ${s.thresholds.adi_intermittent ?? 1.32}`,
          `lumpy if CV² > ${s.thresholds.cv2_lumpy ?? 0.49}`));
    },
    detail: (s) => panel("The series that move least", dataTable(
      ["Series", "Pattern", "ADI", "CV²", "Months with no demand", "Confidence"],
      s.points.slice()
        .sort((a, b) => (b.adi ?? b.cv) - (a.adi ?? a.cv))
        .slice(0, 10).map((p) => [
          `<span class="mono">${escape(p.sku_id)} · ${escape(p.city_id)}</span>`,
          `<span class="pill">${escape(patternWord(p.pattern))}</span>`,
          `<span class="mono num">${(p.adi ?? 0).toFixed(2)}</span>`,
          `<span class="mono num">${(p.cv_squared ?? 0).toFixed(2)}</span>`,
          `<span class="mono num">${pct(p.zero_ratio ?? 0, 0)}</span>`,
          `<span class="mono num">${p.confidence.toFixed(2)}</span>`,
        ]))),
  },

  modelo: {
    step: "3",
    carries: "forecast and reorder point",
    headline: (s) => (s.metrics.rmse ? `RMSE ${s.metrics.rmse.toFixed(1)}` : "not trained"),
    note: (s) => (s.metrics.rmse
      ? `${verdict(s.metrics, s.baselines)} This stage also settles the reorder point of every `
        + `part: ${s.policy.demand_lead_time_avg} units of demand during the `
        + `${s.policy.lead_time_days}-day lead time plus a buffer of `
        + `${s.policy.safety_stock_avg} units on average. A good part of that buffer is not `
        + `there for the demand but for the supplier: the lead time swings with a deviation of `
        + `${s.policy.lead_time_std_days} days.`
      : "The model has not been trained yet. Run: python -m app.services.train_model"),
    figures: (s) => [
      figureCard("Squared error", s.metrics.rmse ? s.metrics.rmse.toFixed(2) : "—",
        "RMSE · the metric that ranks correctly here", "go"),
      figureCard("Cumulative bias", `${(s.metrics.cumulative_bias || 0) >= 0 ? "+" : ""}${
        count(Math.round(s.metrics.cumulative_bias || 0))}`,
      "units over or short across the validation"),
      figureCard("Scaled error", s.metrics.mase ? s.metrics.mase.toFixed(2) : "—",
        "MASE · under 1 beats the naive", (s.metrics.mase || 9) < 1 ? "go" : "hold"),
      figureCard("Weighted error", s.metrics.wmape ? pct(s.metrics.wmape) : "—",
        "WMAPE · read the note before judging it", "hold"),
      figureCard("Bias per month", (s.metrics.bias || 0).toFixed(2), "units per month"),
      figureCard("Planning lead time", `${s.policy.lead_time_days} d`,
        `± ${s.policy.lead_time_std_days} d of deviation`),
      figureCard("Total reorder point", count(s.policy.inventory_min_total),
        "units across the catalogue"),
    ],
    detail: (s) => panel(`What goes in · ${s.features.length} features`, dataTable(
      ["Family", "Features"],
      s.families.map((f) => [escape(f.family),
        `<span class="mono meta">${f.features.map(escape).join(", ")}</span>`])))
      + panel("What comes out · one forecast per series and month",
        `<p class="meta subpanel__lead">Ordered by the metrics that decide. RMSE is minimised by
          the <b>mean</b>, which is what the inventory policy consumes. Cumulative bias says in
          units how short or long the plants would end up. The two on the right are built on
          absolute error, which is minimised by the <b>median</b> — and on these series the
          median is zero, so they reward the method that forecasts least.</p>`
        + dataTable(
          ["Method", "RMSE", "Cumulative bias", "MASE", "WMAPE", "MAE"],
          [["Global model", s.metrics, true]]
            .concat(Object.entries(s.baselines).map(([name, r]) => [baselineName(name), r, false]))
            .map(([name, m, isModel]) => [
              isModel ? `<b>${escape(name)}</b>` : escape(name),
              `<span class="mono num"><b>${(m.rmse || 0).toFixed(2)}</b></span>`,
              `<span class="mono num">${(m.cumulative_bias || 0) >= 0 ? "+" : ""}${
                count(Math.round(m.cumulative_bias || 0))}</span>`,
              `<span class="mono num meta">${(m.mase || 0).toFixed(2)}</span>`,
              `<span class="mono num meta">${pct(m.wmape)}</span>`,
              `<span class="mono num meta">${(m.mae || 0).toFixed(2)}</span>`,
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
      + (s.savings && s.savings.length ? panel("What choosing the supplier saved",
        `<p class="meta subpanel__lead">Every purchase is priced against the worst offer that
          would also have satisfied its constraints. The gap is what the supplier choice is
          worth — not a projection, a comparison between offers already on the table.</p>`
        + dataTable(
          ["Plant", "Purchases", "With a real choice", "Committed", "Worst applicable",
            "Saved", "Saved %"],
          savingsByPlant(s.savings).map(([plant, p], index, all) => {
            const gap = p.worst - p.chosen;
            const strong = index === all.length - 1 ? "b" : "span";
            return [
              `<${strong} class="mono">${escape(plant)}</${strong}>`,
              `<span class="mono num">${p.orders}</span>`,
              `<span class="mono num meta">${p.choices}</span>`,
              `<span class="mono num">${money(p.chosen)}</span>`,
              `<span class="mono num meta">${money(p.worst)}</span>`,
              `<span class="mono num gain">−${money(gap)}</span>`,
              `<span class="mono num">${percent(p.worst ? gap / p.worst : 0, 1)}</span>`,
            ];
          }))
        + drilldown("See the purchases one by one", s.savings.length, dataTable(
          ["Part", "Plant", "Offers", "Chosen", "Worst applicable", "Difference"],
          s.savings.map((i) => [
            `<span class="mono">${escape(i.sku_id)}</span>`,
            `<span class="mono">${escape(i.city_id)}</span>`,
            `<span class="mono num">${i.offers}</span>`,
            `<span class="mono num">${money(i.chosen_cost_usd)}</span>`,
            `<span class="mono num meta">${money(i.worst_cost_usd)}</span>`,
            `<span class="mono num gain">−${money(i.saving_usd)}</span>`,
          ])))) : ""),
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
      ? `<li class="pipe__link" aria-hidden="true"><span>${
        escape(typeof info.carries === "function" ? info.carries(stage) : info.carries)
      }</span></li>` : "";
    return `<li class="pipe__step">
      <button type="button" class="pipe__btn${stage.id === pipeline.current ? " pipe__btn--on" : ""}"
              data-stage="${stage.id}" aria-current="${stage.id === pipeline.current}">
        <span class="pipe__num">Step ${info.step}</span>
        <span class="pipe__name">${escape(stage.title)}</span>
        <span class="pipe__fig">${escape(info.headline(stage))}</span>
        <span class="pipe__go">${stage.id === pipeline.current
          ? "Showing this step" : "See this step →"}</span>
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

  /* Sin carga diferida. `loading="lazy"` decide si pedir la imagen segun la
     posicion del elemento respecto del viewport, y esta pantalla vive dentro de
     una vista que se muestra y se oculta con `hidden`: cuando la vista aparece,
     el navegador ya calculo que estas imagenes no hacian falta y no vuelve a
     evaluarlo. Cuatro de las cinco graficas se quedaban pedidas para siempre y
     lo que se veia en su lugar era el texto alternativo, que repite el titulo.
     Son cinco imagenes y son el contenido de la pantalla: diferirlas no ahorra
     nada que merezca ese riesgo. */
  el("stage-charts").innerHTML = (stage.charts || []).map((chart) => {
    const [title, note] = CHART_INFO[chart.key] || [chart.key, ""];
    return `<section class="card"><h3>${escape(title)}</h3>
      <p class="meta">${escape(note)}</p>
      <img src="${apiUrl(`/${chart.source}/charts/${chart.key}`)}" alt="${escape(title)}"
           decoding="async">
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

/* Las plantas de una pieza son las plantas **de esa pieza**, y no las del
   catalogo entero. De las 876 referencias solo 407 se consumen en las dos: una
   pieza que solo mueve Obregon no tiene serie en Nava, y ofrecer esa combinacion
   es ofrecer un recorrido que no existe. Antes las dos listas se llenaban por
   separado y la seleccion inicial —primera pieza, primera planta— caia en un par
   inexistente, de modo que la pantalla abria con un error en lugar de con un
   ejemplo. */
const tracerPlants = new Map();
const tracerParts = [];

function fillPlants() {
  const citySelect = el("tr-city");
  const plants = tracerPlants.get(el("tr-sku").value) || new Map();
  const previous = citySelect.value;

  citySelect.innerHTML = [...plants.entries()].sort()
    .map(([value, label]) => `<option value="${escape(value)}">${escape(label)}</option>`).join("");

  if (plants.has(previous)) citySelect.value = previous;
}

/* Solo se busca por texto, y a proposito.
 *
 * Hubo tambien filtros por decision y por criticidad, y estaban mal planteados:
 * el desplegable elige una **pieza**, pero la decision pertenece a la serie
 * —pieza y planta—. Una referencia que se compra en Nava y no se toca en
 * Obregon pasa el filtro "Buy" y despues muestra el recorrido de Obregon, que
 * dice "No action". El filtro no mentia sobre la pieza; mentia sobre lo que se
 * iba a ver, que es peor.
 *
 * Arreglarlo pedia que el filtro eligiera la serie y arrastrara el selector de
 * planta con ella, y eso son dos controles gobernando un tercero para una
 * pantalla cuyo trabajo es explicar el pipeline con un ejemplo. La busqueda por
 * codigo o descripcion resuelve el caso real —"quiero ver esta pieza"— sin
 * inventar ninguna de esas reglas.
 */
function matchingParts() {
  const search = el("tr-search").value.trim().toLowerCase();
  if (!search) return tracerParts;
  return tracerParts.filter((part) => part.label.toLowerCase().includes(search));
}

/** Rellena el desplegable con lo que sobrevive a la busqueda, conservando la
 *  seleccion si sigue estando: escribir para buscar otra cosa no tiene por que
 *  recargar el recorrido que se estaba mirando. */
function fillParts() {
  const skuSelect = el("tr-sku");
  const previous = skuSelect.value;
  const visible = matchingParts();

  skuSelect.innerHTML = visible
    .map((part) => `<option value="${escape(part.sku_id)}">${escape(part.label)}</option>`)
    .join("");
  skuSelect.disabled = !visible.length;

  el("tr-matches").textContent = visible.length === tracerParts.length
    ? `· ${count(tracerParts.length)} parts`
    : `· ${count(visible.length)} of ${count(tracerParts.length)}`;

  if (visible.some((part) => part.sku_id === previous)) {
    skuSelect.value = previous;
    return false;
  }
  return visible.length > 0;
}

function fillTracer() {
  const skuSelect = el("tr-sku");
  if (skuSelect.dataset.ready || !state.items.length) return;

  const byPart = new Map();
  state.items.forEach((item) => {
    if (!byPart.has(item.sku_id)) {
      byPart.set(item.sku_id, {
        sku_id: item.sku_id,
        label: `${item.sku_id} · ${item.description}`,
      });
    }
    if (!tracerPlants.has(item.sku_id)) tracerPlants.set(item.sku_id, new Map());
    tracerPlants.get(item.sku_id).set(item.city_id, item.city_name);
  });

  tracerParts.length = 0;
  tracerParts.push(...[...byPart.values()].sort((a, b) => a.label.localeCompare(b.label)));

  fillParts();
  fillPlants();
  skuSelect.dataset.ready = "1";
  loadTrace();
}

/** Escribir en la busqueda solo recarga el recorrido si cambio la pieza. */
function applyFilters() {
  if (fillParts()) {
    fillPlants();
    loadTrace();
  }
}

export async function loadTrace() {
  const sku = el("tr-sku").value;
  const city = el("tr-city").value;
  if (!sku || !city) return;

  await whileLoading(
    { into: "trace", key: `traza:${sku}:${city}`, message: `Walking ${sku} through the pipeline…` },
    async () => {
      try {
        el("trace").innerHTML = renderTrace(await api(
          `/pipeline/trace/${encodeURIComponent(sku)}/${encodeURIComponent(city)}`));
      } catch (error) {
        el("trace").innerHTML = `<p class="meta">${escape(error.message)}</p>`;
      }
    },
  );
}

export function initPipeline() {
  el("tr-sku").addEventListener("change", () => {
    fillPlants();
    loadTrace();
  });
  el("tr-city").addEventListener("change", loadTrace);
  el("tr-search").addEventListener("input", applyFilters);
}

export function refreshTracer() { fillTracer(); }
