/* Piezas visuales y lecturas que comparten varias vistas. */

import { decimal, escape, leadTime, months, pattern, units, usd } from "./format.js";

export const PENDING = "Pendiente aprobacion";
export const ADVANCED = ["Aprobado", "Contactado proveedor", "Orden confirmada"];

/* El semaforo de la pantalla. Las cuatro decisiones no piden lo mismo y la
   interfaz tiene que decirlo antes que ninguna otra cosa:

     COMPRAR      el solver la resolvio sin ambigüedad; no requiere criterio
     REVISAR      hay una tension que el solver no puede zanjar; decide alguien
     APLAZADO     procedia y la freno el presupuesto; decide alguien con dinero
     NO_COMPRAR   no hay nada que hacer

   De ahi que el verde sea el color mas callado de los tres: marca lo que ya
   esta resuelto. El ambar y el rojo son los que reclaman. */
const SEMAPHORE = {
  COMPRAR: { level: "go", label: "Automática" },
  REVISAR: { level: "hold", label: "Tu decisión" },
  APLAZADO: { level: "stop", label: "Sin presupuesto" },
  NO_COMPRAR: { level: "off", label: "Sin acción" },
};

export const semaphore = (item) => SEMAPHORE[item.decision] || SEMAPHORE.NO_COMPRAR;

/** Medidor de existencias: stock sobre la escala del maximo, con marca en el
 *  minimo. Codifica en una sola lectura la tension que decide cada caso. */
export function gauge(item, size = "") {
  const g = item.gauge;
  return `
    <span class="gauge ${size}">
      <span class="gauge__track">
        <span class="gauge__fill gauge__fill--${g.zone}" style="width:${g.fill_pct}%"></span>
        <span class="gauge__min" style="left:${g.minimum_pct}%" title="Mínimo operativo"></span>
      </span>
      <span class="gauge__read">
        <b>${units(item.on_hand_qty)}</b> en bodega · mínimo <b>${units(item.inventory_min)}</b> · caben <b>${units(item.inventory_max)}</b>
      </span>
    </span>`;
}

/** La accion en forma de verbo. La etiqueta COMPRAR / REVISAR es el nombre
 *  interno de la decision, no lo que la persona tiene que hacer. */
export function actionLine(item) {
  if (item.decision === "COMPRAR") {
    return { text: `Comprar ${units(item.recommended_qty)} — automática`, tone: "go" };
  }
  if (item.decision === "REVISAR") {
    return { text: `Decidir: lote mínimo de ${units(item.recommended_qty)}`, tone: "hold" };
  }
  if (item.decision === "APLAZADO") {
    return { text: `Aplazado: ${usd(item.total_cost_usd)} USD`, tone: "stop" };
  }
  return { text: "Sin acción", tone: "none" };
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
      headline: "Yo no compraría",
      why: `El lote deja ${months(item.coverage_months)} de inventario y la pieza `
        + `caduca a los ${months(shelfMonths)}.`,
    };
  }
  if (benefit > 0) {
    return {
      buy: true,
      headline: "Yo compraría",
      why: `Evita ${usd(item.stockout_cost_usd)} USD de quiebre y cuesta `
        + `${usd(item.total_cost_usd)}: ${usd(benefit)} USD a favor.`,
    };
  }
  return {
    buy: false,
    headline: "Yo no compraría",
    why: `Cuesta ${usd(item.total_cost_usd)} USD y solo evita `
      + `${usd(item.stockout_cost_usd)} de quiebre: ${usd(Math.abs(benefit))} USD en contra.`,
  };
}

/** Una linea que explica la tension, no que repite la etiqueta. */
export function whyLine(item) {
  const gap = item.inventory_min - item.on_hand_qty;

  // El limite que bloquea no es la capacidad de la bodega sino el maximo
  // permitido, que ya descuenta lo que caducaria antes de consumirse.
  if (item.decision === "REVISAR") {
    return `${escape(item.supplier_name || "El proveedor")} no vende menos de `
      + `${units(item.recommended_qty)} y el máximo permitido es `
      + `${units(item.max_allowed_qty)}.`;
  }
  if (item.decision === "APLAZADO") {
    const risk = item.stockout_cost_usd
      ? ` Deja ${usd(item.stockout_cost_usd)} USD de riesgo de quiebre sin cubrir.` : "";
    return `El presupuesto de la corrida ya está comprometido.${risk}`;
  }
  if (item.decision === "COMPRAR") {
    const short = gap > 0
      ? `Faltan ${units(gap)} para el mínimo.`
      : "Está en el punto de reposición.";
    return `${short} Al ritmo actual quedan ${runway(item)} en bodega.`;
  }
  return `Cubre el mínimo con ${units(item.on_hand_qty)} en bodega; aguanta ${runway(item)}.`;
}

/** Cuanto dura el stock actual al consumo proyectado. */
export function runway(item) {
  return months(item.on_hand_qty / Math.max(item.demand_monthly, 0.01));
}

/** Pie de la tarjeta: a quien, cuanto y en cuanto tiempo. */
export function footLine(item) {
  if (!item.supplier_id) {
    return `<span>${decimal(item.demand_monthly)} u/mes</span>`
      + `<span>${pattern(item.pattern)}</span>`;
  }
  return `
    <span>${escape(item.supplier_name)}</span>
    <span><b>${usd(item.total_cost_usd)}</b> USD</span>
    <span>${leadTime(item.lead_time_days)}</span>`;
}

export function critChip(item) {
  return `<span class="crit crit--${item.criticality}" title="Criticidad ${item.criticality}">${item.criticality}</span>`;
}

/** Ordena poniendo delante lo que mas duele: criticidad, despues cuanto le
 *  falta al stock para llegar al minimo, y a igualdad de todo, el importe. */
export function byUrgency(a, b) {
  const rank = { A: 0, B: 1, C: 2 };
  return (rank[a.criticality] ?? 3) - (rank[b.criticality] ?? 3)
    || a.gauge.fill_pct - b.gauge.fill_pct
    || (b.total_cost_usd || 0) - (a.total_cost_usd || 0);
}
