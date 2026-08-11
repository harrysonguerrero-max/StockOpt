/* Datos en crudo.
 *
 * El sitio donde se ve lo que el pipeline produjo, sin capa de presentacion por
 * encima: la cabecera es el nombre del campo y la celda es su valor tal como
 * viaja en la API y en los CSV. Nada se traduce, nada se redondea y nada se
 * convierte en barra o etiqueta.
 *
 * Es deliberado y no un descuido. El turno y la tabla leida interpretan el dato
 * —eligen que enseñar, en que unidad y con que palabra—, y precisamente por eso
 * hace falta un lugar donde comprobar contra que se hizo esa interpretacion. Lo
 * unico que se le añade es mecanico: fijar la cabecera, fijar la columna de la
 * pieza, ordenar, filtrar y llevarse el recorte.
 */

import { state } from "./api.js";
import { escape } from "./format.js";
import { mountFilters } from "./filtros.js";
import { csv, download } from "./tabla.js";

const el = (id) => document.getElementById(id);

/* El registro completo, en el orden en que se lee: que pieza y donde, que se
   decidio, el inventario, la demanda, la compra, el proveedor y la traza. */
const COLUMNS = [
  ["sku_id"], ["city_id"], ["description"], ["criticality"],
  ["decision"], ["needs_review", 1], ["state"],
  ["on_hand_qty", 1], ["inventory_min", 1], ["inventory_max", 1],
  ["demand_monthly", 1], ["pattern"], ["confidence", 1], ["forecast_source"],
  ["target_qty", 1], ["max_allowed_qty", 1], ["recommended_qty", 1],
  ["coverage_months", 1], ["shelf_life_days", 1],
  ["supplier_id"], ["supplier_name"], ["unit_price_usd", 1], ["freight_cost_usd", 1],
  ["total_cost_usd", 1], ["lead_time_days", 1], ["lead_time_min_days", 1],
  ["lead_time_max_days", 1], ["alternatives_evaluated", 1], ["contact_email"],
  ["city_name"], ["warehouse_id"],
  ["rejection_reason"], ["comment"], ["purchase_order"],
  ["updated_at"], ["updated_by"], ["reason"],
];

const sort = { key: "sku_id", dir: 1 };
let filters = null;
let onOpenCase = () => {};

export function setRawListener(callback) { onOpenCase = callback; }

export function initRaw() {
  filters = mountFilters("filters-crudo", "c", renderRaw, { raw: true });
  el("export-crudo").addEventListener("click", exportFiltered);
  paintHead();
}

export function fillRawFilters() { filters.fill(); }

function visibleItems() {
  // Los nulos van siempre al final, en los dos sentidos: no son un valor bajo,
  // son la ausencia de valor, y mezclarlos con los ceros confunde la lectura.
  return filters.apply().sort((left, right) => {
    const a = left[sort.key];
    const b = right[sort.key];
    if (a === b) return left.sku_id.localeCompare(right.sku_id);
    if (a === null || a === undefined || a === "") return 1;
    if (b === null || b === undefined || b === "") return -1;
    const cmp = typeof a === "number" ? a - b : String(a).localeCompare(String(b));
    return cmp * sort.dir;
  });
}

function paintHead() {
  el("head-crudo").innerHTML = COLUMNS.map(([field, numeric], index) => `
    <th scope="col" class="${numeric ? "num" : ""}${index === 0 ? " stick" : ""}">
      <button class="sortbtn" type="button" data-sort="${field}"
        ${sort.key === field ? `aria-sort="${sort.dir === 1 ? "ascending" : "descending"}"` : ""}>
        ${field}<span class="sortbtn__dir">${
          sort.key === field && sort.dir === -1 ? "▼" : "▲"}</span>
      </button>
    </th>`).join("");

  el("head-crudo").querySelectorAll("[data-sort]").forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.sort;
      if (sort.key === key) sort.dir *= -1; else { sort.key = key; sort.dir = 1; }
      paintHead();
      renderRaw();
    });
  });
}

/** El valor literal. Solo la decision y la marca de revision reciben color, y
 *  el texto sigue siendo exactamente el del campo. */
function cellMarkup(item, field, index) {
  const value = item[field];

  if (index === 0) {
    return `<button class="rawlink" type="button" title="Abrir el caso de ${
      escape(value)}">${escape(value)}</button>`;
  }
  if (value === null || value === undefined || value === "") {
    return '<span class="rawnull" title="Sin valor">·</span>';
  }
  if (field === "decision") {
    return `<span class="v-${escape(value)}">${escape(value)}</span>`;
  }
  if (field === "needs_review" && value === 1) {
    return '<span class="v-flag">1</span>';
  }
  return escape(value);
}

export function renderRaw() {
  const body = el("rows-crudo");
  const items = visibleItems();
  const active = filters.sync();

  el("crudo-count").textContent =
    `${items.length}${active ? ` de ${state.items.length}` : ""} filas · `
    + `${COLUMNS.length} campos`;

  const empty = el("empty-crudo");
  empty.hidden = items.length > 0;
  empty.textContent = `Ninguna de las ${state.items.length} filas cumple estos filtros.`;

  body.innerHTML = "";
  items.forEach((item) => {
    const row = document.createElement("tr");
    row.innerHTML = COLUMNS.map(([field, numeric], index) => {
      const raw = item[field];
      const title = raw === null || raw === undefined ? "" : ` title="${escape(raw)}"`;
      return `<td class="${numeric ? "num" : ""}${index === 0 ? " stick" : ""}"${title}>${
        cellMarkup(item, field, index)}</td>`;
    }).join("");

    row.querySelector(".rawlink").addEventListener("click", () => onOpenCase(item));
    body.appendChild(row);
  });
}

/** El enlace de la barra baja las cuarenta filas con las columnas que eligio el
 *  servidor. Aqui baja lo que hay en pantalla, con los treinta y siete campos. */
function exportFiltered() {
  const items = visibleItems();
  const fields = COLUMNS.map(([field]) => field);
  const lines = [fields.join(",")];
  items.forEach((item) => lines.push(fields.map((field) => csv(item[field])).join(",")));
  download(lines, `crudo-${items.length}-filas.csv`);
}
