/* Datos en crudo: el explorador de las tablas del dataset.
 *
 * Un indice a la izquierda con las once tablas agrupadas por la etapa que las
 * produce, y a la derecha la tabla elegida tal como esta en disco: sus filas sin
 * tocar, la definicion de cada columna —tipo, unidad y de donde sale— y las
 * notas de lo que se hizo con ella.
 *
 * Es el sitio donde se comprueba contra que se hizo la interpretacion de las
 * otras pantallas. Por eso ni traduce ni redondea: si una columna dice 14.5, en
 * la celda pone 14.5.
 */

import { api, toast } from "./api.js";
import { escape } from "./format.js";

const el = (id) => document.getElementById(id);
const count = (value) => Number(value || 0).toLocaleString("es-MX");

const explorer = { catalog: [], table: null, page: 0, size: 50 };

function paintIndex() {
  const groups = [];
  explorer.catalog.forEach((table) => {
    const group = groups.find((item) => item.stage === table.stage);
    if (group) group.tables.push(table);
    else groups.push({ stage: table.stage, tables: [table] });
  });

  el("table-list").innerHTML = groups.map((group) => `
    <li class="tablelist__group">
      <span class="label">${escape(group.stage)}</span>
      <ul>${group.tables.map((table) => `
        <li>
          <button type="button" class="tablelist__btn${
            table.name === explorer.table?.name ? " tablelist__btn--on" : ""}"
                  data-table="${escape(table.name)}" ${table.available ? "" : "disabled"}>
            <span>${escape(table.title)}</span>
            <span class="meta mono">${table.available
              ? `${count(table.row_count)} × ${table.column_count}` : "sin generar"}</span>
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
    el("t-file").textContent = explorer.table.name;
    el("t-summary").textContent = explorer.table.summary;
    el("t-download").href = `/api/v1/data/files/${name}`;
    el("t-notes").innerHTML = (explorer.table.notes || [])
      .map((note) => `<p class="note">${escape(note)}</p>`).join("");
    paintIndex();
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

/** La cabecera lleva la unidad y, al pasar por encima, de donde sale la columna:
 *  es la diferencia entre leer un CSV y entenderlo. */
function paintGrid() {
  const table = explorer.table;
  if (!table) return;

  el("t-head").innerHTML = `<tr>${table.columns.map((column) => `
    <th title="${escape(column.description || column.name)}${
      column.origin ? ` — Origen: ${escape(column.origin)}` : ""}">
      ${escape(column.name)}
      <span class="grid__unit">${escape(
        column.unit && column.unit !== "-" ? column.unit : column.type)}</span>
    </th>`).join("")}</tr>`;

  const rows = visibleRows();
  const pages = Math.max(1, Math.ceil(rows.length / explorer.size));
  explorer.page = Math.min(explorer.page, pages - 1);
  const start = explorer.page * explorer.size;

  el("t-body").innerHTML = rows.slice(start, start + explorer.size).map((row) =>
    `<tr>${row.map((cell) => `<td class="${typeof cell === "number" ? "num mono" : ""}">${
      cell === null || cell === undefined || cell === ""
        ? '<span class="rawnull" title="Sin valor">·</span>' : escape(cell)
    }</td>`).join("")}</tr>`).join("");

  el("t-count").textContent = rows.length === table.rows.length
    ? `${count(table.rows.length)} filas · ${table.columns.length} columnas`
    : `${count(rows.length)} de ${count(table.rows.length)} filas`;
  el("t-page").textContent = `${explorer.page + 1} / ${pages}`;
  el("t-prev").disabled = explorer.page === 0;
  el("t-next").disabled = explorer.page >= pages - 1;
}

export async function loadCatalog() {
  if (explorer.catalog.length) return;
  try {
    const data = await api("/data/tables");
    explorer.catalog = data.tables;
    paintIndex();
    const first = explorer.catalog.find((table) => table.available);
    if (first) openTable(first.name);
  } catch (error) {
    el("t-summary").textContent = error.message;
  }
}

export function initDatos() {
  el("t-search").addEventListener("input", () => { explorer.page = 0; paintGrid(); });
  el("t-prev").addEventListener("click", () => { explorer.page -= 1; paintGrid(); });
  el("t-next").addEventListener("click", () => { explorer.page += 1; paintGrid(); });
}
