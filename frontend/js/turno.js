/* El turno del comprador: la pantalla de entrada.
 *
 * Se lee de arriba abajo en tres alturas, y cada una responde una pregunta
 * distinta para que ninguna tenga que responder dos:
 *
 *   1. El estado    ¿estoy bien? Vive en `salud.js`.
 *   2. Los casos    ¿que tengo que decidir? Columna izquierda, la ancha.
 *   3. El mapa      ¿donde esta? Columna derecha, porque son dos plantas y no
 *                   necesita mas sitio del que ocupa una ficha.
 *
 * La lista solo contiene lo que reclama a una persona. Lo que el optimizador
 * resolvio sin ambiguedad se compromete solo y baja plegado al final; las mil
 * ciento diecisiete piezas que cubren su minimo no son una banda sino una linea,
 * porque una alerta que no pide accion no es una alerta, es ruido — y el ruido
 * es lo que hace que se apruebe sin mirar.
 */

import { applyState, state, toast } from "./api.js";
import { escape, usdRound } from "./format.js";
import { drawMap, highlightPlant, plantCard } from "./mapa.js";
import { renderHealth, setJumpListener } from "./salud.js";
import { ADVANCED, PENDING, REJECTED, gauge, planLine, riskLine, verdictLine } from "./ui.js";
import { glyph } from "./glyphs.js";

const CRITICALITY_MEANS = {
  A: "Stops a line",
  B: "Degrades output",
  C: "Tolerable",
};

/* Las bandas son solo las que piden criterio, mas la de lo ya comprometido, que
   llega plegada. El orden es el del semaforo: primero lo que no puede esperar. */
const BANDS = [
  {
    id: "escalar",
    title: "Need a budget decision",
    hint: "Critical parts that do not fit even with the authorised overrun",
    open: true,
    match: (i) => i.decision === "ESCALAR" && i.state === PENDING,
  },
  {
    id: "decide",
    title: "Need your decision",
    hint: "The supplier minimum lot is above what the part can hold",
    open: true,
    byCriticality: true,
    match: (i) => i.decision === "REVISAR" && i.state === PENDING,
  },
  {
    id: "aplazado",
    title: "Held back by the budget",
    hint: "They were due, and protecting production took the money first",
    open: true,
    match: (i) => i.decision === "APLAZADO" && i.state === PENDING,
  },
  /* Comprado es comprado, lo haya decidido el sistema o una persona.
     Habia dos bandas —"comprometidas automaticamente" y "en curso"— y esa
     division describia **quien** decidio, no en que estado esta la pieza. Al
     aprobar una revision la fila saltaba de una lista a otra como si empezara un
     tramite nuevo, cuando lo que habia ocurrido es que se compro. Quien lo
     decidio se dice en la propia tarjeta, que es donde importa. */
  {
    id: "comprado",
    title: "Bought",
    hint: "Committed this run, by the system or by you. Nothing left to decide",
    open: false,
    muted: true,
    match: (i) => i.state !== REJECTED
      && (i.decision === "COMPRAR" || ADVANCED.includes(i.state)),
  },
  /* Lo rechazado tiene que seguir viendose. Con las reglas anteriores una fila
     rechazada no encajaba en ninguna banda y desaparecia de la pantalla: la
     decision se registraba en la base pero el turno se comportaba como si nunca
     hubiera existido, que es la peor forma de perder una traza. */
  {
    id: "rechazado",
    title: "Rejected",
    hint: "You turned these down. They stay here so the decision is not lost",
    open: false,
    muted: true,
    match: (i) => i.state === REJECTED,
  },
];

const openBands = new Set(BANDS.filter((band) => band.open).map((band) => band.id));
const openGroups = new Set(["decide:A", "escalar:A", "aplazado:A"]);

let onOpenCase = () => {};
let onChanged = () => {};

export function renderTurno(callback, refresh) {
  onOpenCase = callback;
  if (refresh) onChanged = refresh;
  renderHealth();
  paintMap();
  paintBands();
}

/* Llevar a los casos criticos: se abre su grupo, se despliega la banda que lo
   contiene y se desplaza hasta el primero. Abrirlo sin desplazar dejaria el
   cambio fuera de pantalla y pareceria que el boton no hizo nada. */
setJumpListener((level) => {
  openBands.add("decide");
  openBands.add("escalar");
  openGroups.add(`decide:${level}`);
  openGroups.add(`escalar:${level}`);
  paintBands();

  const target = document.querySelector(`.case[data-criticality="${level}"]`);
  if (!target) return;
  target.scrollIntoView({ behavior: "smooth", block: "center" });
  target.classList.add("case--flash");
  setTimeout(() => target.classList.remove("case--flash"), 1600);
});

/* ---------- El mapa ---------- */

const sum = (rows, key) => rows.reduce((total, row) => total + Number(row[key] || 0), 0);

/** Todo lo que caracteriza una planta sale de sus propias filas. */
function plantStats(city) {
  const rows = state.items.filter((item) => item.city_id === city.id);
  const open = rows.filter(
    (item) => item.state === PENDING && ["ESCALAR", "REVISAR", "APLAZADO"].includes(item.decision)
  );
  const escalated = open.filter((item) => item.decision === "ESCALAR").length;
  const deferred = open.filter((item) => item.decision === "APLAZADO").length;
  const critical = open.filter((item) => item.criticality === "A").length;

  return {
    id: city.id,
    name: city.name,
    short: city.name.split(",")[0],
    warehouse: rows[0] ? rows[0].warehouse_id : "",
    parts: rows.length,
    open: open.length,
    escalated,
    deferred,
    critical,
    level: escalated || critical ? "stop" : open.length ? "hold" : "go",
    stock: sum(rows, "on_hand_qty"),
    capacity: sum(rows, "inventory_max"),
    demand: sum(rows, "demand_monthly"),
    investment: sum(rows.filter((item) => item.decision === "COMPRAR"), "total_cost_usd"),
  };
}

/* El mapa abre con las dos plantas y no con ninguna: el estado por defecto de la
   pantalla es el conjunto, y obligar a elegir para ver algo seria pedir una
   decision antes de dar informacion.

   Pasar el raton sobre una planta la previsualiza; hacer clic la fija. Las dos
   cosas, no una: `hover` no existe en tactil ni con teclado, y dejar ahi la
   unica via de acceso es exactamente la violacion de WCAG 2.1 que este tipo de
   mapa suele cometer. El foco de teclado hace lo mismo que el raton. */
function paintMap() {
  const plants = (state.filters ? state.filters.cities : []).map(plantStats);

  drawMap(plants, {
    onSelect: (id) => {
      state.focusPlant = state.focusPlant === id ? null : id;
      state.hoverPlant = null;
      paintSide(plants);
      paintBands();
    },
    onPreview: (id) => {
      if (state.hoverPlant === id) return;
      state.hoverPlant = id;
      paintSide(plants);
    },
  });

  paintSide(plants);
}

/** Todo lo que cambia al senalar o fijar una planta, sin tocar el mapa. Es lo
 *  que permite que el clic llegue: rehacer los marcadores en cada movimiento del
 *  raton destruia el que estaba a punto de recibirlo. */
function paintSide(plants) {
  highlightPlant({ selected: state.focusPlant, preview: state.hoverPlant });

  const shown = state.hoverPlant || state.focusPlant;
  const picked = plants.find((plant) => plant.id === shown);
  document.getElementById("plant-card").innerHTML = picked
    ? plantCard(picked)
    : bothPlantsCard(plants);

  paintScopeBar(plants);
}

/** La ficha de las dos plantas juntas, que es el estado por defecto. Sin ella el
 *  hueco de la derecha nace vacio y parece que falta algo. */
function bothPlantsCard(plants) {
  const total = plants.reduce(
    (acc, plant) => ({
      open: acc.open + plant.open,
      critical: acc.critical + plant.critical,
      investment: acc.investment + plant.investment,
      parts: acc.parts + plant.parts,
    }),
    { open: 0, critical: 0, investment: 0, parts: 0 },
  );

  return `
    <div class="pcard pcard--both">
      <div class="pcard__head">
        <h3>Both plants</h3>
        <span class="meta mono">${total.parts} part-and-plant combinations</span>
      </div>
      <div class="pcard__stats">
        ${plants.map((plant) => `
          <div class="pstat">
            <span class="label">${escape(plant.short)}</span>
            <strong class="pstat__n pstat__n--${plant.level}">${plant.open}</strong>
            <span class="meta">${plant.open === 1 ? "case" : "cases"} waiting${
  plant.critical ? ` · ${plant.critical} critical` : ""}</span>
          </div>`).join("")}
        <div class="pstat">
          <span class="label">Committed</span>
          <strong class="pstat__n">${usdRound(total.investment)}</strong>
          <span class="meta">USD across both</span>
        </div>
      </div>
      <p class="meta pcard__hint">Hover a plant on the map to preview it, click to keep it.</p>
    </div>`;
}

/** La barra que dice sobre que se esta mirando y permite volver a las dos. */
function paintScopeBar(plants) {
  const host = document.getElementById("map-filter");
  const picked = plants.find((plant) => plant.id === state.focusPlant);

  host.innerHTML = `
    <button type="button" class="scope__btn${state.focusPlant ? "" : " scope__btn--on"}"
            data-scope="">Both plants</button>
    ${plants.map((plant) => `
      <button type="button" class="scope__btn${
  state.focusPlant === plant.id ? " scope__btn--on" : ""}"
              data-scope="${escape(plant.id)}">${escape(plant.short)}</button>`).join("")}
    ${picked ? `<span class="scope__note">showing ${escape(picked.short)} only</span>` : ""}`;

  host.querySelectorAll("[data-scope]").forEach((button) => {
    button.addEventListener("click", () => {
      state.focusPlant = button.dataset.scope || null;
      state.hoverPlant = null;
      paintSide(plants);
      paintBands();
    });
    button.addEventListener("mouseenter", () => {
      state.hoverPlant = button.dataset.scope || null;
      paintSide(plants);
    });
    button.addEventListener("mouseleave", () => {
      if (!state.hoverPlant) return;
      state.hoverPlant = null;
      paintSide(plants);
    });
  });
}

/* ---------- Las bandas ---------- */

/* El orden dentro de cada banda es por importe de compra, de mayor a menor: lo
   que mas dinero compromete se decide primero. */
const byAmount = (a, b) => (b.total_cost_usd || 0) - (a.total_cost_usd || 0);

function paintBands() {
  const host = document.getElementById("bands");
  const scope = state.focusPlant
    ? state.items.filter((item) => item.city_id === state.focusPlant)
    : state.items;

  host.innerHTML = "";
  BANDS.forEach((band) => {
    const rows = scope.filter(band.match).sort(byAmount);
    if (!rows.length) return;
    host.appendChild(bandBlock(band, rows));
  });

  const quiet = scope.filter((item) => item.decision === "NO_COMPRAR").length;
  if (quiet) host.appendChild(quietLine(quiet));
}

/** Las piezas sin nada que hacer son una frase, no una banda. Mil ciento
 *  diecisiete tarjetas plegadas siguen ocupando una linea de titulo, un contador
 *  y un sitio en el orden de lectura, y no aportan ninguna decision. */
function quietLine(count) {
  const line = document.createElement("p");
  line.className = "quiet";
  line.innerHTML = `<b>${count.toLocaleString("en-US")} parts</b> cover their minimum and need
    nothing this run. <button class="figure-link" type="button" data-goto-table>See them in
    All parts →</button>`;

  line.querySelector("[data-goto-table]").addEventListener("click", () => {
    document.querySelector('.navlink[data-view="tabla"]').click();
  });
  return line;
}

function bandBlock(band, rows) {
  const block = document.createElement("section");
  block.className = `band band--${band.id}${band.muted ? " band--muted" : ""}`;
  block.dataset.band = band.id;
  block.dataset.open = String(openBands.has(band.id));

  /* El contador de criticas solo aparece donde queda algo por hacer. Sobre lo
     ya comprometido decia "11 critical" en rojo encima de once compras
     resueltas, que es alarmar por un trabajo que ya esta hecho. */
  const critical = band.muted || band.id === "curso"
    ? 0
    : rows.filter((row) => row.criticality === "A").length;

  const head = document.createElement("button");
  head.type = "button";
  head.className = "band__head";
  head.innerHTML = `<span class="band__caret" aria-hidden="true">▶</span>
    <span class="band__text">
      <span class="band__title">${escape(band.title)}</span>
      <span class="band__hint">${escape(band.hint)}</span>
    </span>
    ${critical ? `<span class="band__crit">${critical} critical</span>` : ""}
    <span class="band__n">${rows.length}</span>`;
  head.addEventListener("click", () => {
    const next = block.dataset.open !== "true";
    if (next) openBands.add(band.id); else openBands.delete(band.id);
    block.dataset.open = String(next);
  });

  const body = document.createElement("div");
  body.className = "band__body";

  if (band.byCriticality) {
    groupByCriticality(band, rows).forEach((group) => body.appendChild(group));
  } else {
    rows.forEach((item) => body.appendChild(caseCard(item)));
  }

  block.append(head, body);
  return block;
}

/* Setenta y ocho casos con la misma causa no son setenta y ocho problemas. Se
   agrupan por criticidad y solo las que paran una linea llegan abiertas: el ojo
   va primero a lo que no se puede posponer, y las demas siguen a un clic. */
function groupByCriticality(band, rows) {
  return ["A", "B", "C"].flatMap((level) => {
    const members = rows.filter((row) => row.criticality === level);
    if (!members.length) return [];

    const key = `${band.id}:${level}`;
    const group = document.createElement("div");
    group.className = "group";
    group.dataset.open = String(openGroups.has(key));

    const head = document.createElement("button");
    head.type = "button";
    head.className = `group__head group__head--${level}`;
    head.innerHTML = `<span class="band__caret" aria-hidden="true">▶</span>
      <span class="group__letter">${level}</span>
      <span class="group__means">${escape(CRITICALITY_MEANS[level] || "")}</span>
      <span class="group__n">${members.length}</span>
      <span class="group__usd">${usdRound(
    members.reduce((total, row) => total + Number(row.total_cost_usd || 0), 0),
  )} USD</span>`;
    head.addEventListener("click", () => {
      const next = group.dataset.open !== "true";
      if (next) openGroups.add(key); else openGroups.delete(key);
      group.dataset.open = String(next);
    });

    const body = document.createElement("div");
    body.className = "group__body";
    members.forEach((item) => body.appendChild(caseCard(item)));

    group.append(head, body);
    return [group];
  });
}

/* ---------- La tarjeta ----------
 *
 * En la lista va compacta: quien es, donde, cuanto cuesta y los botones. Cuatro
 * lineas, porque la lista sirve para recorrer y comparar, no para estudiar un
 * caso.
 *
 * Al pasar el raton se abre una **vista previa centrada** con todo lo que la
 * tarjeta compacta no cabe: el riesgo redactado, el medidor con sus cifras y el
 * plan completo. Es el segundo nivel de tres —lista, previa, detalle— y evita
 * que haya que elegir entre una lista legible y una tarjeta informativa.
 */
function caseCard(item) {
  const card = document.createElement("article");
  const risk = riskLine(item);
  const call = verdictLine(item);
  const decided = !item.next_states || !item.next_states.length
    || item.state !== PENDING
    || item.decision === "COMPRAR" || item.decision === "NO_COMPRAR";

  card.className = `case case--${risk.level}${decided ? " case--done" : ""}`;
  card.tabIndex = 0;
  card.setAttribute("role", "button");
  card.dataset.sku = item.sku_id;
  card.dataset.city = item.city_id;
  card.dataset.criticality = item.criticality;

  const g = item.gauge;
  card.innerHTML = `
    <span class="case__crit case__crit--${escape(item.criticality)}"
          title="Criticality ${escape(item.criticality)}">${escape(item.criticality)}</span>

    <span class="case__id">
      <span class="case__sku">${escape(item.sku_id)}</span>
      <span class="case__name">${escape(item.description)}</span>
    </span>

    <span class="case__bar" aria-hidden="true">
      <span class="case__bar__fill case__bar__fill--${g.zone}"
            style="width:${Math.min(Math.max(g.fill_pct, 0), 100)}%"></span>
      <span class="case__bar__min"
            style="left:${Math.min(Math.max(g.minimum_pct, 0), 100)}%"></span>
    </span>

    <span class="case__plant">${escape(item.city_name.split(",")[0])}</span>
    <span class="case__usd">${item.total_cost_usd
    ? `${usdRound(item.total_cost_usd)} USD` : ""}</span>

    <span class="case__end">
      ${decideBar(item, decided, call)}
    </span>`;

  const open = () => onOpenCase(item);
  card.addEventListener("click", open);
  card.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      open();
    }
  });

  /* La previa se abre al senalar y al recibir el foco. Las dos, porque una
     previa que solo existe bajo el cursor no existe para quien navega con
     tabulador. */
  card.addEventListener("mouseenter", () => showPeek(item));
  card.addEventListener("focus", () => showPeek(item));
  card.addEventListener("mouseleave", hidePeek);
  card.addEventListener("blur", hidePeek);

  /* Aprobar se resuelve en la tarjeta porque no necesita nada mas. Rechazar
     exige motivo, y el motivo vive en el panel: llevar alli es mas honesto que
     inventar un rechazo sin causa registrada. */
  const approve = card.querySelector("[data-approve]");
  if (approve) {
    approve.addEventListener("click", async (event) => {
      event.stopPropagation();
      approve.disabled = true;
      hidePeek();
      try {
        await applyState(item, "Aprobado");
        toast(`${item.sku_id} · bought`);
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
      hidePeek();
      onOpenCase(item);
    });
  }

  return card;
}

/* ---------- La vista previa ----------
 *
 * Va centrada y flotando sobre la lista. Es deliberado: anclarla junto a la
 * tarjeta la dejaria colgando fuera de pantalla en las de abajo, y moverla con
 * el raton la haria perseguir al cursor. En el centro siempre cabe y siempre
 * esta en el mismo sitio, que es lo que permite leerla sin buscarla.
 *
 * No abre nada. El detalle sigue a un clic —sobre la tarjeta o sobre la propia
 * previa— y esa separacion es lo que la hace util: se puede recorrer la lista
 * leyendo casos sin abrir ni cerrar paneles.
 */
let peekFor = null;
let peekTimer = null;

function peekHost() {
  let host = document.getElementById("case-peek");
  if (!host) {
    host = document.createElement("div");
    host.id = "case-peek";
    host.className = "peek";
    host.hidden = true;
    document.body.appendChild(host);
    host.addEventListener("mouseenter", () => clearTimeout(peekTimer));
    host.addEventListener("mouseleave", hidePeek);
    host.addEventListener("click", () => {
      if (peekFor) onOpenCase(peekFor);
      hidePeek();
    });
  }
  return host;
}

function showPeek(item) {
  clearTimeout(peekTimer);
  peekFor = item;

  const risk = riskLine(item);
  const plan = planLine(item);
  const call = verdictLine(item);
  const host = peekHost();

  host.className = `peek peek--${risk.level}`;
  host.hidden = false;
  host.innerHTML = `
    <header class="peek__head">
      <span class="case__crit case__crit--${escape(item.criticality)}">
        ${escape(item.criticality)}</span>
      <span class="peek__id">
        <b>${escape(item.sku_id)}</b>
        <span>${escape(item.description)}</span>
      </span>
      <span class="case__plant">${escape(item.city_name.split(",")[0])}</span>
    </header>

    <div class="peek__block">
      <span class="label">Risk · ${escape(CRITICALITY_MEANS[item.criticality] || "")}</span>
      <p class="case__risk">${risk.text}</p>
      ${gauge(item)}
    </div>

    <div class="peek__block">
      <span class="label">${escape(plan.label)}</span>
      <p class="case__plan">${plan.text}</p>
    </div>

    <footer class="peek__foot">
      ${call ? `<span class="case__call case__call--${call.tone}">${
    escape(call.headline)}</span>` : ""}
      <span class="case__more">Click to open the full detail <i>→</i></span>
    </footer>`;
}

function hidePeek() {
  clearTimeout(peekTimer);
  peekTimer = setTimeout(() => {
    const host = document.getElementById("case-peek");
    if (host) host.hidden = true;
    peekFor = null;
  }, 140);
}

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") hidePeek();
});

/** Quien tomo la decision y en que punto va, para las filas ya resueltas.
 *
 *  Con una sola banda de compradas, esta linea es la que distingue lo que el
 *  sistema comprometio de lo que aprobo una persona. Sin ella la fusion de las
 *  dos bandas perderia informacion en vez de simplificarla.
 */
function provenance(item) {
  if (item.state === REJECTED) {
    const why = item.rejection_reason ? ` · ${escape(item.rejection_reason)}` : "";
    return `<span class="case__done case__done--stop">Rejected${why}</span>`;
  }
  if (item.state === "Contactado proveedor") {
    return '<span class="case__done">Supplier contacted</span>';
  }
  if (item.state === "Orden confirmada") {
    return '<span class="case__done">Order confirmed</span>';
  }
  if (item.decided_by_system) {
    return '<span class="case__done">Bought — committed by the system</span>';
  }
  if (ADVANCED.includes(item.state)) {
    return '<span class="case__done">Bought — approved by you</span>';
  }
  return "";
}

/** Barra de decision. Lo ya resuelto no ofrece botones: una compra automatica se
 *  compromete sola, y ofrecer "aprobar" sobre algo que no espera aprobacion
 *  invita a un clic que no significa nada. */
/** Barra de decision. Lo ya resuelto no ofrece botones: una compra automatica se
 *  compromete sola, y ofrecer "aprobar" sobre algo que no espera aprobacion
 *  invita a un clic que no significa nada.
 *
 *  El veredicto se reduce aqui a su titular —"I would buy"— y el razonamiento
 *  que lo sostiene vive en el detalle. En la tarjeta ocupaba tres lineas para
 *  argumentar una decision que de todos modos no se toma leyendo: se toma
 *  mirando el riesgo y el precio, que estan justo encima. */
function decideBar(item, decided, call) {
  const next = item.next_states || [];
  const canApprove = !decided && next.includes("Aprobado");
  const canReject = !decided && next.includes("Rechazado");
  const hint = call
    ? `<span class="case__call case__call--${call.tone}">${escape(call.headline)}</span>`
    : "";

  if (!canApprove && !canReject) {
    return `<footer class="case__foot">
      ${provenance(item) || hint}
      <span class="case__more">See the detail <i>→</i></span>
    </footer>`;
  }

  return `
    <footer class="case__foot case__foot--decide">
      ${hint}
      ${canApprove ? '<button class="btn btn--go" type="button" data-approve>Approve</button>' : ""}
      ${canReject ? '<button class="btn btn--stop" type="button" data-reject>Reject…</button>' : ""}
      <span class="case__more">See the detail <i>→</i></span>
    </footer>`;
}
