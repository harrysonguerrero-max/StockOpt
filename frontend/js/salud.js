/* El estado de salud del turno.
 *
 * La pantalla abria con una frase que respondia una pregunta —¿estan financiadas
 * las piezas criticas?— mientras debajo habia setenta y ocho casos en rojo
 * respondiendo otra —¿hay trabajo pendiente?—. Las dos eran ciertas y juntas se
 * leian como una contradiccion: "produccion cubierta" sobre un muro de alertas.
 *
 * La salida no es suavizar el titular sino separar las preguntas. Son tres, no
 * una, y cada una tiene su propia luz:
 *
 *   1. Continuidad  ¿hay algo que pueda parar una linea?
 *   2. Presupuesto  ¿el dinero de la corrida da, y a costa de que?
 *   3. Decisiones   ¿cuanto espera a una persona, y de que criticidad?
 *
 * El veredicto de arriba es **la peor de las tres**. Asi no puede ocurrir que el
 * titular diga que todo esta bien mientras una luz esta en rojo: si algo esta en
 * rojo, el titular lo esta.
 *
 * El color nunca va solo. Cada luz lleva su palabra —Clear, Watch, Act now—
 * porque uno de cada doce hombres no distingue rojo de verde, y porque una
 * captura en blanco y negro tiene que seguir diciendo lo mismo.
 */

import { state } from "./api.js";
import { escape, usdRound } from "./format.js";

const PENDING = "Pendiente aprobacion";
const OPEN_DECISIONS = ["ESCALAR", "REVISAR", "APLAZADO"];

const RANK = { go: 0, hold: 1, stop: 2 };
const WORD = { go: "Clear", hold: "Watch", stop: "Act now" };

const worst = (levels) =>
  levels.reduce((found, level) => (RANK[level] > RANK[found] ? level : found), "go");

const money = (rows) => rows.reduce((sum, item) => sum + Number(item.total_cost_usd || 0), 0);

/** Las filas que todavia esperan a una persona. */
const awaiting = (rows) =>
  rows.filter((item) => item.state === PENDING && OPEN_DECISIONS.includes(item.decision));

/* ---------- Las tres luces ---------- */

/** Continuidad: que una linea se pare es lo unico que no se compensa con dinero,
 *  asi que esta luz solo mira criticidad A. Rojo si alguna esta sin financiar
 *  —escalada o aplazada—; ambar si esta financiada pero espera una decision. */
function continuity(rows) {
  const critical = awaiting(rows).filter((item) => item.criticality === "A");
  const unfunded = critical.filter((item) => item.decision !== "REVISAR");
  const undecided = critical.filter((item) => item.decision === "REVISAR");

  if (unfunded.length) {
    return {
      key: "continuity",
      title: "Production continuity",
      level: "stop",
      figure: `${unfunded.length} critical ${unfunded.length === 1 ? "part" : "parts"}`,
      note: "cannot be replenished with the budget of this run",
    };
  }
  if (undecided.length) {
    return {
      key: "continuity",
      title: "Production continuity",
      level: "hold",
      figure: `${undecided.length} critical ${undecided.length === 1 ? "part" : "parts"}`,
      note: "the money is there, but nothing is on order until you decide",
    };
  }
  return {
    key: "continuity",
    title: "Production continuity",
    level: "go",
    figure: "Covered",
    note: "every criticality-A replenishment is resolved",
  };
}

/** Presupuesto: rojo solo si se uso el excedente autorizado, porque eso es gasto
 *  por encima de lo aprobado. Que el presupuesto se agote no es una alarma —es
 *  lo normal cuando la mochila trabaja—, pero desplazar reposiciones si obliga a
 *  mirar. */
function budget(summary) {
  const overrun = summary.overrun_usd || 0;
  const share = summary.budget_usd ? summary.investment_usd / summary.budget_usd : 0;

  if (overrun > 0) {
    return {
      key: "budget",
      title: "Run budget",
      level: "stop",
      figure: `${usdRound(overrun)} USD over`,
      note: `beyond the ${usdRound(summary.budget_usd)} USD authorised`,
    };
  }
  if (summary.deferred > 0) {
    return {
      key: "budget",
      title: "Run budget",
      level: "hold",
      figure: `${Math.round(share * 100)}% committed`,
      note: `${summary.deferred} replenishments displaced for lack of money`,
    };
  }
  return {
    key: "budget",
    title: "Run budget",
    level: "go",
    figure: `${Math.round(share * 100)}% committed`,
    note: "nothing was displaced for lack of money",
  };
}

/** Decisiones: mide carga de trabajo, no riesgo. Se pone en rojo cuando entre lo
 *  pendiente hay piezas criticas, porque entonces la cola deja de ser trabajo y
 *  pasa a ser exposicion. */
function decisions(rows) {
  const open = awaiting(rows);
  const critical = open.filter((item) => item.criticality === "A").length;

  if (!open.length) {
    return {
      key: "decisions",
      title: "Waiting for you",
      level: "go",
      figure: "Nothing",
      note: "the run resolved every case on its own",
    };
  }
  return {
    key: "decisions",
    title: "Waiting for you",
    level: critical ? "stop" : "hold",
    figure: `${open.length} ${open.length === 1 ? "case" : "cases"}`,
    note: critical
      ? `${critical} of them stop a line if they run out`
      : "none of them stops a line",
  };
}

/* ---------- El veredicto ---------- */

const VERDICTS = {
  continuity: "Production is at risk — act now",
  budget: "The run spent beyond its authorised budget",
  decisions: "Critical parts are waiting for your decision",
};

function verdict(level, lights) {
  if (level === "stop") {
    const first = lights.find((light) => light.level === "stop");
    return VERDICTS[first.key];
  }
  if (level === "hold") return "Production is covered, but there is work waiting";
  return "Production is covered and nothing is waiting";
}

/** Los puntos concretos, en bullets y no en un parrafo. Cada uno responde una
 *  pregunta distinta y ninguno repite la cifra de otro. */
function points(rows, summary) {
  const open = awaiting(rows);
  const list = [];

  /* El dinero se reparte por planta. "100 % comprometido" no dice a donde fue,
     y a donde fue es justo lo que decide si el reparto fue razonable: dos
     plantas con bodegas y proveedores distintos no compiten por el mismo
     presupuesto de forma neutral. */
  const auto = rows.filter((item) => item.decision === "COMPRAR");
  if (auto.length) {
    const byPlant = new Map();
    auto.forEach((item) => {
      const plant = byPlant.get(item.city_name) || { usd: 0, n: 0 };
      plant.usd += Number(item.total_cost_usd || 0);
      plant.n += 1;
      byPlant.set(item.city_name, plant);
    });

    const split = [...byPlant.entries()]
      .sort((a, b) => b[1].usd - a[1].usd)
      .map(([name, plant]) =>
        `${name.split(",")[0]} ${usdRound(plant.usd)} (${plant.n})`)
      .join(" · ");

    list.push({
      tone: "go",
      lead: `${usdRound(summary.investment_usd)} USD committed automatically`,
      body: `${split}. Resolved without ambiguity — nothing for you to do on them.`,
    });
  }

  const review = open.filter((item) => item.decision === "REVISAR");
  if (review.length) {
    const critical = review.filter((item) => item.criticality === "A").length;
    list.push({
      tone: critical ? "stop" : "hold",
      lead: `${review.length} purchases need your call · ${usdRound(money(review))} USD`,
      jump: critical ? "A" : null,
      body: critical
        ? `${critical} of them are criticality A. The supplier's minimum lot is above what the `
          + "part can hold, so the system will not commit them for you."
        : "The supplier's minimum lot is above what the part can hold.",
    });
  }

  const deferred = open.filter((item) => item.decision === "APLAZADO");
  if (deferred.length) {
    list.push({
      tone: "hold",
      lead: `${deferred.length} replenishments held back · ${usdRound(money(deferred))} USD`,
      body: "Protecting production took the budget first. It leaves "
        + `${usdRound(summary.stockout_exposed_usd || 0)} USD of stockout risk uncovered.`,
    });
  }

  const escalated = open.filter((item) => item.decision === "ESCALAR");
  if (escalated.length) {
    list.unshift({
      tone: "stop",
      lead: `${escalated.length} critical parts need more budget · `
        + `${usdRound(money(escalated))} USD`,
      body: "They do not fit even with the authorised overrun. Someone has to release money "
        + "or accept the risk of a stoppage.",
    });
  }

  return list;
}

/* ---------- Render ---------- */

export function renderHealth() {
  const summary = state.summary;
  if (!summary) return;

  const rows = state.items;
  const lights = [continuity(rows), budget(summary), decisions(rows)];
  const level = worst(lights.map((light) => light.level));

  const host = document.getElementById("health");
  host.className = `health health--${level}`;
  host.innerHTML = `
    <p class="health__lead">Production-continuity replenishment · Nava and Ciudad Obregón</p>
    <h2 class="health__verdict">${escape(verdict(level, lights))}</h2>

    <div class="health__lights">
      ${lights.map((light) => `
        <div class="light light--${light.level}">
          <span class="light__head">
            <span class="light__dot" aria-hidden="true"></span>
            <span class="light__title">${escape(light.title)}</span>
            <span class="light__word">${WORD[light.level]}</span>
          </span>
          <strong class="light__figure">${escape(light.figure)}</strong>
          <span class="light__note">${escape(light.note)}</span>
        </div>`).join("")}
    </div>

    <ul class="health__points">
      ${points(rows, summary).map((point) => `
        <li class="point point--${point.tone}">
          <b>${escape(point.lead)}</b>
          <span>${escape(point.body)}</span>
          ${point.jump
    ? `<button class="point__go" type="button" data-jump="${point.jump}">Show me those
         ${point.jump === "A" ? "critical" : ""} cases →</button>`
    : ""}
        </li>`).join("")}
    </ul>`;

  /* La cifra que alarma tiene que llevar a los casos que la producen. Decir "3
     criticas esperan" y dejar que se busquen entre setenta y ocho es la clase de
     alerta que se aprende a ignorar. */
  host.querySelectorAll("[data-jump]").forEach((button) => {
    button.addEventListener("click", () => onJump(button.dataset.jump));
  });
}

let onJump = () => {};

/** Quien atiende la peticion de "ensename esos casos". La registra el turno,
 *  que es quien sabe donde estan pintados. */
export function setJumpListener(callback) { onJump = callback; }
