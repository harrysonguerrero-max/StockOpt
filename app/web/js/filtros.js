/* Barra de filtros reutilizable.
 *
 * Las dos vistas de tabla —la interpretada y la de datos en crudo— filtran
 * sobre los mismos campos, pero cada una mantiene su propio estado: quien
 * acota el crudo para inspeccionar un caso no quiere encontrarse la otra
 * pantalla acotada al volver. Por eso se monta una barra por vista, con su
 * prefijo de identificadores, en lugar de compartir una sola.
 *
 * La unica diferencia entre ambas es como se etiquetan las opciones: en el
 * crudo se ofrece el valor literal, porque alli el valor literal es el asunto.
 */

import { state } from "./api.js";
import { escape } from "./format.js";

const DECISION_WORD = {
  COMPRAR: "Comprar", NO_COMPRAR: "No comprar", REVISAR: "Revisar", APLAZADO: "Aplazado",
};

export function mountFilters(hostId, prefix, onChange, { raw = false } = {}) {
  const host = document.getElementById(hostId);
  const id = (name) => `${prefix}-${name}`;
  const el = (name) => document.getElementById(id(name));

  host.innerHTML = `
    <label class="field field--grow">
      <span class="label">Buscar</span>
      <input type="search" id="${id("search")}" autocomplete="off"
             placeholder="Código o descripción">
    </label>
    <label class="field">
      <span class="label">Planta</span>
      <select id="${id("city")}"><option value="">Todas</option></select>
    </label>
    <label class="field">
      <span class="label">Decisión</span>
      <select id="${id("decision")}"><option value="">Todas</option></select>
    </label>
    <label class="field">
      <span class="label">Estado</span>
      <select id="${id("state")}"><option value="">Todos</option></select>
    </label>
    <label class="field">
      <span class="label">Criticidad</span>
      <select id="${id("crit")}"><option value="">Todas</option></select>
    </label>
    <label class="field field--check">
      <input type="checkbox" id="${id("review")}">
      <span>Solo las que piden revisión</span>
    </label>
    <button class="btn btn--quiet" id="${id("clear")}" type="button" hidden>Quitar filtros</button>`;

  const controls = ["search", "city", "decision", "state", "crit", "review"].map(el);
  controls.forEach((node) => node.addEventListener("input", onChange));

  function clear() {
    controls.forEach((node) => {
      if (node.type === "checkbox") node.checked = false; else node.value = "";
    });
    onChange();
  }

  el("clear").addEventListener("click", clear);

  function count() {
    return controls.filter((node) =>
      (node.type === "checkbox" ? node.checked : node.value.trim() !== "")).length;
  }

  /** Rellena los desplegables con lo que traiga el servidor, una sola vez. */
  function fill() {
    if (host.dataset.ready || !state.filters) return;
    const add = (name, values, labeller) => {
      const node = el(name);
      values.forEach((value) => {
        const option = document.createElement("option");
        const [key, text] = labeller(value);
        option.value = key;
        option.textContent = text;
        node.appendChild(option);
      });
    };

    add("city", state.filters.cities, (c) => [c.id, raw ? `${c.id} · ${c.name}` : c.name]);
    add("decision", state.filters.decisions,
      (d) => [d, raw ? d : DECISION_WORD[d] || d]);
    add("state", state.filters.states, (s) => [s, s]);
    add("crit", state.filters.criticalities,
      (c) => [c, raw ? c : `Criticidad ${c}`]);
    host.dataset.ready = "1";
  }

  /** Aplica los filtros sobre la cola completa. */
  function apply() {
    const search = el("search").value.trim().toLowerCase();
    const city = el("city").value;
    const decision = el("decision").value;
    const workflow = el("state").value;
    const criticality = el("crit").value;
    const onlyReview = el("review").checked;

    return state.items.filter((item) => {
      if (city && item.city_id !== city) return false;
      if (decision && item.decision !== decision) return false;
      if (workflow && item.state !== workflow) return false;
      if (criticality && item.criticality !== criticality) return false;
      if (onlyReview && item.needs_review !== 1) return false;
      if (search) {
        return `${item.sku_id} ${item.description}`.toLowerCase().includes(search);
      }
      return true;
    });
  }

  /** El boton de limpiar solo existe cuando hay algo que limpiar. */
  function sync() {
    el("clear").hidden = count() === 0;
    return count();
  }

  return { apply, count, clear, fill, sync };
}

export const decisionWord = (value) => DECISION_WORD[value] || escape(value);
