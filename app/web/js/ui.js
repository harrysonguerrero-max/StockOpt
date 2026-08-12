/* Piezas visuales que comparten varias vistas. */

import { decimal, escape, leadTime, months, pattern, units, usd } from "./format.js";

export const PENDING = "Pendiente aprobacion";
export const ADVANCED = ["Aprobado", "Contactado proveedor", "Orden confirmada"];

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

/** La accion en forma de verbo. La etiqueta COMPRAR / REVISAR / NO_COMPRAR es
 *  el nombre interno de la decision, no lo que el comprador tiene que hacer. */
export function actionLine(item) {
  if (item.decision === "COMPRAR") {
    return { text: `Comprar ${units(item.recommended_qty)}`, tone: "go" };
  }
  if (item.decision === "REVISAR") {
    return { text: `Decidir: lote mínimo de ${units(item.recommended_qty)}`, tone: "hold" };
  }
  if (item.decision === "APLAZADO") {
    return { text: `Aplazado: ${usd(item.total_cost_usd)} USD`, tone: "stop" };
  }
  return { text: "Sin acción", tone: "none" };
}

/** Una linea que explica la tension, no que repite la etiqueta. */
export function whyLine(item) {
  const gap = item.inventory_min - item.on_hand_qty;
  if (item.decision === "REVISAR") {
    return `${escape(item.supplier_name || "El proveedor")} no vende menos de `
      + `${units(item.recommended_qty)} y en bodega caben ${units(item.inventory_max)}.`;
  }
  // Lo que cambia de una fila a otra no es la cobertura del lote —el objetivo
  // es el mismo para todas— sino cuanto aguanta la bodega. Repetir "el lote
  // cubre 1 mes" en cada tarjeta era texto de relleno.
  // La reposicion procedia; lo que falta es dinero, no criterio. Por eso el dato
  // que decide aqui no es el faltante sino el riesgo que queda sin cubrir.
  if (item.decision === "APLAZADO") {
    const riesgo = item.stockout_cost_usd
      ? ` Deja ${usd(item.stockout_cost_usd)} USD de riesgo de quiebre sin cubrir.` : "";
    return `El presupuesto de la corrida ya está comprometido.${riesgo}`;
  }
  if (item.decision === "COMPRAR") {
    const falta = gap > 0
      ? `Faltan ${units(gap)} para el mínimo.`
      : "Está en el punto de reposición.";
    return `${falta} Al ritmo actual quedan ${runway(item)} en bodega.`;
  }
  return `Cubre el mínimo con ${units(item.on_hand_qty)} en bodega; `
    + `aguanta ${runway(item)}.`;
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
