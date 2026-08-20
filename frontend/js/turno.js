/* El turno del comprador: la pantalla de entrada.
 *
 * Abre por lo que amenaza la produccion, no por el inventario de trabajo ni por
 * el presupuesto. El presupuesto dejo de mandar sobre todo: las piezas cuyo
 * quiebre para una linea se reponen siempre, y lo que la pantalla tiene que
 * decir primero es si eso se consiguio. Solo despues viene lo que costo y que
 * desplazo.
 *
 * Luego el mapa, que dice donde estan los casos, y por ultimo la lista.
 *
 * La lista va ordenada por el semaforo y no por volumen. Las compras que el
 * solver resolvio sin ambigüedad son automaticas: se cuentan, se pueden abrir,
 * pero llegan plegadas, porque no reclaman criterio. Lo que se abre solo es lo
 * que necesita a una persona.
 */

import { applyState, state, toast } from "./api.js";
import { escape, percent, usdRound } from "./format.js";
import { drawMap, plantCard } from "./mapa.js";
import {
  ADVANCED, PENDING, actionLine, byUrgency, critChip, footLine, gauge,
  recommendation, semaphore, whyLine,
} from "./ui.js";
import { glyph } from "./glyphs.js";

const BANDS = [
  {
    id: "escalar",
    title: "Need a budget decision",
    open: true,
    match: (i) => i.decision === "ESCALAR" && i.state === PENDING,
  },
  {
    id: "decide",
    title: "Need your decision",
    open: true,
    match: (i) => i.decision === "REVISAR" && i.state === PENDING,
  },
  {
    id: "aplazado",
    title: "Held back by the budget",
    open: true,
    match: (i) => i.decision === "APLAZADO" && i.state === PENDING,
  },
  {
    id: "auto",
    title: "Automatic purchases",
    open: false,
    match: (i) => i.decision === "COMPRAR" && i.state === PENDING,
  },
  {
    id: "curso",
    title: "In progress",
    open: false,
    match: (i) => ADVANCED.includes(i.state),
  },
  {
    id: "quieto",
    title: "No action",
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
 * algo hoy es si algo amenaza la continuidad de produccion. El dinero viene
 * despues, porque es el medio y no el fin: gastar de mas para no parar una
 * linea es una decision correcta, y la pantalla tiene que poder decirlo asi.
 */

const serviceOf = (summary, criticality) =>
  (summary.service || []).find((level) => level.criticality === criticality) || null;

function paintOpening() {
  const s = state.summary;
  if (!s) return;

  const line = document.getElementById("opening-line");
  const note = document.getElementById("opening-note");
  const critical = serviceOf(s, "A");
  const escalated = s.escalated || 0;

  if (escalated > 0) {
    line.className = "display display--alert";
    line.innerHTML = "Production continuity is exposed: "
      + `<button class="figure-link figure-link--stop" data-band="escalar">`
      + `${escalated} critical ${escalated === 1 ? "part" : "parts"}</button> `
      + `cannot be replenished within the authorised budget, leaving `
      + `${usdRound(s.stockout_escalated_usd)} USD of line-stoppage risk uncovered.`;
  } else if (critical && critical.needed > 0) {
    line.className = "display";
    line.innerHTML = `Production is covered: all <b>${critical.needed}</b> criticality-A `
      + `${critical.needed === 1 ? "replenishment is" : "replenishments are"} funded. `
      + "Nothing that stops a line is waiting for money.";
  } else {
    line.className = "display";
    line.innerHTML = "No criticality-A part is below its reorder point. "
      + "Nothing threatens the line this run.";
  }

  note.innerHTML = `${costLine(s)}\n${tradeOffLine(s)}\n${workLine(s)}`;

  document.querySelectorAll(".opening .figure-link").forEach((button) => {
    button.addEventListener("click", () => focusBand(button.dataset.band));
  });
}

/** Que costo proteger la continuidad, y de donde salio el dinero.
 *
 *  La cifra de dinero es la de la corrida entera y no la de lo que sigue
 *  pendiente: el reparto se hizo sobre todas las compras, y aprobar una fila no
 *  cambia lo que costo. Lo pendiente se cuenta aparte, porque es lo unico que
 *  reclama a una persona. */
function costLine(s) {
  const pending = state.items.filter((i) => i.decision === "COMPRAR" && i.state === PENDING);
  const overrun = s.overrun_usd || 0;

  const funding = overrun > 0
    ? `That took the <b>${usdRound(s.budget_usd)} USD</b> of run budget plus `
      + `<b>${usdRound(overrun)} USD</b> of the ${usdRound(s.overrun_max_usd)} USD `
      + "authorised overrun, reported rather than hidden."
    : `It fits inside the <b>${usdRound(s.budget_usd)} USD</b> of the run, `
      + `with ${usdRound(s.budget_usd - s.investment_usd)} USD still free.`;

  return `<span class="lede">
      The run commits <b>${usdRound(s.investment_usd)} USD</b> across ${s.to_buy}
      ${s.to_buy === 1 ? "purchase" : "purchases"} and avoids
      ${usdRound(s.stockout_avoided_usd)} USD of stockout, of which
      <button class="figure-link figure-link--go" data-band="auto">${pending.length} `
    + `${pending.length === 1 ? "is" : "are"} still waiting</button>
      for your approval. ${funding}
    </span>`;
}

/** Que se desplazo para conseguirlo, y contra que politica se mide. */
function tradeOffLine(s) {
  const deferred = s.deferred || 0;
  if (!deferred) {
    return '<span class="lede">Nothing else was displaced: every replenishment that '
      + "was due is funded.</span>";
  }

  const missed = (s.service || []).filter((level) => level.needed > 0 && !level.met);
  const policy = missed.length
    ? " Service lands at " + missed.map((level) =>
      `<b>${percent(level.achieved)}</b> on class ${level.criticality} against a declared `
      + `floor of ${percent(level.floor)}`).join(", and at ") + "."
    : "";

  return `<span class="lede">
      Protecting it displaced
      <button class="figure-link figure-link--stop" data-band="aplazado">${deferred} `
    + `${deferred === 1 ? "replenishment" : "replenishments"}</button>
      worth <b>${usdRound(s.deferred_usd)} USD</b>, which leaves
      ${usdRound(s.stockout_exposed_usd)} USD of stockout risk uncovered.${policy}
    </span>`;
}

/** El trabajo que queda por delante para una persona. */
function workLine(s) {
  const review = state.items.filter((i) => i.decision === "REVISAR" && i.state === PENDING);
  const causes = reviewCauses(review);

  if (!review.length) {
    return `<span class="lede">No case needs your judgement. The other ${s.no_action} `
      + "parts cover their minimum.</span>";
  }

  return `<span class="lede">
      <button class="figure-link figure-link--hold" data-band="decide">${review.length} `
    + `${review.length === 1 ? "case needs" : "cases need"}</button>
      your judgement${causes ? `, ${causes}` : ""}. The other ${s.no_action} parts cover
      their minimum.
    </span>`;
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
    return "the supplier minimum lot exceeds what the part can hold";
  }
  const parts = [];
  if (overflow) parts.push(`${overflow} on minimum lot size`);
  if (rest) parts.push(`${rest} on other constraints`);
  return parts.join(" and ");
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
    (i) => i.state === PENDING && ["ESCALAR", "REVISAR", "APLAZADO"].includes(i.decision)
  );
  const escalated = open.filter((i) => i.decision === "ESCALAR").length;
  const deferred = open.filter((i) => i.decision === "APLAZADO").length;

  return {
    id: city.id,
    name: city.name,
    short: city.name.split(",")[0],
    warehouse: rows[0] ? rows[0].warehouse_id : "",
    parts: rows.length,
    open: open.length,
    escalated,
    deferred,
    level: escalated || deferred ? "stop" : open.length ? "hold" : "go",
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
    ? `Showing <b>${escape(picked.name)}</b> only · <button class="figure-link" id="map-clear">see both plants</button>`
    : "Click a plant to see its card and filter the cases.";

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
        <i>The call is still yours.</i>
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
        toast(`${item.sku_id} · approved`);
        await onChanged();
      } catch (error) {
        /* Si el servidor rechaza la transicion es que la pantalla ya no
           coincide con la base: alguien decidio esa fila desde otro sitio, o
           esta pestaña lleva abierta desde antes. Recargar deja los botones
           acordes a la realidad en lugar de ofrecer una accion imposible. */
        toast(error.message, true);
        await onChanged();
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
    return '<span class="case__more">See the detail <i>→</i></span>';
  }

  return `
    <span class="case__decide">
      ${canApprove ? '<button class="btn btn--go" type="button" data-approve>Approve</button>' : ""}
      ${canReject ? '<button class="btn btn--stop" type="button" data-reject>Reject…</button>' : ""}
      <span class="case__more">See the detail <i>→</i></span>
    </span>`;
}
