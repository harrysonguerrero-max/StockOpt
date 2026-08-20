/* Todas las piezas: la tabla leida.
 *
 * Es el punto medio entre el turno y el crudo. El turno esconde detalle a
 * proposito para que se vea por donde empezar; el crudo lo enseña entero sin
 * tocarlo. Aqui el dato viene traducido a lo que significa —el medidor en vez
 * de tres numeros, la confianza en tramos, el estado en la palabra que usa una
 * persona— y ordenado por cualquier columna, que es para lo que sirve una tabla
 * y no una lista de tarjetas.
 *
 * El pie recalcula con el filtro puesto: es lo que la convierte en una consulta
 * en lugar de un volcado.
 */

import { state } from "./api.js";
import {
  decimal, decisionWord, escape, leadTime, pattern, stateShort, units, usd,
} from "./format.js";
import { mountFilters } from "./filtros.js";
import { byUrgency, gauge, semaphore } from "./ui.js";
import { glyph } from "./glyphs.js";

const el = (id) => document.getElementById(id);

const OPEN_DECISIONS = ["ESCALAR", "REVISAR", "APLAZADO"];

const DECISION_ORDER = { ESCALAR: 0, REVISAR: 1, APLAZADO: 2, COMPRAR: 3, NO_COMPRAR: 4 };
const STATE_ORDER = {
  "Pendiente aprobacion": 0, "Aprobado": 1, "Contactado proveedor": 2,
  "Orden confirmada": 3, "Rechazado": 4,
};

const COLUMNS = [
  {
    id: "pieza", label: "Part", by: (i) => i.sku_id,
    cell: (i) => `<span class="cell-part">
        <span class="cell-part__glyph" title="${escape(i.category || "")}">${
          glyph(i.category, { size: 26 })}</span>
        <span>
          <span class="case__sku">${escape(i.sku_id)}</span>
          <span class="crit crit--${i.criticality}" title="Criticality ${i.criticality}">${i.criticality}</span>
          <span class="meta cell-part__name">${escape(i.description)}</span>
        </span>
      </span>`,
  },
  {
    id: "planta", label: "Plant", by: (i) => i.city_id,
    cell: (i) => `<span class="plantchip" title="${escape(i.city_name)}">${escape(i.city_id)}</span>
      <div class="meta">${escape(i.warehouse_id)}</div>`,
  },
  {
    // Ordena por lo que le falta al stock respecto de su propio minimo, no por
    // el valor absoluto: 36 unidades sobre un minimo de 51 aprieta mas que 3
    // sobre un minimo de 2, y el numero suelto no lo dice.
    id: "stock", label: "Stock", cls: "col-gauge",
    by: (i) => (i.on_hand_qty - i.inventory_min) / Math.max(i.inventory_min, 1),
    cell: (i) => gauge(i),
  },
  {
    id: "trust", label: "Confidence", by: (i) => i.confidence,
    cell: (i) => `${trustBars(i.confidence)}<div class="meta">${pattern(i.pattern)}</div>`,
  },
  {
    id: "decision", label: "Decision", by: (i) => DECISION_ORDER[i.decision] ?? 9,
    cell: (i) => `<span class="tag tag--${i.decision}">
        <i class="tag__dot tag__dot--${semaphore(i).level}"></i>${decisionWord(i.decision)}</span>
      ${i.needs_review === 1 ? '<span class="flagreview">needs review</span>' : ""}`,
  },
  {
    id: "cantidad", label: "Quantity", num: true, by: (i) => i.recommended_qty || 0,
    cell: (i) => (i.recommended_qty
      ? `<span class="mono">${units(i.recommended_qty)}</span>${
          i.decision === "REVISAR" ? '<div class="meta">minimum lot</div>' : ""}`
      : "—"),
  },
  {
    id: "proveedor", label: "Supplier", by: (i) => i.supplier_name || "",
    cell: (i) => (i.supplier_name
      ? `${escape(i.supplier_name)}<div class="meta">${leadTime(i.lead_time_days)}</div>`
      : '<span class="meta">—</span>'),
  },
  {
    id: "costo", label: "Cost USD", num: true, by: (i) => i.total_cost_usd || 0,
    cell: (i) => (i.total_cost_usd
      ? `<span class="mono">${usd(i.total_cost_usd)}</span>${
          i.decision === "REVISAR" ? '<div class="meta">if accepted</div>' : ""}`
      : "—"),
  },
  {
    id: "estado", label: "Status", by: (i) => STATE_ORDER[i.state] ?? 9,
    cell: (i) => `<span class="statedot statedot--${String(i.state).split(" ")[0]}">${
      stateShort(i.state)}</span>`,
  },
];

const sort = { key: "decision", dir: 1 };
let filters = null;
let category = null;
let onOpenCase = () => {};

/* Se entra por familia y no por codigo. Veinte piezas caben en una lista, pero
   la pregunta real casi nunca es "que pasa con MRO-30012" sino "como estan las
   correas". Nueve familias es un primer corte que se abarca de un vistazo, y el
   dibujo llega antes que el nombre. */
function paintCategories() {
  const host = el("cats");
  const groups = new Map();
  state.items.forEach((item) => {
    const key = item.category || "No family";
    const g = groups.get(key) || { n: 0, open: 0 };
    g.n += 1;
    if (OPEN_DECISIONS.includes(item.decision)) g.open += 1;
    groups.set(key, g);
  });

  const chip = (key, label, mark, data) => `
    <button type="button" class="cat${category === key ? " cat--on" : ""}"
            data-cat="${key === null ? "" : escape(key)}">
      <span class="cat__glyph">${mark}</span>
      <span class="cat__name">${escape(label)}</span>
      <span class="cat__n">${data.n}${
        data.open ? ` · <b class="cat__open">${data.open}</b>` : ""}</span>
    </button>`;

  const total = { n: state.items.length,
    open: state.items.filter((i) => OPEN_DECISIONS.includes(i.decision)).length };

  host.innerHTML = chip(null, "All", glyph(null, { size: 26 }), total)
    + [...groups.entries()].sort().map(([key, data]) =>
      chip(key, key, glyph(key, { size: 26 }), data)).join("");

  host.querySelectorAll("[data-cat]").forEach((button) => {
    button.addEventListener("click", () => {
      category = button.dataset.cat || null;
      paintCategories();
      renderTable();
    });
  });
}

export function setTableListener(callback) { onOpenCase = callback; }

export function initTable() {
  filters = mountFilters("filters-tabla", "t", renderTable);
  el("export-tabla").addEventListener("click", exportFiltered);
  paintHead();
}

export function fillTableFilters() {
  filters.fill();
  paintCategories();
}

function visibleItems() {
  const column = COLUMNS.find((c) => c.id === sort.key);
  const inCategory = (i) => !category || (i.category || "No family") === category;
  // La urgencia rompe los empates en cualquier orden: dentro del mismo
  // proveedor o la misma decision, delante lo que mas aprieta.
  return filters.apply().filter(inCategory).sort((a, b) => {
    const left = column.by(a);
    const right = column.by(b);
    const cmp = typeof left === "string" ? left.localeCompare(right) : left - right;
    return cmp * sort.dir || byUrgency(a, b);
  });
}

function paintHead() {
  el("head-tabla").innerHTML = COLUMNS.map((column) => `
    <th scope="col" class="${column.cls || ""}${column.num ? " num" : ""}">
      <button class="sortbtn" type="button" data-sort="${column.id}"
        ${sort.key === column.id ? `aria-sort="${sort.dir === 1 ? "ascending" : "descending"}"` : ""}>
        ${column.label}<span class="sortbtn__dir">${
          sort.key === column.id && sort.dir === -1 ? "▼" : "▲"}</span>
      </button>
    </th>`).join("");

  el("head-tabla").querySelectorAll("[data-sort]").forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.sort;
      if (sort.key === key) sort.dir *= -1; else { sort.key = key; sort.dir = 1; }
      paintHead();
      renderTable();
    });
  });
}

/** Confianza en tres tramos: 0,49 frente a 0,76 no dice nada suelto, y es justo
 *  lo que matiza cuanto fiarse de la fila. */
function trustBars(value) {
  const n = Number(value || 0);
  const level = n >= 0.75 ? "alta" : n >= 0.55 ? "media" : "baja";
  const word = n >= 0.75 ? "high" : n >= 0.55 ? "medium" : "low";
  return `<span class="trust trust--${level}" title="${word} confidence (${decimal(n, 2)})">
    <i></i><i></i><i></i></span>`;
}

/* Sin familia elegida la tabla no vuelca las cuarenta filas: enseña las nueve
   familias con su recuento. La pregunta que trae a alguien aqui casi nunca es
   "que pasa con MRO-30012" sino "como estan las correas", y cuarenta filas de
   golpe obligan a buscar antes de poder mirar. */
function renderGroups(rows) {
  const body = el("rows-tabla");
  const groups = new Map();

  rows.forEach((item) => {
    const key = item.category || "No family";
    const g = groups.get(key) || { rows: [], open: 0, cost: 0 };
    g.rows.push(item);
    if (OPEN_DECISIONS.includes(item.decision)) g.open += 1;
    if (item.decision === "COMPRAR") g.cost += item.total_cost_usd || 0;
    groups.set(key, g);
  });

  body.innerHTML = [...groups.entries()].sort().map(([key, g]) => `
    <tr class="grouprow" data-open-cat="${escape(key)}" tabindex="0">
      <td class="grouprow__head">
        <span class="cell-part">
          <span class="cell-part__glyph">${glyph(key, { size: 30 })}</span>
          <span>
            <span class="grouprow__name">${escape(key)}</span>
            <span class="meta">${g.rows.length} part-and-plant combinations</span>
          </span>
        </span>
      </td>
      <td colspan="7" class="grouprow__state">
        ${g.open
          ? `<span class="tag"><i class="tag__dot tag__dot--hold"></i>${g.open} need a decision</span>`
          : '<span class="tag tag--NO_COMPRAR"><i class="tag__dot tag__dot--go"></i>nothing open</span>'}
        ${g.cost ? `<span class="meta mono">${usd(g.cost)} USD in purchases</span>` : ""}
      </td>
      <td class="grouprow__go">See the parts →</td>
    </tr>`).join("");

  body.querySelectorAll("[data-open-cat]").forEach((row) => {
    const open = () => {
      category = row.dataset.openCat;
      paintCategories();
      renderTable();
    };
    row.addEventListener("click", open);
    row.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); open(); }
    });
  });
}

export function renderTable() {
  const body = el("rows-tabla");
  const items = visibleItems();
  const active = filters.sync();

  body.innerHTML = "";
  const empty = el("empty-tabla");
  empty.hidden = items.length > 0;
  empty.textContent = `None of the ${state.items.length} rows matches these filters.`;

  if (!category && !active) {
    renderGroups(items);
    paintFoot(items, active);
    return;
  }

  items.forEach((item) => {
    const row = document.createElement("tr");
    row.tabIndex = 0;
    row.innerHTML = COLUMNS
      .map((column) => `<td class="${column.num ? "num" : ""}">${column.cell(item)}</td>`)
      .join("");

    const open = () => onOpenCase(item);
    row.addEventListener("click", open);
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter") { event.preventDefault(); open(); }
    });
    body.appendChild(row);
  });

  paintFoot(items, active);
}

/** Responde la pregunta que motivo el filtro: si dejo solo criticidad A,
 *  cuantas compras son y cuanto cuestan. */
function paintFoot(items, active) {
  const of = (decision) => items.filter((i) => i.decision === decision);
  const buy = of("COMPRAR");
  const review = of("REVISAR");
  const deferred = of("APLAZADO");
  const escalated = of("ESCALAR");
  const total = (rows) => rows.reduce((sum, i) => sum + (i.total_cost_usd || 0), 0);
  const qty = buy.reduce((sum, i) => sum + (i.recommended_qty || 0), 0);
  const idle = items.length - buy.length - review.length - deferred.length - escalated.length;

  el("foot-tabla").innerHTML = `
    <span><b>${items.length}</b> ${active ? `of ${state.items.length} rows` : "rows"}</span>
    ${escalated.length ? `<span><b>${escalated.length}</b> need budget</span>` : ""}
    <span><b>${buy.length}</b> to buy</span>
    <span><b>${review.length}</b> to decide</span>
    <span><b>${deferred.length}</b> deferred</span>
    <span><b>${idle}</b> no action</span>
    <span><b>${usd(total(buy))}</b> USD in purchases</span>
    <span><b>${units(qty)}</b> units</span>
    ${total(deferred) ? `<span><b>${usd(total(deferred))}</b> USD unfunded</span>` : ""}
    ${total(escalated) ? `<span><b>${usd(total(escalated))}</b> USD to escalate</span>` : ""}`;
}

/* ---------- Descarga del recorte ---------- */

const EXPORT = [
  ["sku_id", (i) => i.sku_id],
  ["description", (i) => i.description],
  ["criticality", (i) => i.criticality],
  ["plant", (i) => i.city_name],
  ["warehouse", (i) => i.warehouse_id],
  ["on_hand_qty", (i) => i.on_hand_qty],
  ["reorder_point", (i) => i.inventory_min],
  ["order_up_to_level", (i) => i.inventory_max],
  ["economic_order_qty", (i) => i.eoq_units],
  ["order_cost_usd", (i) => i.order_cost_usd],
  ["holding_cost_usd_unit_year", (i) => i.holding_cost_usd],
  ["demand_pattern", (i) => i.pattern],
  ["confidence", (i) => i.confidence],
  ["decision", (i) => i.decision],
  ["recommended_qty", (i) => i.recommended_qty],
  ["supplier", (i) => i.supplier_name],
  ["total_cost_usd", (i) => i.total_cost_usd],
  ["stockout_cost_usd", (i) => i.stockout_cost_usd],
  ["net_benefit_usd", (i) => i.net_benefit_usd],
  ["lead_time_days", (i) => i.lead_time_days],
  ["workflow_state", (i) => i.state],
  ["needs_review", (i) => i.needs_review],
];

function exportFiltered() {
  const items = visibleItems();
  const lines = [EXPORT.map(([name]) => name).join(",")];
  items.forEach((item) => lines.push(EXPORT.map(([, read]) => csv(read(item))).join(",")));
  download(lines, `mro-parts-${items.length}-rows.csv`);
}

export function csv(value) {
  const text = value === null || value === undefined ? "" : String(value);
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/** El BOM es lo que hace que Excel abra los acentos bien en Windows. */
export function download(lines, filename) {
  const blob = new Blob([`﻿${lines.join("\r\n")}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
