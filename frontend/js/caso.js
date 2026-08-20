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
const FLOW_SHORT = ["Pending", "Approved", "Contacted", "Confirmed"];

const ACTION_LABEL = {
  "Aprobado": "Approve",
  "Contactado proveedor": "Mark supplier contacted",
  "Orden confirmada": "Confirm order",
  "Pendiente aprobacion": "Reopen",
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
    <aside class="panel" role="dialog" aria-modal="true" aria-label="Detail for ${escape(item.sku_id)}">
      <div class="panel__head">
        <button class="panel__close" type="button" aria-label="Close">×</button>
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
    ? '<button class="btn btn--stop" type="button" data-reject="1">Reject</button>' : "";

  const done = !buttons && !rejectButton
    ? `<p class="meta">${rejected ? "Rejected." : "This order is already confirmed."}</p>` : "";

  return `
    <div class="flow ${rejected ? "flow--rejected" : ""}">
      <div class="flow__track">${steps}</div>
      ${rejected && item.rejection_reason
        ? `<p class="step__aside">Rejected: ${escape(item.rejection_reason)}${
            item.comment ? ` — ${escape(item.comment)}` : ""}</p>` : ""}
      <div class="flow__actions">${buttons}${rejectButton}${done}</div>
      <div class="reject" data-open="false">
        <select data-field="reason">
          ${(state.filters?.rejection_reasons || [])
            .map((r) => `<option value="${escape(r)}">${escape(r)}</option>`).join("")}
        </select>
        <textarea data-field="comment" placeholder="Optional detail for the record"></textarea>
        <button class="btn btn--stop" type="button" data-confirm-reject="1">Confirm rejection</button>
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
  return step(1, "What it consumes", `
    <div data-spark>&nbsp;</div>
    <p class="step__read">
      <b>${decimal(item.demand_monthly)}</b> units per month on average.
      At that rate, what is on the shelf lasts ${runway(item)}.
    </p>
    <p class="step__aside">${pattern(item.pattern)} pattern.</p>`);
}

function stepForecast(item) {
  const c = confidence(item.confidence);
  return step(2, "What it will consume", `
    <p class="step__read" data-forecast>
      Forecast of <b>${units(item.demand_monthly)}</b> units for next month.
    </p>
    <span class="pill-row">
      <span class="pill">${pattern(item.pattern)} pattern</span>
      <span class="pill pill--${c.tone}">${c.word} confidence</span>
      <span class="pill">${source(item.forecast_source)}</span>
    </span>
    <p class="step__aside" style="margin-top:12px">
      <button class="figure-link" data-goto-model>Can I trust this forecast?</button>
    </p>`);
}

function stepStock(item) {
  const gap = item.inventory_min - item.on_hand_qty;
  const read = gap > 0
    ? `<b>${units(gap)}</b> ${gap === 1 ? "unit" : "units"} short of the reorder point.`
    : `<b>${units(-gap)}</b> above the reorder point.`;

  return step(3, "How much it needs on the shelf", `
    ${gauge(item, "gauge--lg")}
    <p class="step__read">${read}</p>
    <p class="step__aside" data-policy>
      The reorder point covers consumption during the lead time plus a safety buffer.
    </p>
    ${lotBlock(item)}`);
}

function stepSupplier(item) {
  if (item.decision === "NO_COMPRAR") {
    return step(4, "Who to buy from", `
      <p class="step__read">Not needed yet.</p>
      <p class="step__aside">A replenishment is due when stock falls below
        ${units(item.inventory_min)} units, which at this rate happens in
        ${months(Math.max(0, item.on_hand_qty - item.inventory_min)
                 / Math.max(item.demand_monthly, 0.01))}.</p>`);
  }

  const offers = (item.alternatives || []).map((offer) => `
    <div class="offer ${offer.chosen ? "offer--chosen" : ""}">
      <span class="offer__name">${escape(offer.supplier_name)}${
        offer.chosen ? '<span class="offer__tag">chosen</span>' : ""}</span>
      <span class="offer__total">${usd(offer.total_cost_usd)} USD</span>
      <span class="offer__meta">
        ${price(offer.unit_price_usd)} per unit · minimum lot ${units(offer.moq)}
        <span class="synthetic" title="Field generated by the build">gen</span>
        · freight ${usd(offer.freight_cost_usd)} USD · delivery in ${leadTime(offer.lead_time_days)}
      </span>
    </div>`).join("");

  const gain = item.alternatives && item.alternatives.length > 1
    ? `<p class="step__aside">It wins by ${usd(
        item.alternatives[1].total_cost_usd - item.alternatives[0].total_cost_usd
      )} USD over the next best.</p>` : "";

  return step(4, "Who to buy from",
    (item.decision === "REVISAR" ? fork(item) : "")
    + (item.decision === "ESCALAR" ? escalateBlock(item) : "")
    + `<div class="offers">${offers}</div>${gain}`);
}

/* ---------- De donde sale la cantidad ----------
 * El nivel de reposicion no es una cobertura en meses elegida a dedo sino la
 * cantidad economica de pedido. Mostrarla descompuesta es lo que permite
 * defenderla: se ve que el flete tira hacia arriba y el valor de la pieza hacia
 * abajo, y que el tope de obsolescencia esta ahi para cuando la formula se pasa.
 */

function lotBlock(item) {
  if (!item.eoq_units) return "";

  const capped = item.eoq_units >= Math.floor(item.demand_monthly * 6);
  return `
    <div class="lot">
      <p class="lot__title">Where the order quantity comes from</p>
      <div class="lot__terms">
        <span class="lot__term">
          <span class="label">Freight per order</span>
          <b>${usd(item.order_cost_usd)} USD</b>
        </span>
        <span class="lot__op">vs</span>
        <span class="lot__term">
          <span class="label">Holding cost</span>
          <b>${price(item.holding_cost_usd)} USD</b>
          <span class="meta">per unit and year</span>
        </span>
        <span class="lot__op">→</span>
        <span class="lot__term lot__term--out">
          <span class="label">Economic order quantity</span>
          <b>${units(item.eoq_units)} units</b>
        </span>
      </div>
      <p class="step__aside">
        Wilson's formula balances paying freight more often against leaving capital
        idle on the shelf. Refill level = reorder point ${units(item.inventory_min)}
        + lot ${units(item.eoq_units)} = <b>${units(item.inventory_max)}</b> units.
        ${capped ? "The six-month obsolescence cap is what limits this lot." : ""}
      </p>
    </div>`;
}

/* ---------- La escalada ----------
 * No es una recomendacion sino una peticion. El optimizador ya resolvio que
 * comprar y a quien; lo que falta es dinero que solo puede autorizar alguien
 * mas, y la pantalla tiene que decir cuanto y contra que riesgo.
 */

function escalateBlock(item) {
  return `
    <div class="escalate">
      <p class="escalate__title">This one needs a budget decision</p>
      <p class="step__read">
        Criticality <b>${escape(item.criticality)}</b>: running out stops a line.
        The model funds every critical replenishment before anything else and
        stretches the budget by the authorised overrun to do it. This one still
        does not fit.
      </p>
      <div class="escalate__figures">
        <span><span class="label">Extra budget needed</span>
          <b>${usd(item.total_cost_usd)} USD</b></span>
        <span><span class="label">Stockout it prevents</span>
          <b>${usd(item.stockout_cost_usd)} USD</b></span>
        <span><span class="label">Net if approved</span>
          <b>${usd(item.net_benefit_usd)} USD</b></span>
      </div>
    </div>`;
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
      The system cannot settle this one: the minimum lot at
      ${escape(item.supplier_name)} is <b>${units(item.recommended_qty)}</b>
      and the allowed maximum is <b>${units(item.max_allowed_qty)}</b>.
    </p>
    <div class="fork">
      <div class="fork__opt fork__opt--warn">
        <p class="fork__title">Buy ${units(item.recommended_qty)}</p>
        <span class="fork__figure">${usd(item.total_cost_usd)} USD</span>
        <ul class="fork__list">
          <li>Leaves ${months(item.coverage_months)} of stock</li>
          <li>${units(Math.max(0, item.recommended_qty - item.max_allowed_qty))} over the allowed maximum</li>
          <li>${caduca
            ? `Expires before it is consumed (shelf life ${months(shelfMonths)})`
            : `Shelf life of ${months(shelfMonths)}: it does not expire`}</li>
        </ul>
      </div>
      <div class="fork__opt">
        <p class="fork__title">Do not buy</p>
        <span class="fork__figure">${gap ? `−${units(gap)}` : "0"}</span>
        <ul class="fork__list">
          <li>${gap ? "Below the reorder point" : "At the reorder point"}</li>
          <li>Criticality ${escape(item.criticality)}</li>
          <li>At the current rate it runs out in ${agota}</li>
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
      Assumptions applied <span class="band__n">${item.explanation.assumptions.length}</span></button>
    <div class="fold__body"><ul class="assumptions">${list}</ul></div>
  </div>`;
}

function foldExplanation(item) {
  return `<div class="fold" data-open="false" data-explain="1">
    <button class="fold__head" type="button"><span class="fold__caret">▶</span>
      How the system would explain it</button>
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
    /* Un rechazo del servidor significa que el panel muestra un estado que ya
       no es el de la base. Se cierra y se recarga para que los botones vuelvan
       a corresponderse con lo que de verdad se puede hacer. */
    toast(error.message, true);
    closeCase();
    await onChange();
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
      target.innerHTML = `Forecast of <b>${units(f.q50)}</b> units for next month`
        + (f.q25 != null && f.q75 != null
          ? `, between <b>${units(f.q25)}</b> and <b>${units(f.q75)}</b> in the likely range.` : ".");
    }

    const policy = host.querySelector("[data-policy]");
    if (policy && data.policy.demand_lead_time != null) {
      policy.innerHTML = `The reorder point of ${units(data.policy.inventory_min)} is `
        + `${units(data.policy.demand_lead_time)} units of consumption during the lead time `
        + `(${leadTime(data.policy.lead_time_days)}) plus ${units(data.policy.safety_stock)} `
        + `of buffer for the variability.`;
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
  flag.textContent = "Writing with the model";
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
