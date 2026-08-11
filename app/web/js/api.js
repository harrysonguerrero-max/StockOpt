/* Acceso a la API y estado compartido de la pantalla.
 *
 * Un unico lugar habla con el servidor. Las vistas leen de `state` y piden
 * recargas por aqui, de modo que ninguna guarda su propia copia de los datos.
 */

const BASE = "/api/v1";

export const state = {
  items: [],
  filters: null,
  summary: null,
  openKey: null,
  view: "turno",
  focusPlant: null,
  tableFilter: null,
};

export const keyOf = (item) => `${item.sku_id}|${item.city_id}`;

export const findItem = (key) => state.items.find((item) => keyOf(item) === key) || null;

export async function api(path, options) {
  const response = await fetch(BASE + path, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || "No se pudo completar la operación");
  }
  return payload;
}

export async function loadQueue(refresh = false) {
  const data = await api(`/recommendations${refresh ? "?refresh=true" : ""}`);
  state.items = data.items;
  state.filters = data.filters;
  state.summary = data.summary;
  return data;
}

export const loadHistory = (sku, city) =>
  api(`/recommendations/${encodeURIComponent(sku)}/${encodeURIComponent(city)}/history`);

export const loadExplanation = (sku, city) =>
  api(`/recommendations/${encodeURIComponent(sku)}/${encodeURIComponent(city)}/explanation`);

export function applyState(item, newState, extra) {
  return api("/recommendations/state", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sku_id: item.sku_id,
      city_id: item.city_id,
      new_state: newState,
      ...(extra || {}),
    }),
  });
}

export function toast(message, isError) {
  const node = document.getElementById("toast");
  node.textContent = message;
  node.classList.toggle("toast--error", Boolean(isError));
  node.hidden = false;
  clearTimeout(node.timer);
  node.timer = setTimeout(() => { node.hidden = true; }, 3600);
}
