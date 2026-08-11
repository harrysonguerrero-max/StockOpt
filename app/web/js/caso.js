/* El caso de una pieza en una planta, contado como una consecuencia.
 *
 * Antes esto era una fila desplegada dentro de la tabla, comprimida en dos
 * columnas y con treinta y nueve filas alrededor tirando de la atencion. Aqui
 * ocupa su propia superficie y sigue el orden en que se forma la decision:
 * que consume, que va a consumir, cuanto necesita en bodega y a quien comprarle.
 *
 * La justificacion redactada queda plegada al final. Llegaba de golpe, noventa
 * palabras antes de haber visto un solo dato, y era lo que hacia que la
 * pantalla pareciera escrita por una maquina en lugar de mostrada.
 */

import { applyState, loadExplanation, loadHistory, state, toast } from "./api.js";
import {
  confidence, decimal, escape, leadTime, months, pattern, price, source, units, usd,
} from "./format.js";
import { critChip, gauge, runway } from "./ui.js";
import { spark } from "./spark.js";

const FLOW = ["Pendiente aprobacion", "Aprobado", "Contactado proveedor", "Orden confirmada"];
const FLOW_SHORT = ["Pendiente", "Aprobado", "Contactado", "Confirmada"];

const ACTION_LABEL = {
  "Aprobado": "Aprobar",
  "Contactado proveedor": "Marcar proveedor contactado",
  "Orden confirmada": "Confirmar orden",
  "Pendiente aprobacion": "Reabrir",
};

let onChange = () => {};

export function setCaseListener(callback) { onChange = callback; }

export function closeCase() {
  document.getElementById("panel-host").innerHTML = "";
  state.openKey = null;
  document.removeEventListener("keydown", escapeToClose);
}

function escapeToClose(event) {
  if (event.key === "Escape") closeCase();
}

export function openCase(item) {
  const host = document.getElementById("panel-host");
  state.openKey = `${item.sku_id}|${item.city_id}`;

  host.innerHTML = `
    <div class="scrim"></div>
    <aside class="panel" role="dialog" aria-modal="true" aria-label="Detalle de ${escape(item.sku_id)}">
      <div class="panel__head">
        <button class="panel__close" type="button" aria-label="Cerrar">×</button>
        <div class="panel__where">
          <span class="panel__sku">${escape(item.sku_id)}</span>
          ${critChip(item)}
          <span class="panel__city">${escape(item.city_name)} · ${escape(item.warehouse_id)}</span>
        </div>
        <h2 class="title">${escape(item.description)}</h2>
      </div>
      <div class="panel__body">
        ${flowBlock(item)}
        ${stepConsume(item)}
        ${stepForecast(item)}
        ${stepStock(item)}
        ${stepSupplier(item)}
        ${foldAssumptions(item)}
        ${foldExplanation(item)}
      </div>
    </aside>`;

  host.querySelector(".scrim").addEventListener("click", closeCase);
  host.querySelector(".panel__close").addEventListener("click", closeCase);
  document.addEventListener("keydown", escapeToClose);

  wireFolds(host);
  wireActions(host, item);
  fillHistory(host, item);
}

/* ---------- Flujo de aprobacion ----------
 * Cuatro estados dibujados como secuencia, con el boton de la accion siguiente
 * pegado a la barra. Antes era un punto de color y una palabra en la ultima
 * columna: no se veia ni donde estaba la pieza ni cuanto le faltaba.
 */

function flowBlock(item) {
  const rejected = item.state === "Rechazado";
  const current = rejected ? 0 : Math.max(0, FLOW.indexOf(item.state));

  const steps = FLOW.map((name, i) => {
    const cls = i < current ? "flow__step--done" : i === current ? "flow__step--now" : "";
    return `<div class="flow__step ${cls}">${FLOW_SHORT[i]}</div>`;
  }).join("");

  const buttons = (item.next_states || [])
    .filter((target) => target !== "Rechazado")
    .map((target) => `<button class="btn ${target === "Aprobado" ? "btn--go" : "btn--quiet"}"
        type="button" data-go="${escape(target)}">${ACTION_LABEL[target] || target}</button>`)
    .join("");

  const rejectButton = (item.next_states || []).includes("Rechazado")
    ? '<button class="btn btn--stop" type="button" data-reject="1">Rechazar</button>' : "";

  const done = !buttons && !rejectButton
    ? `<p class="meta">${rejected ? "Rechazada." : "Esta orden ya está confirmada."}</p>` : "";

  return `
    <div class="flow ${rejected ? "flow--rejected" : ""}">
      <div class="flow__track">${steps}</div>
      ${rejected && item.rejection_reason
        ? `<p class="step__aside">Rechazado: ${escape(item.rejection_reason)}${
            item.comment ? ` — ${escape(item.comment)}` : ""}</p>` : ""}
      <div class="flow__actions">${buttons}${rejectButton}${done}</div>
      <div class="reject" data-open="false">
        <select data-field="reason">
          ${(state.filters?.rejection_reasons || [])
            .map((r) => `<option value="${escape(r)}">${escape(r)}</option>`).join("")}
        </select>
        <textarea data-field="comment" placeholder="Detalle opcional para el registro"></textarea>
        <button class="btn btn--stop" type="button" data-confirm-reject="1">Confirmar rechazo</button>
      </div>
    </div>`;
}

/* ---------- Los cuatro pasos ---------- */

function step(n, title, body) {
  return `<section class="step">
    <div class="step__head"><span class="step__n">${n}</span>
      <span class="step__title">${title}</span></div>
    ${body}
  </section>`;
}

function stepConsume(item) {
  return step(1, "Qué consume", `
    <div data-spark>&nbsp;</div>
    <p class="step__read">
      <b>${decimal(item.demand_monthly)}</b> unidades al mes de media.
      Con lo que hay en bodega, ${runway(item)} de consumo.
    </p>
    <p class="step__aside">Patrón ${pattern(item.pattern)}.</p>`);
}

function stepForecast(item) {
  const c = confidence(item.confidence);
  return step(2, "Qué va a consumir", `
    <p class="step__read" data-forecast>
      Proyección de <b>${units(item.demand_monthly)}</b> unidades para el próximo mes.
    </p>
    <span class="pill-row">
      <span class="pill">Patrón ${pattern(item.pattern)}</span>
      <span class="pill pill--${c.tone}">Confianza ${c.word}</span>
      <span class="pill">${source(item.forecast_source)}</span>
    </span>
    <p class="step__aside" style="margin-top:12px">
      <button class="figure-link" data-goto-model>¿Confío en esta proyección?</button>
    </p>`);
}

function stepStock(item) {
  const gap = item.inventory_min - item.on_hand_qty;
  const read = gap > 0
    ? `Faltan <b>${units(gap)}</b> ${gap === 1 ? "unidad" : "unidades"} para llegar al mínimo.`
    : `Está <b>${units(-gap)}</b> por encima del mínimo.`;

  return step(3, "Cuánto necesita en bodega", `
    ${gauge(item, "gauge--lg")}
    <p class="step__read">${read}</p>
    <p class="step__aside" data-policy>
      El mínimo cubre el consumo durante el plazo de entrega más un colchón de seguridad.
    </p>`);
}

function stepSupplier(item) {
  if (item.decision === "NO_COMPRAR") {
    return step(4, "A quién comprarle", `
      <p class="step__read">Todavía no hace falta.</p>
      <p class="step__aside">Habrá que reponer cuando el stock baje de
        ${units(item.inventory_min)} unidades, a este ritmo dentro de
        ${months(Math.max(0, item.on_hand_qty - item.inventory_min)
                 / Math.max(item.demand_monthly, 0.01))}.</p>`);
  }

  const offers = (item.alternatives || []).map((offer) => `
    <div class="offer ${offer.chosen ? "offer--chosen" : ""}">
      <span class="offer__name">${escape(offer.supplier_name)}${
        offer.chosen ? '<span class="offer__tag">elegido</span>' : ""}</span>
      <span class="offer__total">${usd(offer.total_cost_usd)} USD</span>
      <span class="offer__meta">
        ${price(offer.unit_price_usd)} por unidad · lote mínimo ${units(offer.moq)}
        <span class="synthetic" title="Campo generado por el build">gen</span>
        · flete ${usd(offer.freight_cost_usd)} USD · entrega en ${leadTime(offer.lead_time_days)}
      </span>
    </div>`).join("");

  const gain = item.alternatives && item.alternatives.length > 1
    ? `<p class="step__aside">Gana por ${usd(
        item.alternatives[1].total_cost_usd - item.alternatives[0].total_cost_usd
      )} USD sobre el siguiente.</p>` : "";

  return step(4, "A quién comprarle",
    (item.decision === "REVISAR" ? fork(item) : "")
    + `<div class="offers">${offers}</div>${gain}`);
}

/* ---------- La bifurcacion de REVISAR ----------
 * Es el caso que exige a una persona, y no es una recomendacion sino una
 * pregunta. Antes se veia igual que una compra, con una etiqueta ambar.
 */

function fork(item) {
  const shelfMonths = item.shelf_life_days / 30.4;
  const caduca = item.coverage_months > shelfMonths;
  const gap = Math.max(0, item.inventory_min - item.on_hand_qty);
  const agota = months(item.on_hand_qty / Math.max(item.demand_monthly, 0.01));

  return `
    <p class="step__read" style="margin-bottom:14px">
      El sistema no puede resolverlo: el lote mínimo de
      ${escape(item.supplier_name)} es <b>${units(item.recommended_qty)}</b>
      y en bodega caben <b>${units(item.inventory_max)}</b>.
    </p>
    <div class="fork">
      <div class="fork__opt fork__opt--warn">
        <p class="fork__title">Comprar ${units(item.recommended_qty)}</p>
        <span class="fork__figure">${usd(item.total_cost_usd)} USD</span>
        <ul class="fork__list">
          <li>Deja ${months(item.coverage_months)} de inventario</li>
          <li>Sobran ${units(Math.max(0, item.recommended_qty - item.inventory_max))} sobre la capacidad</li>
          <li>${caduca
            ? `Caduca antes de consumirse (vida útil ${months(shelfMonths)})`
            : `Vida útil de ${months(shelfMonths)}: no caduca`}</li>
        </ul>
      </div>
      <div class="fork__opt">
        <p class="fork__title">No comprar</p>
        <span class="fork__figure">${gap ? `−${units(gap)}` : "0"}</span>
        <ul class="fork__list">
          <li>${gap ? `Por debajo del mínimo operativo` : "En el mínimo operativo"}</li>
          <li>Criticidad ${escape(item.criticality)}</li>
          <li>Al ritmo actual se agota en ${agota}</li>
        </ul>
      </div>
    </div>`;
}

/* ---------- Plegables ---------- */

function foldAssumptions(item) {
  const list = (item.explanation.assumptions || [])
    .map((text) => `<li>${escape(text)}</li>`).join("");
  return `<div class="fold" data-open="false">
    <button class="fold__head" type="button"><span class="fold__caret">▶</span>
      Supuestos aplicados <span class="band__n">${item.explanation.assumptions.length}</span></button>
    <div class="fold__body"><ul class="assumptions">${list}</ul></div>
  </div>`;
}

function foldExplanation(item) {
  return `<div class="fold" data-open="false" data-explain="1">
    <button class="fold__head" type="button"><span class="fold__caret">▶</span>
      Cómo lo explicaría el sistema</button>
    <div class="fold__body">
      <p class="prose"><strong>${escape(item.explanation.headline)}</strong></p>
      <p class="prose" data-body>${escape(item.explanation.body)}</p>
    </div>
  </div>`;
}

/* ---------- Conexiones ---------- */

function wireFolds(host) {
  host.querySelectorAll(".fold").forEach((fold) => {
    fold.querySelector(".fold__head").addEventListener("click", () => {
      const open = fold.dataset.open !== "true";
      fold.dataset.open = String(open);
      if (open && fold.dataset.explain) requestExplanation(fold);
    });
  });
}

function wireActions(host, item) {
  host.querySelectorAll("[data-go]").forEach((button) => {
    button.addEventListener("click", () => send(item, button.dataset.go));
  });

  const panel = host.querySelector(".reject");
  const toggle = host.querySelector("[data-reject]");
  if (toggle) {
    toggle.addEventListener("click", () => {
      panel.dataset.open = panel.dataset.open === "true" ? "false" : "true";
    });
  }

  const confirm = host.querySelector("[data-confirm-reject]");
  if (confirm) {
    confirm.addEventListener("click", () => send(item, "Rechazado", {
      rejection_reason: panel.querySelector('[data-field="reason"]').value,
      comment: panel.querySelector('[data-field="comment"]').value,
    }));
  }

  const link = host.querySelector("[data-goto-model]");
  if (link) {
    link.addEventListener("click", () => {
      closeCase();
      document.querySelector('.navlink[data-view="modelo"]').click();
    });
  }
}

async function send(item, newState, extra) {
  try {
    await applyState(item, newState, extra);
    toast(`${item.sku_id} · ${newState}`);
    closeCase();
    await onChange();
  } catch (error) {
    toast(error.message, true);
  }
}

/** La serie llega despues de pintar el panel: el caso se abre al instante y el
 *  grafico entra cuando esta, en lugar de retener toda la pantalla. */
async function fillHistory(host, item) {
  const slot = host.querySelector("[data-spark]");
  try {
    const data = await loadHistory(item.sku_id, item.city_id);
    if (!slot.isConnected) return;
    slot.innerHTML = spark(data.history, data.forecast);

    const f = data.forecast;
    const target = host.querySelector("[data-forecast]");
    if (target && f.q50 != null) {
      target.innerHTML = `Proyección de <b>${units(f.q50)}</b> unidades para el próximo mes`
        + (f.q25 != null && f.q75 != null
          ? `, entre <b>${units(f.q25)}</b> y <b>${units(f.q75)}</b> en el rango probable.` : ".");
    }

    const policy = host.querySelector("[data-policy]");
    if (policy && data.policy.demand_lead_time != null) {
      policy.innerHTML = `El mínimo de ${units(data.policy.inventory_min)} son `
        + `${units(data.policy.demand_lead_time)} unidades de consumo durante el plazo de entrega `
        + `(${leadTime(data.policy.lead_time_days)}) más ${units(data.policy.safety_stock)} `
        + `de colchón para la variabilidad.`;
    }
  } catch (error) {
    if (slot.isConnected) slot.innerHTML = `<p class="step__aside">${escape(error.message)}</p>`;
  }
}

/** La redaccion del modelo se pide solo cuando alguien abre el plegable. */
async function requestExplanation(fold) {
  const item = state.items.find(
    (row) => `${row.sku_id}|${row.city_id}` === state.openKey
  );
  if (!item || item.explanationTried) return;
  item.explanationTried = true;

  const body = fold.querySelector("[data-body]");
  const flag = document.createElement("span");
  flag.className = "writing";
  flag.textContent = "Redactando con el modelo";
  body.after(flag);

  try {
    const fresh = await loadExplanation(item.sku_id, item.city_id);
    item.explanation = fresh;
    if (body.isConnected && fresh.body) body.textContent = fresh.body;
  } catch (error) {
    /* Se queda la version deterministica, que ya esta en pantalla. */
  } finally {
    if (flag.isConnected) flag.remove();
  }
}
