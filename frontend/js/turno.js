/* El turno del comprador: la pantalla de entrada.
 *
 * Abre por lo que amenaza la cadena, no por el inventario de trabajo. Primero
 * la desviacion —si el presupuesto dejo reposiciones sin financiar, eso es lo
 * unico que importa saber al entrar—, luego el mapa que dice donde estan los
 * casos, y solo despues la lista.
 *
 * La lista va ordenada por el semaforo y no por volumen. Las compras que el
 * solver resolvio sin ambigüedad son automaticas: se cuentan, se pueden abrir,
 * pero llegan plegadas, porque no reclaman criterio. Lo que se abre solo es lo
 * que necesita a una persona.
 */

import { applyState, state, toast } from "./api.js";
import { escape, usdRound } from "./format.js";
import { drawMap, plantCard } from "./mapa.js";
import {
  ADVANCED, PENDING, actionLine, byUrgency, critChip, footLine, gauge,
  recommendation, semaphore, whyLine,
} from "./ui.js";
import { glyph } from "./glyphs.js";

const BANDS = [
  {
    id: "decide",
    title: "Necesitan tu decisión",
    open: true,
    match: (i) => i.decision === "REVISAR" && i.state === PENDING,
  },
  {
    id: "aplazado",
    title: "Frenadas por presupuesto",
    open: true,
    match: (i) => i.decision === "APLAZADO" && i.state === PENDING,
  },
  {
    id: "auto",
    title: "Compras automáticas",
    open: false,
    match: (i) => i.decision === "COMPRAR" && i.state === PENDING,
  },
  {
    id: "curso",
    title: "En curso",
    open: false,
    match: (i) => ADVANCED.includes(i.state),
  },
  {
    id: "quieto",
    title: "Sin acción",
    open: false,
    muted: true,
    match: (i) => (i.decision === "NO_COMPRAR" && i.state === PENDING)
      || i.state === "Rechazado",
  },
];

const openBands = new Set(BANDS.filter((b) => b.open).map((b) => b.id));
let onOpenCase = () => {};
let onChanged = () => {};

export function renderTurno(callback, refresh) {
  onOpenCase = callback;
  if (refresh) onChanged = refresh;
  paintOpening();
  paintMap();
  paintBands();
}

/* ---------- La apertura ----------
 * Una alerta, no un recuento. Lo que decide si el comprador tiene que hacer
 * algo hoy es si el presupuesto dejo riesgo sin cubrir, no cuantas filas hay.
 */

function paintOpening() {
  const s = state.summary;
  if (!s) return;

  const deferred = s.deferred || 0;
  const line = document.getElementById("opening-line");
  const note = document.getElementById("opening-note");

  if (deferred > 0) {
    line.className = "display display--alert";
    line.innerHTML = `El presupuesto se agotó y dejó `
      + `<button class="figure-link figure-link--stop" data-band="aplazado">`
      + `${deferred} reposiciones</button> sin financiar, `
      + `con ${usdRound(s.stockout_exposed_usd)} USD de quiebre expuesto.`;
  } else {
    line.className = "display";
    line.innerHTML = "El presupuesto cubre todo lo que procedía. Ninguna reposición quedó fuera.";
  }

  // Las cifras cuentan lo que sigue pendiente, no el total de la corrida: una
  // fila ya aprobada no reclama nada y sumarla infla el trabajo por delante.
  const pending = (decision) => state.items.filter(
    (i) => i.decision === decision && i.state === PENDING
  );
  const review = pending("REVISAR");
  const auto = pending("COMPRAR");
  const causes = reviewCauses(review);

  note.innerHTML = `
    <span class="lede">
      ${deferred > 0
        ? `Ampliar el presupuesto en <b>${usdRound(s.deferred_usd)} USD</b> lo cierra. `
        : ""}
      <button class="figure-link figure-link--go" data-band="auto">${auto.length} compras</button>
      salen automáticas por <b>${usdRound(s.investment_usd)} USD</b> de los
      ${usdRound(s.budget_usd)} USD de la corrida, y evitan
      ${usdRound(s.stockout_avoided_usd)} USD de quiebre.
    </span>
    <span class="lede">
      <button class="figure-link figure-link--hold" data-band="decide">${review.length} casos</button>
      necesitan tu criterio${causes ? `, ${causes}` : ""}. Las otras ${s.no_action}
      piezas cubren su mínimo.
    </span>`;

  document.querySelectorAll(".opening .figure-link").forEach((button) => {
    button.addEventListener("click", () => focusBand(button.dataset.band));
  });
}

/** Agrupa por que el solver no pudo cerrar los casos que siguen abiertos.
 *
 *  El limite que bloquea es `max_allowed_qty`, no la capacidad de la bodega:
 *  descuenta ademas lo que caducaria antes de consumirse. */
function reviewCauses(review) {
  if (!review.length) return "";

  const overflow = review.filter((i) => i.recommended_qty > i.max_allowed_qty).length;
  const rest = review.length - overflow;

  if (overflow === review.length) {
    return "el lote mínimo del proveedor supera lo que se puede almacenar";
  }
  const parts = [];
  if (overflow) parts.push(`${overflow} por lote mínimo`);
  if (rest) parts.push(`${rest} por otras restricciones`);
  return parts.join(" y ");
}

function focusBand(id) {
  openBands.clear();
  openBands.add(id);
  paintBands();
  document.getElementById("bands").scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ---------- El mapa ---------- */

const sum = (rows, field) => rows.reduce((total, i) => total + (Number(i[field]) || 0), 0);

/** Todo lo que caracteriza una planta sale de sus propias filas. */
function plantStats(city) {
  const rows = state.items.filter((i) => i.city_id === city.id);
  const open = rows.filter(
    (i) => i.state === PENDING && ["REVISAR", "APLAZADO"].includes(i.decision)
  );
  const deferred = open.filter((i) => i.decision === "APLAZADO").length;

  return {
    id: city.id,
    name: city.name,
    short: city.name.split(",")[0],
    warehouse: rows[0] ? rows[0].warehouse_id : "",
    parts: rows.length,
    open: open.length,
    deferred,
    level: deferred ? "stop" : open.length ? "hold" : "go",
    stock: sum(rows, "on_hand_qty"),
    capacity: sum(rows, "inventory_max"),
    demand: sum(rows, "demand_monthly"),
    investment: sum(rows.filter((i) => i.decision === "COMPRAR"), "total_cost_usd"),
  };
}

function paintMap() {
  const plants = (state.filters ? state.filters.cities : []).map(plantStats);

  drawMap(plants, {
    selected: state.focusPlant,
    onSelect: (id) => {
      state.focusPlant = state.focusPlant === id ? null : id;
      paintMap();
      paintBands();
    },
  });

  const picked = plants.find((p) => p.id === state.focusPlant);
  document.getElementById("plant-card").innerHTML = plantCard(picked);

  const label = document.getElementById("map-filter");
  label.innerHTML = picked
    ? `Mostrando solo <b>${escape(picked.name)}</b> · <button class="figure-link" id="map-clear">ver las dos plantas</button>`
    : "Pulsa una planta para ver su ficha y filtrar los casos.";

  const clear = document.getElementById("map-clear");
  if (clear) {
    clear.addEventListener("click", () => {
      state.focusPlant = null;
      paintMap();
      paintBands();
    });
  }
}

/* ---------- Las bandas ---------- */

function paintBands() {
  const host = document.getElementById("bands");
  const scope = state.focusPlant
    ? state.items.filter((i) => i.city_id === state.focusPlant)
    : state.items;

  host.innerHTML = "";
  BANDS.forEach((band) => {
    const rows = scope.filter(band.match).sort(byUrgency);
    if (!rows.length) return;
    host.appendChild(bandBlock(band, rows));
  });
}

function bandBlock(band, rows) {
  const block = document.createElement("section");
  block.className = `band band--${band.id}${band.muted ? " band--muted" : ""}`;
  block.dataset.band = band.id;
  block.dataset.open = String(openBands.has(band.id));

  const head = document.createElement("button");
  head.type = "button";
  head.className = "band__head";
  head.innerHTML = `<span class="band__caret">▶</span>
    <span class="band__title">${band.title}</span>
    <span class="band__n">${rows.length}</span>`;
  head.addEventListener("click", () => {
    const next = block.dataset.open !== "true";
    if (next) openBands.add(band.id); else openBands.delete(band.id);
    block.dataset.open = String(next);
  });

  const body = document.createElement("div");
  body.className = "band__body";
  rows.forEach((item) => body.appendChild(caseCard(item)));

  block.append(head, body);
  return block;
}

/* ---------- La tarjeta ----------
 * Se lee de arriba abajo: que pieza es —con su dibujo, porque un rodamiento no
 * se reconoce por el codigo—, como esta el stock, que hay que hacer y por que.
 * En los casos que piden criterio, ademas, que haria el sistema.
 */

function caseCard(item) {
  const card = document.createElement("article");
  const action = actionLine(item);
  const light = semaphore(item);
  const advice = recommendation(item);

  card.className = `case case--${light.level}`;
  card.tabIndex = 0;
  card.setAttribute("role", "button");
  card.innerHTML = `
    <span class="case__mark" aria-hidden="true"></span>
    <span class="case__part">
      <span class="case__glyph">${glyph(item.category, { size: 34 })}</span>
      <span>
        <span class="case__top">
          <span class="case__sku">${escape(item.sku_id)}</span>
          ${critChip(item)}
          <span class="case__light case__light--${light.level}">${light.label}</span>
        </span>
        <span class="case__name">${escape(item.description)}</span>
      </span>
    </span>
    ${gauge(item)}
    <span class="case__action case__action--${action.tone}">${action.text}</span>
    <span class="case__why">${whyLine(item)}</span>
    ${advice ? `
      <span class="advice advice--${advice.buy ? "buy" : "hold"}">
        <b>${advice.headline}</b> ${advice.why}
        <i>La decisión sigue siendo tuya.</i>
      </span>` : ""}
    <span class="case__foot">${footLine(item)}</span>
    ${decideBar(item)}`;

  const open = () => onOpenCase(item);
  card.addEventListener("click", open);
  card.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      open();
    }
  });

  /* Aprobar se resuelve en la tarjeta porque no necesita nada mas. Rechazar
     exige motivo, y el motivo vive en el panel: llevar alli es mas honesto que
     inventar un rechazo sin causa registrada. */
  const approve = card.querySelector("[data-approve]");
  if (approve) {
    approve.addEventListener("click", async (event) => {
      event.stopPropagation();
      approve.disabled = true;
      try {
        await applyState(item, "Aprobado");
        toast(`${item.sku_id} · aprobado`);
        await onChanged();
      } catch (error) {
        approve.disabled = false;
        toast(error.message, true);
      }
    });
  }

  const reject = card.querySelector("[data-reject]");
  if (reject) {
    reject.addEventListener("click", (event) => {
      event.stopPropagation();
      onOpenCase(item);
    });
  }

  return card;
}

/** Barra de decision de la tarjeta, mas la pista de que hay detalle detras. */
function decideBar(item) {
  const next = item.next_states || [];
  const canApprove = next.includes("Aprobado");
  const canReject = next.includes("Rechazado");
  if (!canApprove && !canReject) {
    return '<span class="case__more">Ver el detalle <i>→</i></span>';
  }

  return `
    <span class="case__decide">
      ${canApprove ? '<button class="btn btn--go" type="button" data-approve>Aprobar</button>' : ""}
      ${canReject ? '<button class="btn btn--stop" type="button" data-reject>Rechazar…</button>' : ""}
      <span class="case__more">Ver el detalle <i>→</i></span>
    </span>`;
}
