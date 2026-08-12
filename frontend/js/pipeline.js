/* Modelo y pipeline: de donde sale cada numero.
 *
 * Dos piezas. Arriba el recorrido completo —limpieza, dataset, patrones,
 * modelo, optimizacion— donde cada etapa declara que entra, que sale y que hizo
 * con lo que recibio. Abajo el trazador, que recorre esas mismas cinco etapas
 * para una sola pieza en una sola planta.
 *
 * La narrativa por etapa se conserva de la version SupplyOpt porque es donde
 * esta el criterio de dominio: que un mes con un solo dia registrado se leeria
 * como caida de demanda, que la mitad de la historia es simulada, o que las
 * filas en revision no son un fallo del solver. Eso no se reescribe.
 */

import { api, apiUrl, state } from "./api.js";
import { escape } from "./format.js";

const count = (value) => Number(value || 0).toLocaleString("es-MX");
const money = (value) => Number(value || 0).toLocaleString("es-MX", { maximumFractionDigits: 0 });
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
    return `El modelo mejora un ${pct(naive, 0)} frente a repetir el último mes, pero solo `
      + `un ${pct(gain, 1)} frente al promedio móvil. Es un resultado honesto: dos tercios de `
      + `las series son planas y ahí no hay estructura que aprender. Por eso la proyección `
      + `final promedia ambos métodos en lugar de apostar todo al modelo.`;
  }
  return `El modelo mejora un ${pct(gain, 0)} frente al promedio móvil y un ${pct(naive, 0)} `
    + `frente a repetir el último mes. La proyección final combina ambos métodos.`;
}

const CHART_INFO = {
  limpieza: ["Qué se descartó y por qué", "Filas retiradas de cada fuente, agrupadas por la regla que las retiró."],
  dataset: ["La historia disponible", "Consumo mensual agregado, separando los meses observados de los simulados."],
  patrones: ["Mapa de patrones", "Cada serie situada por su variabilidad y su fuerza estacional."],
  decisiones: ["En qué acabó cada serie", "Reparto de las cuarenta combinaciones entre las cuatro decisiones."],
  ahorro: ["Qué se ahorró al elegir proveedor", "Diferencia entre la oferta elegida y la peor aplicable, por compra."],
  comparison: ["Error frente a las referencias", "El modelo contra repetir el último mes y contra el promedio móvil."],
  series: ["Proyección contra consumo real", "Mes a mes en las series de mayor volumen durante la validación."],
  scatter: ["Predicho contra observado", "Cada punto es un mes. Sobre la diagonal sobreestima; debajo, subestima."],
  errors: ["Distribución del error", "Centrado en cero indica que no compra sistemáticamente de más ni de menos."],
  importance: ["Peso de cada variable", "Cuánto empeora el error al barajar cada una."],
};

/* ---------- La narrativa de cada etapa ---------- */

const STAGE_INFO = {
  limpieza: {
    step: "0",
    carries: "fuentes limpias",
    headline: (s) => `−${count(s.discarded)} filas`,
    note: () => "Es la única etapa cuyo valor está en lo que quitó. Lo importante no es "
      + "el número de filas descartadas sino el motivo: órdenes canceladas contadas como "
      + "entregas sesgaban el plazo de entrega a la baja, y un mes con un solo día "
      + "registrado se habría leído como una caída de la demanda.",
    figures: (s) => [
      figureCard("Filas crudas", count(s.rows_before), `${s.sources.length} fuentes`),
      figureCard("Filas útiles", count(s.rows_after), "entran al dataset", "go"),
      figureCard("Descartadas", count(s.discarded), "no evidencian nada", "hold"),
      figureCard("Ajustadas", count(s.adjusted), "corregidas sin eliminar"),
    ],
    detail: (s) => s.sources.map((source) => panel(
      `${source.name} · ${count(source.rows_before)} → ${count(source.rows_after)} filas`,
      dataTable(["Regla", "Motivo", "Filas", "Efecto"],
        source.rules.filter((rule) => rule.kind !== "resultado").map((rule) => [
          escape(rule.rule),
          `<span class="meta">${escape(rule.reason)}</span>`,
          `<span class="mono num">${count(rule.rows)}</span>`,
          `<span class="badge badge--${rule.kind}">${rule.kind === "descarte" ? "descarta" : "ajusta"}</span>`,
        ]))
    )).join(""),
  },

  dataset: {
    step: "1",
    carries: "72 meses × 40 series",
    headline: (s) => `${s.months} meses · ${s.series} series`,
    note: (s) => `De las ${count(s.synthetic_rows + s.real_rows)} filas de historia, `
      + `${count(s.synthetic_rows)} son meses simulados hacia atrás. Se generaron porque `
      + `detectar estacionalidad exige al menos dos ciclos completos y el dato observado no `
      + `llegaba. Conviene decirlo antes de que alguien lo pregunte: las decisiones son `
      + `correctas dado ese dato, pero la mitad de la historia no ocurrió.`,
    figures: (s) => [
      figureCard("Meses de historia", s.months, `${s.first_month} a ${s.last_month}`),
      figureCard("Series", s.series, `${s.parts} piezas × ${s.cities} plantas`),
      figureCard("Filas simuladas", count(s.synthetic_rows), `de ${count(s.synthetic_rows + s.real_rows)}`, "hold"),
      figureCard("Proveedores", s.suppliers, `${s.offers} ofertas`),
    ],
    detail: (s) => panel("Tablas generadas", dataTable(["Tabla", "Filas"],
      s.tables.map((t) => [escape(t.name), `<span class="mono num">${count(t.rows)}</span>`]))),
  },

  patrones: {
    step: "2",
    carries: "patrón por serie",
    headline: (s) => `${Object.keys(s.counts).length} patrones`,
    note: (s) => "Se clasifica por pieza y planta, no solo por pieza: una misma refacción "
      + "puede ser estable en Nava y volátil en Obregón. Estacional exige dos condiciones a "
      + `la vez, fuerza ≥ ${s.thresholds.seasonal_strength} y efecto de mes significativo `
      + `(p < ${s.thresholds.seasonal_pvalue}), porque la fuerza por sí sola etiqueta como `
      + "estacional hasta el ruido puro.",
    figures: (s) => {
      const tones = { Estable: "go", Volatil: "hold", Estacional: "" };
      return Object.entries(s.counts)
        .map(([name, value]) => figureCard(name, value, "series", tones[name]))
        .concat(figureCard("Umbral de volatilidad", `CV > ${s.thresholds.cv_volatile}`, "σ sobre μ"));
    },
    detail: (s) => panel("Series más volátiles", dataTable(
      ["Serie", "Patrón", "CV", "Fuerza estacional", "p-valor", "Confianza"],
      s.points.slice().sort((a, b) => b.cv - a.cv).slice(0, 10).map((p) => [
        `<span class="mono">${escape(p.sku_id)} · ${escape(p.city_id)}</span>`,
        `<span class="pill">${escape(p.pattern)}</span>`,
        `<span class="mono num">${p.cv.toFixed(2)}</span>`,
        `<span class="mono num">${p.seasonal_strength.toFixed(2)}</span>`,
        `<span class="mono num">${p.seasonal_pvalue.toFixed(3)}</span>`,
        `<span class="mono num">${p.confidence.toFixed(2)}</span>`,
      ]))),
  },

  modelo: {
    step: "3",
    carries: "proyección por pieza",
    headline: (s) => (s.metrics.wmape ? `WMAPE ${pct(s.metrics.wmape)}` : "sin entrenar"),
    note: (s) => (s.metrics.wmape ? verdict(s.metrics)
      : "El modelo aún no se ha entrenado. Corre: python -m app.services.train_model"),
    figures: (s) => [
      figureCard("Error del modelo", s.metrics.wmape ? pct(s.metrics.wmape) : "—", "WMAPE en validación", "go"),
      figureCard("Sobre el último mes", pct(s.metrics.mejora_vs_ultimo_mes, 0), "referencia trivial"),
      figureCard("Sobre el promedio móvil", pct(s.metrics.mejora_vs_promedio_movil, 1), "método en producción", "hold"),
      figureCard("Sesgo", (s.metrics.bias || 0).toFixed(2), "unidades por mes"),
      figureCard("Reparto temporal", `${count(s.rows_train)} / ${count(s.rows_validation)}`, `validación ${s.validation_months}`),
    ],
    detail: (s) => panel(`Qué entra · ${s.features.length} variables`, dataTable(
      ["Familia", "Variables"],
      s.families.map((f) => [escape(f.family),
        `<span class="mono meta">${f.features.map(escape).join(", ")}</span>`])))
      + panel("Qué sale · una proyección por serie y mes", dataTable(
        ["Método", "WMAPE", "MAE", "Sesgo"],
        [["Modelo global", s.metrics.wmape, s.metrics.mae, s.metrics.bias]]
          .concat(Object.entries(s.baselines).map(([name, r]) =>
            [name.replace(/_/g, " "), r.wmape, r.mae, r.bias]))
          .map(([name, wmape, mae, bias]) => [
            escape(name),
            `<span class="mono num">${pct(wmape)}</span>`,
            `<span class="mono num">${(mae || 0).toFixed(2)}</span>`,
            `<span class="mono num">${(bias || 0).toFixed(2)}</span>`,
          ]))),
  },

  optimizacion: {
    step: "4",
    carries: "decisión y motivo",
    headline: (s) => `${s.counts.COMPRAR} compras`,
    note: (s) => "El modelo se resuelve por pieza y planta: minimiza precio por cantidad más "
      + "flete, sujeto a cubrir el faltante, no pasar del máximo de bodega, respetar el lote "
      + `mínimo del proveedor y su capacidad, y un solo proveedor por orden. Las `
      + `${s.counts.REVISAR} filas en revisión no son un fallo del solver: son casos donde el `
      + "lote mínimo supera lo que cabe en bodega, y esa tensión la decide una persona."
      + (s.budget_usd
        ? ` Al final una mochila reparte los ${money(s.budget_usd)} USD de presupuesto `
          + "maximizando el beneficio neto: lo que cuesta el quiebre que se evita menos lo que "
          + `cuesta evitarlo. Es el único paso que mira todas las piezas a la vez. Ese dinero `
          + `evita ${money(s.stockout_avoided_usd)} USD de quiebre, un retorno de `
          + `${s.stockout_return}×, y deja ${money(s.stockout_exposed_usd)} USD de riesgo sin `
          + `cubrir en ${s.counts.APLAZADO} reposiciones que sí procedían. Ampliar el `
          + `presupuesto en ${money(s.deferred_usd)} USD lo cerraría.`
        : " No hay presupuesto configurado, así que cada pieza se decide sin mirar lo que "
          + "gastan las demás."),
    figures: (s) => [
      figureCard("Comprar", s.counts.COMPRAR, `${count(s.units)} unidades`, "go"),
      figureCard("Revisar", s.counts.REVISAR, "lote mínimo excede el máximo", "hold"),
      figureCard("Aplazado", s.counts.APLAZADO || 0, `${money(s.deferred_usd)} USD sin financiar`, "stop"),
      figureCard("Inversión", `${money(s.investment_usd)} USD`,
        s.budget_usd ? `de ${money(s.budget_usd)} USD de presupuesto` : "sin límite"),
      figureCard("Quiebre evitado", `${money(s.stockout_avoided_usd)} USD`, `retorno ${s.stockout_return}×`, "go"),
    ],
    detail: (s) => panel("Por qué cada decisión", dataTable(
      ["Causa", "Decisión", "Casos", "Ejemplo"],
      s.reasons.map((r) => [
        escape(r.reason),
        `<span class="tag tag--${escape(r.decision)}">${escape(r.decision.replace("_", " "))}</span>`,
        `<span class="mono num">${r.count}</span>`,
        `<span class="meta mono">${escape(r.examples.map((e) => `${e.sku_id}·${e.city_id}`).join(", "))}</span>`,
      ])))
      + (s.savings && s.savings.length ? panel("Qué se ahorró en cada compra", dataTable(
        ["Serie", "Ofertas", "Elegida", "Peor aplicable", "Diferencia"],
        s.savings.map((i) => [
          `<span class="mono">${escape(i.sku_id)} · ${escape(i.city_id)}</span>`,
          `<span class="mono num">${i.offers}</span>`,
          `<span class="mono num">${money(i.chosen_cost_usd)}</span>`,
          `<span class="mono num meta">${money(i.worst_cost_usd)}</span>`,
          `<span class="mono num gain">−${money(i.saving_usd)}</span>`,
        ]))) : ""),
  },
};

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
    role="img" aria-label="Consumo mensual de la serie">${shade}
    ${bars}
    <path d="${line(smooth)}" class="spark__line"/></svg>
    <span class="spark__key">
      <span><i class="k-bar"></i>consumo del mes</span>
      <span><i class="k-real"></i>tendencia a 3 meses</span>
      ${boundary > 0 ? '<span><i class="k-sint"></i>tramo simulado</span>' : ""}
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

  return traceStep("1", "Historia de consumo", `
    ${sparkline(trace.history)}
    ${pairs([
      ["Meses", `${trace.history.length} (${observed} observados, ${synthetic} simulados)`],
      ["Consumo medio", `${(pattern.mean_monthly || 0).toFixed(1)} unidades/mes`],
      ["Meses sin consumo", pct(pattern.zero_ratio, 0)],
    ])}`)

    + traceStep("2", "Clasificación del patrón", pairs([
      ["Patrón", `<span class="pill">${escape(pattern.pattern || "—")}</span>`],
      ["Coeficiente de variación", (pattern.cv || 0).toFixed(2)],
      ["Fuerza estacional", `${(pattern.seasonal_strength || 0).toFixed(2)} (p ${(pattern.seasonal_pvalue || 0).toFixed(3)})`],
      ["Método recomendado", escape(pattern.recommended_model || "—")],
      ["Confianza del patrón", (pattern.confidence || 0).toFixed(2)],
    ]))

    + traceStep("3", "Qué sale del modelo", pairs([
      ["Proyección del modelo ML", `${(forecast.forecast_model || 0).toFixed(2)} unidades/mes`],
      ["Método estadístico", escape(forecast.method || "—")],
      ["Proyección final", `<strong>${(forecast.forecast_q50 || 0).toFixed(2)}</strong> unidades/mes`],
      ["Escenarios", `${(forecast.forecast_q25 || 0).toFixed(1)} a ${(forecast.forecast_q75 || 0).toFixed(1)}`],
      ["Origen de la cifra", escape(forecast.forecast_source || "—")],
      ["Confianza final", (forecast.confidence_final || 0).toFixed(2)],
    ]))

    + traceStep("4", "Cómo se compone el inventario mínimo", pairs([
      ["Plazo de reposición", `${(forecast.lead_time_days || 0).toFixed(1)} días`],
      ["Demanda durante el plazo", `${(forecast.demand_lead_time || 0).toFixed(2)} unidades`],
      ["Colchón de seguridad", `${(forecast.safety_stock || 0).toFixed(2)} unidades`],
      ["Inventario mínimo", `<strong>${decision.inventory_min}</strong> unidades`],
      ["Existencias hoy", `${decision.on_hand_qty} unidades`],
      ["Máximo de bodega", `${decision.inventory_max} unidades`],
    ]))

    + traceStep("5", "Ofertas que compitieron", trace.offers.length
      ? dataTable(["Proveedor", "Precio", "Lote mín.", "Flete", "Entrega", "Unidades", "Total"],
          trace.offers.map((offer) => [
            `${escape(offer.supplier_name)}${offer.chosen ? ' <span class="offer__tag">elegido</span>' : ""}`,
            `<span class="mono num">${(offer.unit_price_usd).toFixed(2)}</span>`,
            `<span class="mono num">${offer.moq}</span>`,
            `<span class="mono num">${money(offer.freight_cost_usd)}</span>`,
            `<span class="mono num">${offer.lead_time_days}d</span>`,
            `<span class="mono num">${offer.units}</span>`,
            `<span class="mono num">${money(offer.total_cost_usd)}</span>`,
          ]))
      : '<p class="meta">Ninguna oferta cubre esta pieza en esta planta.</p>', true)

    + traceStep("6", "Decisión", `
      <p class="trace__decision">
        <span class="tag tag--${escape(decision.decision)}">${escape(decision.decision.replace("_", " "))}</span>
        ${decision.recommended_qty ? `<strong>${decision.recommended_qty} unidades</strong>` : ""}
        ${decision.supplier_name ? `a ${escape(decision.supplier_name)}` : ""}
        ${decision.total_cost_usd ? `por ${money(decision.total_cost_usd)} USD` : ""}
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
  box.innerHTML = '<p class="meta">Recorriendo el pipeline…</p>';
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
