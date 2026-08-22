/* Piezas visuales y lecturas que comparten varias vistas. */

import { decimal, escape, leadTime, months, pattern, units, usd } from "./format.js";

export const PENDING = "Pendiente aprobacion";
export const ADVANCED = ["Aprobado", "Contactado proveedor", "Orden confirmada"];
export const REJECTED = "Rechazado";

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

/** Medidor de existencias, dibujado como la escala que es.
 *
 *  La version anterior era una barra roja medio llena y una frase debajo con
 *  tres numeros. La barra no decia donde estaba cada cosa y la frase obligaba a
 *  releerla para emparejar cada cifra con su sitio, de modo que ninguna de las
 *  dos servia sola y juntas eran redundantes.
 *
 *  Ahora las cifras estan **sobre la escala, en su posicion**: el stock actual
 *  donde termina el relleno, el punto de reorden sobre su marca negra, y el
 *  nivel de reposicion al final. Se lee de un vistazo si el stock esta antes o
 *  despues del punto que dispara la orden, que es la unica pregunta que el
 *  medidor tiene que responder.
 */
export function gauge(item, size = "") {
  const g = item.gauge;
  const reorder = Math.min(Math.max(g.minimum_pct, 0), 100);
  const fill = Math.min(Math.max(g.fill_pct, 0), 100);

  /* La etiqueta del stock se ancla por el lado que no se salga del medidor:
     pegada al cero se desbordaria por la izquierda, y al maximo por la derecha. */
  const anchor = fill < 12 ? "start" : fill > 88 ? "end" : "mid";

  return `
    <span class="gauge ${size}">
      <span class="gauge__scale">
        <span class="gauge__now gauge__now--${anchor}" style="left:${fill}%">
          <b>${units(item.on_hand_qty)}</b> on hand
        </span>
      </span>
      <span class="gauge__track">
        <span class="gauge__fill gauge__fill--${g.zone}" style="width:${fill}%"></span>
        <span class="gauge__min" style="left:${reorder}%"></span>
      </span>
      <span class="gauge__scale gauge__scale--under">
        <span class="gauge__zero">0</span>
        <span class="gauge__mark" style="left:${reorder}%">
          <b>${units(item.inventory_min)}</b> reorder
        </span>
        <span class="gauge__max"><b>${units(item.inventory_max)}</b> refill to</span>
      </span>
    </span>`;
}

/** Cuanto dura el stock actual al consumo proyectado. */
export function runway(item) {
  return months(item.on_hand_qty / Math.max(item.demand_monthly, 0.01));
}

/* ---------- Los dos bloques de la tarjeta ---------- */

const CONSEQUENCE = {
  A: "Stops a production line",
  B: "Degrades output",
  C: "Tolerable until the next run",
};

/** 1. El riesgo: que pasa si falta, y cuanto queda antes de que falte.
 *
 *  Va primero y sin cifras en dolares: lo que decide la urgencia es el tiempo y
 *  la consecuencia, no el importe. Una pieza de 238 USD que para una linea es
 *  mas urgente que una de 2.000 que no.
 *
 *  Tampoco repite las unidades. El medidor que va justo debajo ya dice cuanto
 *  hay, en que punto se dispara la orden y hasta donde se repone, y decirlo dos
 *  veces obligaba a comprobar que las dos versiones coincidian.
 */
export function riskLine(item) {
  const consequence = CONSEQUENCE[item.criticality] || CONSEQUENCE.C;
  const left = `about <b>${runway(item)}</b> left at the current rate`;

  if (item.decision === "NO_COMPRAR") {
    return { level: "off", text: `Covers its minimum — ${left}.` };
  }
  if (item.decision === "ESCALAR") {
    return {
      level: "escalate",
      text: `${consequence}. ${left}, and the run cannot fund it even with the overrun.`,
    };
  }
  if (item.decision === "APLAZADO") {
    return {
      level: "stop",
      text: `${consequence}. ${left}, and nothing is on order: the budget went elsewhere.`,
    };
  }
  return {
    level: item.decision === "COMPRAR" ? "go" : "hold",
    text: `${consequence}. Below the reorder point, ${left}.`,
  };
}

/** 2. El plan: que hacer, a quien, por cuanto y cuando llega.
 *
 *  El proveedor lleva su etiqueta de mejor candidato porque no es el unico: el
 *  optimizador comparo las ofertas aplicables y esta gano. Sin decirlo, el
 *  nombre parece un dato administrativo en vez de una eleccion.
 */
export function planLine(item) {
  if (item.decision === "NO_COMPRAR") {
    return { label: "What to do", text: "Nothing this run." };
  }
  if (!item.supplier_id) {
    return { label: "What to do", text: "No offer meets the constraints for this plant." };
  }

  const pick = item.alternatives_evaluated > 1
    ? `<span class="pick">best of ${item.alternatives_evaluated}</span>`
    : '<span class="pick">only offer</span>';

  const head = `<b>${units(item.recommended_qty)}</b> from `
    + `<b>${escape(item.supplier_name)}</b> ${pick} · <b>${usd(item.total_cost_usd)} USD</b> · `
    + `${leadTime(item.lead_time_days)}`;

  if (item.decision === "REVISAR") {
    return {
      label: "What to decide",
      text: `${head}<span class="case__snag">Their minimum lot is `
        + `${units(item.recommended_qty)} and the part only holds `
        + `${units(item.max_allowed_qty)}.</span>`,
    };
  }
  return { label: "What to do", text: head };
}

/** 3. El veredicto: que haria el sistema, en dos palabras.
 *
 *  Solo el titular. El razonamiento completo —cuanto quiebre evita, cuantas
 *  veces el costo del lote, si caduca antes de consumirse— vive en el panel de
 *  detalle, que es donde se lee cuando ya se decidio mirar el caso. En la
 *  tarjeta ocupaba tres lineas para sostener una decision que no se toma
 *  leyendo un parrafo, sino viendo el riesgo y el precio, que estan justo
 *  encima.
 *
 *  El beneficio neto lo calcula el optimizador —lo que cuesta el quiebre que se
 *  evita menos lo que cuesta evitarlo— asi que la recomendacion sale del dato.
 *  La vida util manda por encima: comprar algo que caduca antes de consumirse no
 *  se recomienda aunque el numero salga a favor.
 */
export function verdictLine(item) {
  if (!["REVISAR", "APLAZADO", "ESCALAR"].includes(item.decision)) return null;

  if (item.decision === "ESCALAR") {
    return { tone: "stop", headline: "Needs budget released" };
  }
  if (item.decision === "APLAZADO") {
    return { tone: "stop", headline: "Left uncovered this run" };
  }

  const shelfMonths = item.shelf_life_days / 30.4;
  if (item.coverage_months > shelfMonths) {
    return { tone: "hold", headline: "I would not buy — it expires first" };
  }
  return Number(item.net_benefit_usd || 0) > 0
    ? { tone: "go", headline: "I would buy" }
    : { tone: "hold", headline: "I would not buy" };
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
