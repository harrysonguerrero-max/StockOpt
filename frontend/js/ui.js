/* Piezas visuales y lecturas que comparten varias vistas. */

import { decimal, escape, leadTime, months, pattern, units, usd } from "./format.js";

export const PENDING = "Pendiente aprobacion";
export const ADVANCED = ["Aprobado", "Contactado proveedor", "Orden confirmada"];

/* El semaforo de la pantalla. Las cinco decisiones no piden lo mismo y la
   interfaz tiene que decirlo antes que ninguna otra cosa:

     ESCALAR      pieza critica que no cabe ni con el excedente; decide gerencia
     REVISAR      hay una tension que el solver no puede zanjar; decide alguien
     APLAZADO     procedia y la freno el presupuesto discrecional
     COMPRAR      el solver la resolvio sin ambigüedad; no requiere criterio
     NO_COMPRAR   no hay nada que hacer

   De ahi que el verde sea el color mas callado: marca lo que ya esta resuelto.
   El ambar y el rojo son los que reclaman, y el azul de ESCALAR se separa de
   los tres porque no es trabajo de comprador sino de quien firma presupuesto. */
const SEMAPHORE = {
  ESCALAR: { level: "escalate", label: "Needs budget" },
  COMPRAR: { level: "go", label: "Automatic" },
  REVISAR: { level: "hold", label: "Your call" },
  APLAZADO: { level: "stop", label: "Deferred" },
  NO_COMPRAR: { level: "off", label: "No action" },
};

export const semaphore = (item) => SEMAPHORE[item.decision] || SEMAPHORE.NO_COMPRAR;

/** Medidor de existencias: stock sobre la escala del nivel de reposicion, con
 *  marca en el punto de reorden. Codifica en una sola lectura la tension que
 *  decide cada caso. */
export function gauge(item, size = "") {
  const g = item.gauge;
  return `
    <span class="gauge ${size}">
      <span class="gauge__track">
        <span class="gauge__fill gauge__fill--${g.zone}" style="width:${g.fill_pct}%"></span>
        <span class="gauge__min" style="left:${g.minimum_pct}%" title="Reorder point"></span>
      </span>
      <span class="gauge__read">
        <b>${units(item.on_hand_qty)}</b> on hand · reorder at <b>${units(item.inventory_min)}</b>
        · refill to <b>${units(item.inventory_max)}</b>
      </span>
    </span>`;
}

/** La accion en forma de verbo. La etiqueta COMPRAR / REVISAR es el nombre
 *  interno de la decision, no lo que la persona tiene que hacer. */
export function actionLine(item) {
  if (item.decision === "ESCALAR") {
    return { text: `Escalate: ${usd(item.total_cost_usd)} USD of extra budget`, tone: "escalate" };
  }
  if (item.decision === "COMPRAR") {
    return { text: `Buy ${units(item.recommended_qty)} — automatic`, tone: "go" };
  }
  if (item.decision === "REVISAR") {
    return { text: `Decide: minimum lot of ${units(item.recommended_qty)}`, tone: "hold" };
  }
  if (item.decision === "APLAZADO") {
    return { text: `Deferred: ${usd(item.total_cost_usd)} USD`, tone: "stop" };
  }
  return { text: "No action", tone: "none" };
}

/* En los casos que exigen criterio, el sistema no se calla: dice que haria y
   por que, y deja la decision. El beneficio neto ya lo calcula el optimizador
   —lo que cuesta el quiebre que se evita, menos lo que cuesta evitarlo— asi que
   la recomendacion sale del dato y no de una regla inventada aqui. La vida util
   manda por encima: comprar algo que caduca antes de consumirse no se recomienda
   aunque el numero salga a favor. */
export function recommendation(item) {
  if (item.decision !== "REVISAR") return null;

  const shelfMonths = item.shelf_life_days / 30.4;
  const expires = item.coverage_months > shelfMonths;
  const benefit = Number(item.net_benefit_usd || 0);

  if (expires) {
    return {
      buy: false,
      headline: "I would not buy",
      why: `The lot leaves ${months(item.coverage_months)} of stock and the part expires `
        + `after ${months(shelfMonths)}.`,
    };
  }
  if (benefit > 0) {
    return {
      buy: true,
      headline: "I would buy",
      why: `It prevents ${usd(item.stockout_cost_usd)} USD of stockout and costs `
        + `${usd(item.total_cost_usd)}: ${usd(benefit)} USD in favour.`,
    };
  }
  return {
    buy: false,
    headline: "I would not buy",
    why: `It costs ${usd(item.total_cost_usd)} USD and only prevents `
      + `${usd(item.stockout_cost_usd)} of stockout: ${usd(Math.abs(benefit))} USD against.`,
  };
}

/** Una linea que explica la tension, no que repite la etiqueta. */
export function whyLine(item) {
  const gap = item.inventory_min - item.on_hand_qty;

  // El limite que bloquea no es la capacidad de la bodega sino el maximo
  // permitido, que ya descuenta lo que caducaria antes de consumirse.
  if (item.decision === "ESCALAR") {
    return `Criticality ${escape(item.criticality)}: running out stops a line. `
      + `Covering it needs ${usd(item.total_cost_usd)} USD beyond the authorised budget.`;
  }
  if (item.decision === "REVISAR") {
    return `${escape(item.supplier_name || "The supplier")} does not sell fewer than `
      + `${units(item.recommended_qty)} and the allowed maximum is `
      + `${units(item.max_allowed_qty)}.`;
  }
  if (item.decision === "APLAZADO") {
    const risk = item.stockout_cost_usd
      ? ` It leaves ${usd(item.stockout_cost_usd)} USD of stockout risk uncovered.` : "";
    return `Production continuity took the budget of this run first.${risk}`;
  }
  if (item.decision === "COMPRAR") {
    const short = gap > 0
      ? `${units(gap)} short of the reorder point.`
      : "Right at the reorder point.";
    return `${short} At the current rate there is ${runway(item)} left on the shelf.`;
  }
  return `Covers its minimum with ${units(item.on_hand_qty)} on hand; lasts ${runway(item)}.`;
}

/** Cuanto dura el stock actual al consumo proyectado. */
export function runway(item) {
  return months(item.on_hand_qty / Math.max(item.demand_monthly, 0.01));
}

/** Pie de la tarjeta: a quien, cuanto y en cuanto tiempo. */
export function footLine(item) {
  if (!item.supplier_id) {
    return `<span>${decimal(item.demand_monthly)} u/month</span>`
      + `<span>${pattern(item.pattern)}</span>`;
  }
  return `
    <span>${escape(item.supplier_name)}</span>
    <span><b>${usd(item.total_cost_usd)}</b> USD</span>
    <span>${leadTime(item.lead_time_days)}</span>`;
}

export function critChip(item) {
  return `<span class="crit crit--${item.criticality}" title="Criticality ${item.criticality}">${item.criticality}</span>`;
}

/** Ordena poniendo delante lo que mas duele: criticidad, despues cuanto le
 *  falta al stock para llegar al minimo, y a igualdad de todo, el importe. */
export function byUrgency(a, b) {
  const rank = { A: 0, B: 1, C: 2 };
  return (rank[a.criticality] ?? 3) - (rank[b.criticality] ?? 3)
    || a.gauge.fill_pct - b.gauge.fill_pct
    || (b.total_cost_usd || 0) - (a.total_cost_usd || 0);
}
