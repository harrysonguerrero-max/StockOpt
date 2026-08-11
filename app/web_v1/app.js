const API = "/api/v1";

const AI_PREFERENCE_KEY = "supplyopt.usarIA";

const state = {
  items: [],
  filters: null,
  openKey: null,
  useAI: localStorage.getItem(AI_PREFERENCE_KEY) !== "0",
};

const el = (id) => document.getElementById(id);
const keyOf = (item) => `${item.sku_id}|${item.city_id}`;

const money = (value) =>
  Number(value || 0).toLocaleString("es-MX", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function toast(message, isError) {
  const node = el("toast");
  node.textContent = message;
  node.classList.toggle("toast--error", Boolean(isError));
  node.hidden = false;
  clearTimeout(node.timer);
  node.timer = setTimeout(() => { node.hidden = true; }, 3600);
}

async function api(path, options) {
  const response = await fetch(API + path, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || "No se pudo completar la operación");
  }
  return payload;
}

async function load(refresh) {
  try {
    const data = await api(`/recommendations${refresh ? "?refresh=true" : ""}`);
    state.items = data.items;
    state.filters = data.filters;
    paintSummary(data.summary);
    fillFilters(data.filters);
    render();
  } catch (error) {
    el("rows").innerHTML = "";
    el("empty").hidden = false;
    el("empty").textContent = error.message;
  }
}

function paintSummary(summary) {
  el("s-pending").textContent = summary.pending_decision;
  el("s-total").textContent = `de ${summary.total} filas`;
  el("s-buy").textContent = summary.to_buy;
  el("s-units").textContent = `${summary.units} unidades`;
  el("s-review").textContent = summary.to_review;
  el("s-deferred").textContent = summary.deferred;
  el("s-deferred-usd").textContent = summary.deferred
    ? `expone ${money(summary.stockout_exposed_usd)} USD de quiebre`
    : "todo lo necesario cabe";
  el("s-none").textContent = summary.no_action;
  el("s-money").textContent = `${money(summary.investment_usd)} USD`;
  el("s-budget").textContent = summary.budget_usd
    ? `de ${money(summary.budget_usd)} USD de presupuesto`
    : "solo filas por comprar";
  el("context").textContent =
    `Refacciones industriales · ${summary.needs_review} filas marcadas para revisión humana`;
}

function fillFilters(filters) {
  const fill = (id, values, labeller) => {
    const node = el(id);
    if (node.dataset.ready) return;
    values.forEach((value) => {
      const option = document.createElement("option");
      const [key, text] = labeller(value);
      option.value = key;
      option.textContent = text;
      node.appendChild(option);
    });
    node.dataset.ready = "1";
  };

  fill("f-city", filters.cities, (c) => [c.id, c.name]);
  fill("f-decision", filters.decisions, (d) => [d, d.replace("_", " ")]);
  fill("f-state", filters.states, (s) => [s, s]);
  fill("f-crit", filters.criticalities, (c) => [c, `Criticidad ${c}`]);
}

function visibleItems() {
  const search = el("f-search").value.trim().toLowerCase();
  const city = el("f-city").value;
  const decision = el("f-decision").value;
  const workflowState = el("f-state").value;
  const criticality = el("f-crit").value;
  const onlyReview = el("f-review").checked;

  return state.items.filter((item) => {
    if (city && item.city_id !== city) return false;
    if (decision && item.decision !== decision) return false;
    if (workflowState && item.state !== workflowState) return false;
    if (criticality && item.criticality !== criticality) return false;
    if (onlyReview && item.needs_review !== 1) return false;
    if (search) {
      const haystack = `${item.sku_id} ${item.description}`.toLowerCase();
      if (!haystack.includes(search)) return false;
    }
    return true;
  });
}

function gaugeMarkup(item) {
  const g = item.gauge;
  return `
    <span class="gauge">
      <span class="gauge__track">
        <span class="gauge__fill gauge__fill--${g.zone}" style="width:${g.fill_pct}%"></span>
        <span class="gauge__min" style="left:${g.minimum_pct}%"></span>
      </span>
      <span class="gauge__read"><b>${item.on_hand_qty}</b> en bodega · mínimo ${item.inventory_min} · máximo ${item.inventory_max}</span>
    </span>`;
}

function stateClass(value) {
  return `state--${String(value).split(" ")[0]}`;
}

function rowMarkup(item) {
  const flag = item.needs_review === 1
    ? '<span class="flag" title="Requiere revisión humana">▲ REVISAR</span>' : "";
  const supplier = item.supplier_name
    ? `${item.supplier_name}<br><span class="sub mono">${item.lead_time_days} días</span>`
    : '<span class="sub">—</span>';
  const revisar = item.decision === "REVISAR";
  const aplazado = item.decision === "APLAZADO";
  const hipotetica = revisar || aplazado;
  const qty = item.recommended_qty
    ? (revisar
        ? `<span class="hypo">lote mín. ${item.recommended_qty}</span>
           <span class="hypo hypo--warn">≈${item.coverage_months} meses</span>`
        : aplazado
          ? `<span class="hypo">requiere ${item.recommended_qty}</span>
             <span class="hypo hypo--stop">sin financiar</span>`
          : item.recommended_qty)
    : "—";
  const cost = item.total_cost_usd
    ? (hipotetica ? `<span class="hypo">(${money(item.total_cost_usd)})</span>`
                  : money(item.total_cost_usd))
    : "—";

  return `
    <td>
      <span class="part">
        <span class="part__id">${item.sku_id}<span class="crit crit--${item.criticality}">${item.criticality}</span></span>
        <span class="part__name">${item.description}</span>
      </span>
    </td>
    <td>${item.city_name}<br><span class="sub mono">${item.warehouse_id}</span></td>
    <td>${gaugeMarkup(item)}</td>
    <td class="num">
      <span class="tag tag--${item.decision}">${item.decision.replace("_", " ")}</span>
      <div class="qty">${qty}</div>
    </td>
    <td>${supplier}</td>
    <td class="num mono">${cost}</td>
    <td>
      <span class="state ${stateClass(item.state)}"><span class="state__dot"></span>${item.state}</span>
      ${flag}
    </td>`;
}

function render() {
  const rows = el("rows");
  const items = visibleItems();
  rows.innerHTML = "";
  el("empty").hidden = items.length > 0;

  items.forEach((item) => {
    const key = keyOf(item);
    const tr = document.createElement("tr");
    tr.className = "row";
    tr.dataset.key = key;
    tr.tabIndex = 0;
    tr.setAttribute("aria-expanded", String(state.openKey === key));
    tr.innerHTML = rowMarkup(item);
    tr.addEventListener("click", () => toggle(key));
    tr.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        toggle(key);
      }
    });
    rows.appendChild(tr);

    if (state.openKey === key) {
      rows.appendChild(detailRow(item));
    }
  });
}

function toggle(key) {
  state.openKey = state.openKey === key ? null : key;
  render();
}

function detailRow(item) {
  const node = el("tpl-detail").content.cloneNode(true);
  const row = node.querySelector("tr");

  row.querySelector(".detail__headline").textContent = item.explanation.headline;
  const body = row.querySelector(".detail__body");
  body.textContent = item.explanation.body;
  requestExplanation(item, body);

  const list = row.querySelector(".assumptions");
  item.explanation.assumptions.forEach((text) => {
    const li = document.createElement("li");
    li.textContent = text;
    list.appendChild(li);
  });

  const kv = row.querySelector(".kv");
  const pairs = item.supplier_id
    ? [
        ["Nombre", item.supplier_name],
        ["Código", item.supplier_id],
        ["Contacto", item.contact_email || "—"],
        ["Precio unitario", `${money(item.unit_price_usd)} USD`],
        ["Flete", `${money(item.freight_cost_usd)} USD`],
        ["Entrega", `${item.lead_time_days} días (${item.lead_time_min_days}–${item.lead_time_max_days})`],
      ]
    : [["Proveedor", "No aplica para esta fila"]];

  pairs.forEach(([term, value]) => {
    const dt = document.createElement("dt");
    dt.textContent = term;
    const dd = document.createElement("dd");
    dd.textContent = value;
    kv.append(dt, dd);
  });

  row.querySelector(".actions").append(...actionControls(item, row));
  paintAlternatives(item, row);

  if (item.rejection_reason) {
    const note = document.createElement("p");
    note.className = "note";
    note.textContent = `Rechazado: ${item.rejection_reason}${item.comment ? ` — ${item.comment}` : ""}`;
    row.querySelector(".detail__side").appendChild(note);
  }

  return row;
}

function actionControls(item, row) {
  const controls = [];
  const transitions = item.next_states || [];

  transitions.forEach((target) => {
    if (target === "Rechazado") return;
    const button = document.createElement("button");
    button.type = "button";
    button.className = target === "Aprobado" ? "btn btn--go" : "btn btn--quiet";
    button.textContent = actionLabel(target);
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      submit(item, target);
    });
    controls.push(button);
  });

  if (transitions.includes("Rechazado")) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn--stop";
    button.textContent = "Rechazar";
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const panel = row.querySelector(".reject");
      panel.dataset.open = panel.dataset.open === "true" ? "false" : "true";
    });
    controls.push(button);
    row.querySelector(".detail__side").appendChild(rejectPanel(item));
  }

  if (!controls.length) {
    const done = document.createElement("p");
    done.className = "sub";
    done.textContent = "Esta orden ya está confirmada.";
    controls.push(done);
  }
  return controls;
}

function actionLabel(target) {
  if (target === "Aprobado") return "Aprobar";
  if (target === "Contactado proveedor") return "Marcar proveedor contactado";
  if (target === "Orden confirmada") return "Confirmar orden";
  if (target === "Pendiente aprobacion") return "Reabrir";
  return target;
}

function rejectPanel(item) {
  const panel = document.createElement("div");
  panel.className = "reject";
  panel.dataset.open = "false";
  panel.addEventListener("click", (event) => event.stopPropagation());

  const select = document.createElement("select");
  (state.filters.rejection_reasons || []).forEach((reason) => {
    const option = document.createElement("option");
    option.value = reason;
    option.textContent = reason;
    select.appendChild(option);
  });

  const comment = document.createElement("textarea");
  comment.placeholder = "Detalle opcional para el registro";

  const confirm = document.createElement("button");
  confirm.type = "button";
  confirm.className = "btn btn--stop";
  confirm.textContent = "Confirmar rechazo";
  confirm.addEventListener("click", () =>
    submit(item, "Rechazado", { rejection_reason: select.value, comment: comment.value })
  );

  panel.append(select, comment, confirm);
  return panel;
}

async function submit(item, newState, extra) {
  try {
    await api("/recommendations/state", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sku_id: item.sku_id,
        city_id: item.city_id,
        new_state: newState,
        ...(extra || {}),
      }),
    });
    toast(`${item.sku_id} · ${newState}`);
    await load(false);
  } catch (error) {
    toast(error.message, true);
  }
}

["f-search", "f-city", "f-decision", "f-state", "f-crit", "f-review"].forEach((id) => {
  el(id).addEventListener("input", render);
});

el("refresh").addEventListener("click", () => load(true));

load(false);

const CHART_INFO = {
  comparison: ["¿El modelo aporta algo?", "Error del modelo frente a repetir el último mes y al promedio móvil que ya estaba en uso."],
  series: ["¿Sigue la forma de la demanda?", "Proyección mes a mes en las series de mayor volumen durante la validación."],
  scatter: ["¿Dónde se equivoca?", "Cada punto es un mes. Por encima de la diagonal sobreestima, por debajo subestima."],
  errors: ["¿Está sesgado?", "Un histograma centrado en cero indica que no compra sistemáticamente de más ni de menos."],
  importance: ["¿De qué se alimenta?", "Cuánto empeora el error al barajar cada variable. Si barajarla no cambia nada, no aportaba."],
  limpieza: ["¿Qué se descartó y por qué?", "Solo las reglas que eliminan filas. Rellenar un nulo o marcar una lectura extrema no quita nada."],
  dataset: ["¿Cuánta historia es real?", "Consumo mensual de las 40 series. La zona ámbar son los meses simulados para poder detectar estacionalidad."],
  patrones: ["¿Por qué cada serie cayó en su patrón?", "Cada punto es una serie frente a los dos umbrales que deciden su etiqueta."],
  decisiones: ["¿De dónde sale cada decisión?", "Las 40 combinaciones agrupadas por la causa que las explica, no por el texto de cada fila."],
  ahorro: ["¿Qué aporta el optimizador?", "Costo de la oferta elegida contra la más cara que podía surtir el mismo caso."],
};

const count = (value) => Number(value || 0).toLocaleString("es-MX");

const pct = (value, digits) => `${((value || 0) * 100).toFixed(digits === undefined ? 1 : digits)}%`;

function escapeHtml(value) {
  const node = document.createElement("span");
  node.textContent = value === null || value === undefined ? "" : String(value);
  return node.innerHTML;
}

function figureCard(label, value, sub, tone) {
  return `<div class="strip__item">
    <span class="label">${escapeHtml(label)}</span>
    <strong class="figure${tone ? ` figure--${tone}` : ""}">${escapeHtml(value)}</strong>
    <span class="sub">${escapeHtml(sub || "")}</span>
  </div>`;
}

function dataTable(headers, rows, className) {
  const head = headers.map((h) => `<th>${escapeHtml(h)}</th>`).join("");
  const body = rows
    .map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`)
    .join("");
  return `<table class="mini ${className || ""}"><thead><tr>${head}</tr></thead>
    <tbody>${body}</tbody></table>`;
}

function panel(title, inner) {
  return `<section class="panel"><h3>${escapeHtml(title)}</h3>${inner}</section>`;
}

function verdict(metrics) {
  const gain = metrics.mejora_vs_promedio_movil || 0;
  const naive = metrics.mejora_vs_ultimo_mes || 0;
  if (gain < 0.05) {
    return `El modelo mejora un ${pct(naive, 0)} frente a repetir el último mes, pero solo un ${pct(gain, 1)} frente al promedio móvil. Es un resultado honesto: dos tercios de las series son planas y ahí no hay estructura que aprender. Por eso la proyección final promedia ambos métodos en lugar de apostar todo al modelo.`;
  }
  return `El modelo mejora un ${pct(gain, 0)} frente al promedio móvil y un ${pct(naive, 0)} frente a repetir el último mes. La proyección final combina ambos métodos para reducir la varianza.`;
}

const STAGE_INFO = {
  limpieza: {
    step: "0",
    carries: "fuentes limpias",
    headline: (s) => `−${count(s.discarded)} filas`,
    note: () =>
      "Es la única etapa cuyo valor está en lo que quitó. Lo importante no es el número de filas descartadas sino el motivo: 130 órdenes canceladas contadas como entregas sesgaban el plazo de entrega a la baja, y un mes con un solo día registrado se habría leído como una caída de la demanda.",
    figures: (s) => [
      figureCard("Filas crudas", count(s.rows_before), `${s.sources.length} fuentes`),
      figureCard("Filas útiles", count(s.rows_after), "entran al dataset", "go"),
      figureCard("Descartadas", count(s.discarded), "no evidencian nada", "hold"),
      figureCard("Ajustadas", count(s.adjusted), "corregidas sin eliminar"),
      figureCard("Columnas añadidas", count(
        s.sources.reduce((total, src) => total + Math.max(0, src.columns_after - src.columns_before), 0)
      ), "derivadas en la limpieza"),
    ],
    detail: (s) => s.sources.map((source) => panel(
      `${source.name} · ${count(source.rows_before)} → ${count(source.rows_after)} filas`,
      dataTable(
        ["Regla", "Motivo", "Filas", "Efecto"],
        source.rules.filter((rule) => rule.kind !== "resultado").map((rule) => [
          escapeHtml(rule.rule),
          `<span class="sub">${escapeHtml(rule.reason)}</span>`,
          `<span class="mono num">${count(rule.rows)}</span>`,
          `<span class="badge badge--${rule.kind}">${rule.kind === "descarte" ? "descarta" : "ajusta"}</span>`,
        ])
      )
    )).join(""),
  },

  dataset: {
    step: "1",
    carries: "72 meses × 40 series",
    headline: (s) => `${s.months} meses · ${s.series} series`,
    note: (s) =>
      `De las ${count(s.synthetic_rows + s.real_rows)} filas de historia, ${count(s.synthetic_rows)} son meses simulados hacia atrás. Se generaron porque detectar estacionalidad exige al menos dos ciclos completos y el dato observado no llegaba. Conviene decirlo antes de que alguien lo pregunte: las decisiones son correctas dado ese dato, pero la mitad de la historia no ocurrió.`,
    figures: (s) => [
      figureCard("Meses de historia", s.months, `${s.first_month} a ${s.last_month}`),
      figureCard("Series", s.series, `${s.parts} piezas × ${s.cities} plantas`),
      figureCard("Filas simuladas", count(s.synthetic_rows), `de ${count(s.synthetic_rows + s.real_rows)}`, "hold"),
      figureCard("Proveedores", s.suppliers, `${s.offers} ofertas`),
      figureCard("Tablas", s.tables.length, "relacionadas y validadas"),
    ],
    detail: (s) => panel("Tablas generadas", dataTable(
      ["Tabla", "Filas"],
      s.tables.map((table) => [
        escapeHtml(table.name),
        `<span class="mono num">${count(table.rows)}</span>`,
      ])
    )),
  },

  patrones: {
    step: "2",
    carries: "patrón por serie",
    headline: (s) => `${Object.keys(s.counts).length} patrones`,
    note: (s) =>
      `Se clasifica por pieza y planta, no solo por pieza: una misma refacción puede ser estable en Nava y volátil en Obregón. Estacional exige dos condiciones a la vez, fuerza ≥ ${s.thresholds.seasonal_strength} y efecto de mes significativo (p < ${s.thresholds.seasonal_pvalue}), porque la fuerza por sí sola etiqueta como estacional hasta el ruido puro.`,
    figures: (s) => {
      const tones = { Estable: "go", "Volatil": "hold", Estacional: "" };
      return Object.entries(s.counts)
        .map(([name, value]) => figureCard(name, value, "series", tones[name]))
        .concat(figureCard("Umbral de volatilidad", `CV > ${s.thresholds.cv_volatile}`, "σ sobre μ"));
    },
    detail: (s) => panel("Series más volátiles y estacionales", dataTable(
      ["Serie", "Patrón", "CV", "Fuerza estacional", "p-valor", "Confianza"],
      s.points
        .slice()
        .sort((a, b) => b.cv - a.cv)
        .slice(0, 10)
        .map((point) => [
          `<span class="mono">${escapeHtml(point.sku_id)} · ${escapeHtml(point.city_id)}</span>`,
          `<span class="tag tag--soft">${escapeHtml(point.pattern)}</span>`,
          `<span class="mono num">${point.cv.toFixed(2)}</span>`,
          `<span class="mono num">${point.seasonal_strength.toFixed(2)}</span>`,
          `<span class="mono num">${point.seasonal_pvalue.toFixed(3)}</span>`,
          `<span class="mono num">${point.confidence.toFixed(2)}</span>`,
        ])
    )),
  },

  modelo: {
    step: "3",
    carries: "proyección por pieza",
    headline: (s) => (s.metrics.wmape ? `WMAPE ${pct(s.metrics.wmape)}` : "sin entrenar"),
    note: (s) => (s.metrics.wmape ? verdict(s.metrics)
      : "El modelo aún no se ha entrenado. Corre: python -m app.services.train_model"),
    figures: (s) => [
      figureCard("Error del modelo", s.metrics.wmape ? pct(s.metrics.wmape) : "—", "WMAPE en validación", "go"),
      figureCard("Mejora vs. último mes", pct(s.metrics.mejora_vs_ultimo_mes, 0), "referencia trivial"),
      figureCard("Mejora vs. promedio móvil", pct(s.metrics.mejora_vs_promedio_movil, 1), "método en producción", "hold"),
      figureCard("Sesgo", (s.metrics.bias || 0).toFixed(2), "unidades por mes"),
      figureCard("Reparto temporal", `${count(s.rows_train)} / ${count(s.rows_validation)}`, `validación ${s.validation_months}`),
    ],
    detail: (s) => panel(`Qué entra · ${s.features.length} variables`, dataTable(
      ["Familia", "Variables"],
      s.families.map((family) => [
        escapeHtml(family.family),
        `<span class="mono sub">${family.features.map(escapeHtml).join(", ")}</span>`,
      ])
    )) + panel("Qué sale · una proyección por serie y mes", dataTable(
      ["Método", "WMAPE", "MAE", "Sesgo"],
      [["Modelo global", s.metrics.wmape, s.metrics.mae, s.metrics.bias]]
        .concat(Object.entries(s.baselines).map(([name, reference]) =>
          [name.replace(/_/g, " "), reference.wmape, reference.mae, reference.bias]))
        .map(([name, wmape, mae, bias]) => [
          escapeHtml(name),
          `<span class="mono num">${pct(wmape)}</span>`,
          `<span class="mono num">${(mae || 0).toFixed(2)}</span>`,
          `<span class="mono num">${(bias || 0).toFixed(2)}</span>`,
        ])
    )),
  },

  optimizacion: {
    step: "4",
    carries: "decisión y motivo",
    headline: (s) => `${s.counts.COMPRAR} compras`,
    note: (s) =>
      `El modelo se resuelve por pieza y planta: minimiza precio por cantidad más flete, sujeto a cubrir el faltante, no pasar del máximo de bodega, respetar el lote mínimo del proveedor y su capacidad, y un solo proveedor por orden. Las ${s.counts.REVISAR} filas en revisión no son un fallo del solver: son casos donde el lote mínimo supera lo que cabe en bodega, y esa tensión la decide una persona.` +
      (s.budget_usd
        ? ` Al final una mochila reparte los ${money(s.budget_usd)} USD de presupuesto maximizando el beneficio neto: lo que cuesta el quiebre que se evita menos lo que cuesta evitarlo. Es el único paso que mira todas las piezas a la vez. Ese dinero evita ${money(s.stockout_avoided_usd)} USD de quiebre, un retorno de ${s.stockout_return}×, y deja ${money(s.stockout_exposed_usd)} USD de riesgo sin cubrir en ${s.counts.APLAZADO} reposiciones que sí procedían. Ampliar el presupuesto en ${money(s.deferred_usd)} USD lo cerraría.`
        : " No hay presupuesto configurado, así que cada pieza se decide sin mirar lo que gastan las demás."),
    figures: (s) => [
      figureCard("Comprar", s.counts.COMPRAR, `${count(s.units)} unidades`, "go"),
      figureCard("Revisar", s.counts.REVISAR, "lote mínimo excede el máximo", "hold"),
      figureCard("Aplazado", s.counts.APLAZADO, `${money(s.deferred_usd)} USD sin financiar`, "stop"),
      figureCard("Inversión", `${money(s.investment_usd)} USD`,
        s.budget_usd ? `de ${money(s.budget_usd)} USD de presupuesto` : "sin límite"),
      figureCard("Quiebre evitado", `${money(s.stockout_avoided_usd)} USD`,
        `retorno ${s.stockout_return}×`, "go"),
    ],
    detail: (s) => panel("Por qué cada decisión", dataTable(
      ["Causa", "Decisión", "Casos", "Ejemplo"],
      s.reasons.map((reason) => [
        escapeHtml(reason.reason),
        `<span class="tag tag--${escapeHtml(reason.decision)}">${escapeHtml(reason.decision.replace("_", " "))}</span>`,
        `<span class="mono num">${reason.count}</span>`,
        `<span class="sub mono">${escapeHtml(reason.examples.map((e) => `${e.sku_id}·${e.city_id}`).join(", "))}</span>`,
      ])
    )) + (s.savings.length ? panel("Qué se ahorró en cada compra", dataTable(
      ["Serie", "Ofertas", "Elegida", "Peor aplicable", "Diferencia"],
      s.savings.map((item) => [
        `<span class="mono">${escapeHtml(item.sku_id)} · ${escapeHtml(item.city_id)}</span>`,
        `<span class="mono num">${item.offers}</span>`,
        `<span class="mono num">${money(item.chosen_cost_usd)}</span>`,
        `<span class="mono num sub">${money(item.worst_cost_usd)}</span>`,
        `<span class="mono num gain">−${money(item.saving_usd)}</span>`,
      ])
    )) : ""),
  },
};

const pipeline = { stages: [], current: null };

function paintFlow() {
  const track = el("flow");
  track.innerHTML = pipeline.stages.map((stage, index) => {
    const info = STAGE_INFO[stage.id];
    const link = index < pipeline.stages.length - 1
      ? `<li class="flow__link" aria-hidden="true"><span>${escapeHtml(info.carries)}</span></li>`
      : "";
    return `<li class="flow__step">
      <button type="button" class="flow__btn${stage.id === pipeline.current ? " flow__btn--on" : ""}"
              data-stage="${stage.id}" aria-current="${stage.id === pipeline.current}">
        <span class="flow__num">${info.step}</span>
        <span class="flow__name">${escapeHtml(stage.title)}</span>
        <span class="flow__fig">${escapeHtml(info.headline(stage))}</span>
      </button>
    </li>${link}`;
  }).join("");

  track.querySelectorAll(".flow__btn").forEach((button) => {
    button.addEventListener("click", () => selectStage(button.dataset.stage));
  });
}

function selectStage(id) {
  const stage = pipeline.stages.find((item) => item.id === id);
  if (!stage) return;
  pipeline.current = id;
  const info = STAGE_INFO[id];

  el("stage-title").textContent = stage.title;
  el("stage-in").textContent = stage.input;
  el("stage-out").textContent = stage.output;
  el("stage-figures").innerHTML = info.figures(stage).join("");
  el("stage-note").textContent = info.note(stage);
  el("stage-detail").innerHTML = info.detail(stage);

  el("stage-charts").innerHTML = stage.charts.map((chart) => {
    const [title, note] = CHART_INFO[chart.key] || [chart.key, ""];
    return `<section class="card">
      <h2>${escapeHtml(title)}</h2><p>${escapeHtml(note)}</p>
      <img src="${API}/${chart.source}/charts/${chart.key}" alt="${escapeHtml(title)}" loading="lazy">
    </section>`;
  }).join("");

  paintFlow();
}

async function loadPipeline() {
  if (pipeline.stages.length) return;
  try {
    const data = await api("/pipeline/stages");
    pipeline.stages = data.stages;
    pipeline.current = data.stages[0].id;
    paintFlow();
    selectStage(pipeline.current);
    fillTracer();
  } catch (error) {
    el("stage-note").textContent = error.message;
  }
}

function sparkline(history) {
  const values = history.map((point) => point.qty_issued);
  const top = Math.max(...values, 1);
  const width = 640;
  const height = 64;
  const step = width / Math.max(values.length - 1, 1);

  const path = values
    .map((value, index) =>
      `${index ? "L" : "M"}${(index * step).toFixed(1)},${(height - (value / top) * height).toFixed(1)}`)
    .join(" ");

  const boundary = history.findIndex((point) => !point.is_synthetic);
  const shade = boundary > 0
    ? `<rect x="0" y="0" width="${(boundary * step).toFixed(1)}" height="${height}" class="spark__sim"/>`
    : "";

  return `<svg class="spark" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none"
    role="img" aria-label="Consumo mensual de la serie">${shade}
    <path d="${path}" class="spark__line"/></svg>`;
}

function traceStep(step, title, inner, wide) {
  return `<section class="trace__step${wide ? " trace__step--wide" : ""}">
    <header><span class="trace__num">${escapeHtml(step)}</span>
    <h3>${escapeHtml(title)}</h3></header>${inner}</section>`;
}

function pairs(entries) {
  return `<dl class="kv kv--wide">${entries
    .map(([term, value]) => `<dt>${escapeHtml(term)}</dt><dd>${value}</dd>`)
    .join("")}</dl>`;
}

function renderTrace(trace) {
  const forecast = trace.forecast || {};
  const pattern = trace.pattern || {};
  const decision = trace.decision;
  const synthetic = trace.history.filter((point) => point.is_synthetic).length;
  const observed = trace.history.length - synthetic;

  const history = traceStep("1", "Historia de consumo", `
    ${sparkline(trace.history)}
    ${pairs([
      ["Meses", `${trace.history.length} (${observed} observados, ${synthetic} simulados)`],
      ["Consumo medio", `${(pattern.mean_monthly || 0).toFixed(1)} unidades/mes`],
      ["Meses sin consumo", pct(pattern.zero_ratio, 0)],
    ])}`);

  const patternStep = traceStep("2", "Clasificación del patrón", pairs([
    ["Patrón", `<span class="tag tag--soft">${escapeHtml(pattern.pattern || "—")}</span>`],
    ["Coeficiente de variación", (pattern.cv || 0).toFixed(2)],
    ["Fuerza estacional", `${(pattern.seasonal_strength || 0).toFixed(2)} (p ${(pattern.seasonal_pvalue || 0).toFixed(3)})`],
    ["Método recomendado", escapeHtml(pattern.recommended_model || "—")],
    ["Confianza del patrón", (pattern.confidence || 0).toFixed(2)],
  ]));

  const model = traceStep("3", "Qué sale del modelo", pairs([
    ["Proyección del modelo ML", `${(forecast.forecast_model || 0).toFixed(2)} unidades/mes`],
    ["Método estadístico", escapeHtml(forecast.method || "—")],
    ["Proyección final", `<strong>${(forecast.forecast_q50 || 0).toFixed(2)}</strong> unidades/mes`],
    ["Escenarios", `${(forecast.forecast_q25 || 0).toFixed(1)} a ${(forecast.forecast_q75 || 0).toFixed(1)}`],
    ["Origen de la cifra", escapeHtml(forecast.forecast_source || "—")],
    ["Confianza final", (forecast.confidence_final || 0).toFixed(2)],
  ]));

  const policy = traceStep("4", "Cómo se compone el inventario mínimo", pairs([
    ["Plazo de reposición", `${(forecast.lead_time_days || 0).toFixed(1)} días`],
    ["Demanda durante el plazo", `${(forecast.demand_lead_time || 0).toFixed(2)} unidades`],
    ["Colchón de seguridad", `${(forecast.safety_stock || 0).toFixed(2)} unidades`],
    ["Inventario mínimo", `<strong>${decision.inventory_min}</strong> unidades`],
    ["Existencias hoy", `${decision.on_hand_qty} unidades`],
    ["Máximo de bodega", `${decision.inventory_max} unidades`],
  ]));

  const offers = traceStep("5", "Ofertas que compitieron", trace.offers.length
    ? dataTable(
        ["Proveedor", "Precio", "Lote mín.", "Flete", "Entrega", "Unidades", "Total"],
        trace.offers.map((offer) => [
          `${escapeHtml(offer.supplier_name)}${offer.chosen ? ' <span class="alts__tag">elegido</span>' : ""}`,
          `<span class="mono num">${money(offer.unit_price_usd)}</span>`,
          `<span class="mono num">${offer.moq}</span>`,
          `<span class="mono num">${money(offer.freight_cost_usd)}</span>`,
          `<span class="mono num">${offer.lead_time_days}d</span>`,
          `<span class="mono num">${offer.units}</span>`,
          `<span class="mono num">${money(offer.total_cost_usd)}</span>`,
        ])
      )
    : '<p class="sub">Ninguna oferta cubre esta pieza en esta planta.</p>', true);

  const outcome = traceStep("6", "Decisión", `
    <p class="trace__decision">
      <span class="tag tag--${escapeHtml(decision.decision)}">${escapeHtml(decision.decision.replace("_", " "))}</span>
      ${decision.recommended_qty ? `<strong>${decision.recommended_qty} unidades</strong>` : ""}
      ${decision.supplier_name ? `a ${escapeHtml(decision.supplier_name)}` : ""}
      ${decision.total_cost_usd ? `por ${money(decision.total_cost_usd)} USD` : ""}
    </p>
    <p class="sub">${escapeHtml(decision.reason)}</p>`);

  return history + patternStep + model + policy + offers + outcome;
}

async function fillTracer() {
  const skuSelect = el("tr-sku");
  const citySelect = el("tr-city");
  if (skuSelect.dataset.ready) return;
  if (!state.items.length) await load(false);
  if (!state.items.length) return;

  const parts = new Map();
  const cities = new Map();
  state.items.forEach((item) => {
    parts.set(item.sku_id, `${item.sku_id} · ${item.description}`);
    cities.set(item.city_id, item.city_name);
  });

  const fill = (node, entries) => {
    node.innerHTML = entries
      .map(([value, label]) => `<option value="${escapeHtml(value)}">${escapeHtml(label)}</option>`)
      .join("");
  };

  fill(skuSelect, [...parts.entries()].sort());
  fill(citySelect, [...cities.entries()].sort());
  skuSelect.dataset.ready = "1";
  loadTrace();
}

async function loadTrace() {
  const sku = el("tr-sku").value;
  const city = el("tr-city").value;
  if (!sku || !city) return;

  const box = el("trace");
  try {
    const trace = await api(
      `/pipeline/trace/${encodeURIComponent(sku)}/${encodeURIComponent(city)}`
    );
    box.innerHTML = renderTrace(trace);
  } catch (error) {
    box.innerHTML = `<p class="sub">${escapeHtml(error.message)}</p>`;
  }
}

["tr-sku", "tr-city"].forEach((id) => {
  el(id).addEventListener("change", loadTrace);
});

const explorer = { catalog: [], table: null, page: 0, size: 50 };

function paintTableList() {
  const stages = [];
  explorer.catalog.forEach((table) => {
    const group = stages.find((item) => item.stage === table.stage);
    if (group) group.tables.push(table);
    else stages.push({ stage: table.stage, tables: [table] });
  });

  el("table-list").innerHTML = stages.map((group) => `
    <li class="tablelist__group">
      <span class="label">${escapeHtml(group.stage)}</span>
      <ul>${group.tables.map((table) => `
        <li>
          <button type="button" class="tablelist__btn${table.name === explorer.table?.name ? " tablelist__btn--on" : ""}"
                  data-table="${escapeHtml(table.name)}" ${table.available ? "" : "disabled"}>
            <span>${escapeHtml(table.title)}</span>
            <span class="sub mono">${table.available ? `${count(table.row_count)} filas` : "sin generar"}</span>
          </button>
        </li>`).join("")}</ul>
    </li>`).join("");

  el("table-list").querySelectorAll(".tablelist__btn").forEach((button) => {
    button.addEventListener("click", () => openTable(button.dataset.table));
  });
}

async function openTable(name) {
  try {
    explorer.table = await api(`/data/tables/${name}`);
    explorer.page = 0;
    el("t-search").value = "";
    el("t-title").textContent = explorer.table.title;
    el("t-summary").textContent = explorer.table.summary;
    el("t-download").href = `${API}/data/files/${name}`;
    el("t-notes").innerHTML = explorer.table.notes
      .map((note) => `<p class="note">${escapeHtml(note)}</p>`).join("");
    paintTableList();
    paintGrid();
  } catch (error) {
    toast(error.message, true);
  }
}

function visibleRows() {
  const search = el("t-search").value.trim().toLowerCase();
  if (!search) return explorer.table.rows;
  return explorer.table.rows.filter((row) =>
    row.some((cell) => String(cell ?? "").toLowerCase().includes(search)));
}

function paintGrid() {
  const table = explorer.table;
  if (!table) return;

  el("t-head").innerHTML = `<tr>${table.columns.map((column) => `
    <th title="${escapeHtml(column.description || column.name)}">
      ${escapeHtml(column.name)}
      <span class="grid__unit">${escapeHtml(column.unit && column.unit !== "-" ? column.unit : column.type)}</span>
    </th>`).join("")}</tr>`;

  const rows = visibleRows();
  const pages = Math.max(1, Math.ceil(rows.length / explorer.size));
  explorer.page = Math.min(explorer.page, pages - 1);
  const start = explorer.page * explorer.size;
  const slice = rows.slice(start, start + explorer.size);

  el("t-body").innerHTML = slice.map((row) => `<tr>${row.map((cell) => `
    <td class="${typeof cell === "number" ? "num mono" : ""}">${escapeHtml(cell ?? "")}</td>`).join("")}</tr>`).join("");

  el("t-count").textContent = rows.length === table.rows.length
    ? `${count(table.rows.length)} filas · ${table.columns.length} columnas`
    : `${count(rows.length)} de ${count(table.rows.length)} filas`;
  el("t-page").textContent = `${explorer.page + 1} / ${pages}`;
  el("t-prev").disabled = explorer.page === 0;
  el("t-next").disabled = explorer.page >= pages - 1;
}

async function loadCatalog() {
  if (explorer.catalog.length) return;
  try {
    const data = await api("/data/tables");
    explorer.catalog = data.tables;
    paintTableList();
    const first = explorer.catalog.find((table) => table.available);
    if (first) openTable(first.name);
  } catch (error) {
    el("t-summary").textContent = error.message;
  }
}

el("t-search").addEventListener("input", () => {
  explorer.page = 0;
  paintGrid();
});
el("t-prev").addEventListener("click", () => {
  explorer.page -= 1;
  paintGrid();
});
el("t-next").addEventListener("click", () => {
  explorer.page += 1;
  paintGrid();
});

const VIEWS = { queue: "view-queue", data: "view-data", model: "view-model" };

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((other) =>
      other.classList.toggle("tab--on", other === tab));
    Object.entries(VIEWS).forEach(([view, id]) => {
      el(id).hidden = view !== tab.dataset.view;
    });
    if (tab.dataset.view === "model") loadPipeline();
    if (tab.dataset.view === "data") loadCatalog();
  });
});

async function requestExplanation(item, target) {
  if (!state.useAI) return;
  if (item.explanation.source === "gemini" || item.explanationPending) return;
  if (item.explanationTried) return;

  item.explanationPending = true;
  const original = target.textContent;

  const status = document.createElement("span");
  status.className = "writing";
  status.textContent = "Redactando con el modelo";
  target.after(status);

  try {
    const fresh = await api(
      `/recommendations/${encodeURIComponent(item.sku_id)}/${encodeURIComponent(item.city_id)}/explanation`
    );
    item.explanation = fresh;
    item.explanationTried = true;
    if (target.isConnected) {
      target.textContent = fresh.body || original;
      if (fresh.source === "gemini") {
        status.className = "writing writing--done";
        status.textContent = "Redactado por el modelo";
      } else {
        status.remove();
      }
    }
  } catch (error) {
    item.explanationTried = true;
    if (status.isConnected) status.remove();
  } finally {
    item.explanationPending = false;
  }
}

function paintAlternatives(item, row) {
  const alternatives = item.alternatives || [];
  if (alternatives.length < 2) return;

  const wrap = row.querySelector(".alts-wrap");
  const body = row.querySelector(".alts tbody");
  wrap.hidden = false;

  alternatives.forEach((offer) => {
    const tr = document.createElement("tr");
    if (offer.chosen) tr.className = "alts__chosen";
    tr.innerHTML = `
      <td>${offer.supplier_name}${offer.chosen ? ' <span class="alts__tag">elegido</span>' : ""}</td>
      <td class="num mono">${money(offer.unit_price_usd)}</td>
      <td class="num mono">${offer.moq}</td>
      <td class="num mono">${offer.lead_time_days}d</td>
      <td class="num mono">${money(offer.total_cost_usd)}</td>`;
    body.appendChild(tr);
  });

  const head = document.createElement("tr");
  head.className = "alts__head";
  head.innerHTML = `<td>Proveedor</td><td class="num">Precio</td>
    <td class="num">MOQ</td><td class="num">Entrega</td><td class="num">Total</td>`;
  body.prepend(head);
}

function paintToggle() {
  const button = el("ai-toggle");
  button.setAttribute("aria-checked", String(state.useAI));
  button.querySelector(".toggle__text").textContent =
    state.useAI ? "Redacción con IA" : "Redacción sin IA";
  button.title = state.useAI
    ? "El modelo de lenguaje reescribe la justificación al abrir una fila"
    : "Se usa la justificación generada por plantilla, sin llamar al modelo";
}

el("ai-toggle").addEventListener("click", () => {
  state.useAI = !state.useAI;
  localStorage.setItem(AI_PREFERENCE_KEY, state.useAI ? "1" : "0");
  paintToggle();
  state.items.forEach((item) => {
    item.explanationTried = false;
  });
  toast(state.useAI ? "Redacción con IA activada" : "Redacción con IA desactivada");
  render();
});

paintToggle();
