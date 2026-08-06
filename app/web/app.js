const API = "/api/v1";

const state = {
  items: [],
  filters: null,
  openKey: null,
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
  el("s-none").textContent = summary.no_action;
  el("s-money").textContent = `${money(summary.investment_usd)} USD`;
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
  const qty = item.recommended_qty ? item.recommended_qty : "—";
  const cost = item.total_cost_usd ? money(item.total_cost_usd) : "—";

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
      <div class="mono" style="margin-top:4px">${qty}</div>
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
};

function verdict(data) {
  const gain = data.metrics.mejora_vs_promedio_movil || 0;
  const naive = data.metrics.mejora_vs_ultimo_mes || 0;
  if (gain < 0.05) {
    return `El modelo mejora un ${(naive * 100).toFixed(0)}% frente a repetir el último mes, pero solo un ${(gain * 100).toFixed(1)}% frente al promedio móvil. Es un resultado honesto: dos tercios de las series son planas y ahí no hay estructura que aprender. Por eso la proyección final promedia ambos métodos en lugar de apostar todo al modelo.`;
  }
  return `El modelo mejora un ${(gain * 100).toFixed(0)}% frente al promedio móvil y un ${(naive * 100).toFixed(0)}% frente a repetir el último mes. La proyección final combina ambos métodos para reducir la varianza.`;
}

async function loadModel() {
  const box = el("charts");
  try {
    const data = await api("/training/metrics");
    el("m-wmape").textContent = `${(data.metrics.wmape * 100).toFixed(1)}%`;
    el("m-naive").textContent = `${((data.metrics.mejora_vs_ultimo_mes || 0) * 100).toFixed(0)}%`;
    el("m-ma").textContent = `${((data.metrics.mejora_vs_promedio_movil || 0) * 100).toFixed(1)}%`;
    el("m-bias").textContent = data.metrics.bias.toFixed(2);
    el("m-series").textContent = data.n_series;
    el("m-split").textContent = `validación ${data.validation_months}`;
    el("m-verdict").textContent = verdict(data);

    box.className = "charts";
    box.innerHTML = "";
    ["comparison", "series", "scatter", "errors", "importance"].forEach((name, index) => {
      const [title, note] = CHART_INFO[name];
      const card = document.createElement("section");
      card.className = "card";
      card.innerHTML = `<h2>${title}</h2><p>${note}</p>
        <img src="${API}/training/charts/${name}" alt="${title}" loading="lazy">`;
      if (index >= 2) card.dataset.pair = "1";
      box.appendChild(card);
    });
  } catch (error) {
    el("m-verdict").textContent = error.message;
    box.innerHTML = "";
  }
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("tab--on", t === tab));
    const showModel = tab.dataset.view === "model";
    el("view-queue").hidden = showModel;
    el("view-model").hidden = !showModel;
    if (showModel && !el("charts").children.length) loadModel();
  });
});

async function requestExplanation(item, target) {
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
