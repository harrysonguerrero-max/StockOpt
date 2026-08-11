/* El turno del comprador: la pantalla de entrada.
 *
 * La version anterior abria en el nivel mas granular que tenia —cuarenta filas
 * por siete columnas— y no ofrecia ninguno por encima. De ahi salia todo lo
 * demas: la tabla gigante de entrada, los seis filtros antes de saber que se
 * quiere filtrar, y la necesidad de explicar con palabras que cada decision es
 * por pieza y por ciudad.
 *
 * Aqui la pantalla abre arriba: una frase que resume el dia y dos columnas, una
 * por planta. El grano deja de necesitar explicacion porque es la estructura de
 * la pagina. Dentro de cada planta, tres bandas ordenadas por quien debe actuar;
 * la primera dice de forma explicita que ahi hace falta una persona, y eso es
 * la primera accion evidente que antes no existia.
 */

import { state } from "./api.js";
import { escape, stateShort, units, usdRound } from "./format.js";
import {
  ADVANCED, PENDING, actionLine, byUrgency, critChip, footLine, gauge, whyLine,
} from "./ui.js";

const BANDS = [
  {
    id: "decide",
    title: "El sistema no puede decidir esto",
    open: true,
    match: (i) => i.decision === "REVISAR" && i.state === PENDING,
  },
  {
    id: "aprobar",
    title: "Listo para aprobar",
    open: true,
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
    match: (i) => i.decision === "NO_COMPRAR" && i.state === PENDING
      || i.state === "Rechazado",
  },
];

const openBands = new Set(BANDS.filter((b) => b.open).map((b) => b.id));

export function renderTurno(onOpenCase) {
  paintOpening();
  paintPlants(onOpenCase);
}

/* ---------- La frase de apertura ---------- */

function paintOpening() {
  const s = state.summary;
  if (!s) return;

  const abiertas = s.to_buy + s.to_review;
  const line = document.getElementById("opening-line");

  line.innerHTML = abiertas === 0
    ? "Hoy no hay ninguna decisión abierta."
    : `Hoy hay <button class="figure-link" data-band="all">${abiertas} decisiones</button> abiertas: `
      + `<button class="figure-link figure-link--go" data-band="aprobar">${s.to_buy} compras</button> `
      + `por ${usdRound(s.investment_usd)} USD y `
      + `<button class="figure-link figure-link--hold" data-band="decide">${s.to_review}</button> `
      + `que el sistema no pudo resolver solo.`;

  line.querySelectorAll(".figure-link").forEach((button) => {
    button.addEventListener("click", () => focusBand(button.dataset.band));
  });

  document.getElementById("opening-note").innerHTML =
    `Las otras ${s.no_action} piezas cubren su mínimo. `
    + `Vida útil, existencias, lote mínimo y flete los genera el build con semilla fija: `
    + `van marcados <span class="synthetic" title="Campo generado por el build, no viene de un sistema real">gen</span> donde aparecen.`;
}

/** Una cifra de la frase abre su banda en las dos plantas y cierra el resto. */
function focusBand(id) {
  openBands.clear();
  if (id === "all") {
    openBands.add("decide");
    openBands.add("aprobar");
  } else {
    openBands.add(id);
  }
  document.querySelectorAll(".band").forEach((band) => {
    band.dataset.open = String(openBands.has(band.dataset.band));
  });
  document.getElementById("plants").scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ---------- Las dos plantas ---------- */

function paintPlants(onOpenCase) {
  const host = document.getElementById("plants");
  host.innerHTML = "";

  const cities = state.filters ? state.filters.cities : [];
  const focus = state.focusPlant;
  host.style.gridTemplateColumns = focus ? "minmax(0, 1fr)" : "";

  cities
    .filter((city) => !focus || city.id === focus)
    .forEach((city) => {
      const items = state.items.filter((item) => item.city_id === city.id);
      host.appendChild(plantSection(city, items, onOpenCase));
    });
}

function plantSection(city, items, onOpenCase) {
  const section = document.createElement("section");
  section.className = "plant";

  const abiertas = items.filter(
    (i) => i.state === PENDING && i.decision !== "NO_COMPRAR"
  );
  const inversion = abiertas
    .filter((i) => i.decision === "COMPRAR")
    .reduce((total, i) => total + (i.total_cost_usd || 0), 0);
  const warehouse = items[0] ? items[0].warehouse_id : "";
  const focused = state.focusPlant === city.id;

  const head = document.createElement("button");
  head.type = "button";
  head.className = "plant__head";
  head.title = focused ? "Ver las dos plantas" : "Ver solo esta planta";
  head.innerHTML = `
    <span>
      <span class="plant__name">${escape(city.name)}</span><br>
      <span class="plant__warehouse">${escape(warehouse)}</span>
    </span>
    <span class="plant__count">
      <b>${abiertas.length}</b> por decidir${inversion ? ` · ${usdRound(inversion)} USD` : ""}
    </span>`;
  head.addEventListener("click", () => {
    state.focusPlant = focused ? null : city.id;
    paintPlants(onOpenCase);
  });
  section.appendChild(head);

  BANDS.forEach((band) => {
    const rows = items.filter(band.match).sort(byUrgency);
    if (!rows.length) return;
    section.appendChild(bandBlock(band, rows, onOpenCase));
  });

  return section;
}

function bandBlock(band, rows, onOpenCase) {
  const block = document.createElement("div");
  block.className = `band band--${band.id}${band.muted ? " band--muted" : ""}`;
  block.dataset.band = band.id;
  block.dataset.open = String(openBands.has(band.id));

  const rule = document.createElement("div");
  rule.className = "band__rule";

  const head = document.createElement("button");
  head.type = "button";
  head.className = "band__head";
  head.innerHTML = `<span class="band__caret">▶</span> ${band.title}
    <span class="band__n">${rows.length}</span>`;
  head.addEventListener("click", () => {
    const next = block.dataset.open !== "true";
    if (next) openBands.add(band.id); else openBands.delete(band.id);
    document.querySelectorAll(`.band[data-band="${band.id}"]`)
      .forEach((node) => { node.dataset.open = String(next); });
  });

  const body = document.createElement("div");
  body.className = "band__body";
  rows.forEach((item) => body.appendChild(caseCard(item, onOpenCase)));

  block.append(rule, head, body);
  return block;
}

/* ---------- La tarjeta ----------
 * Se lee sola de arriba abajo: que pieza, como esta el stock, que hay que
 * hacer, por que, y a quien comprarle. El medidor, que antes era la tercera
 * columna de una tabla de siete, es aqui el centro.
 */

function caseCard(item, onOpenCase) {
  const card = document.createElement("article");
  const action = actionLine(item);

  card.className = `case case--${item.gauge.zone}`;
  card.tabIndex = 0;
  card.setAttribute("role", "button");
  card.innerHTML = `
    <span class="case__top">
      <span class="case__sku">${escape(item.sku_id)}</span>
      ${critChip(item)}
      ${item.state !== PENDING
        ? `<span class="case__state">${escape(stateShort(item.state))}</span>` : ""}
    </span>
    <p class="case__name">${escape(item.description)}</p>
    ${gauge(item)}
    <p class="case__action case__action--${action.tone}">${action.text}</p>
    <p class="case__why">${whyLine(item)}</p>
    <span class="case__foot">${footLine(item)}</span>`;

  const open = () => onOpenCase(item);
  card.addEventListener("click", open);
  card.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      open();
    }
  });
  return card;
}
