/* El control de presupuesto.
 *
 * El reparto de dinero es la unica decision del sistema que no depende de
 * proyectar nada: la mochila mira cuatro columnas que ya estan escritas —el
 * costo de la orden, el beneficio neto, la criticidad y el quiebre que evita— y
 * ninguna de las cuatro cambia con el presupuesto. Por eso el presupuesto puede
 * ser un control en vez de una constante, y por eso importa que lo sea: con el
 * presupuesto de la corrida holgado la restriccion de continuidad de produccion
 * no se dispara nunca y no hay forma de ensenarla. Bajando el numero se ve en el
 * acto que reposiciones se aplazan y cuales, por ser criticas, obligan a
 * escalar en lugar de ceder.
 *
 * Vive con los datos en crudo y no con el turno. Es un parametro del escenario,
 * del mismo orden que las tablas que lo alimentan, y el turno tiene que abrir
 * por lo que amenaza la produccion, no por un formulario.
 */

import { state, toast } from "./api.js";
import { percent, usdRound } from "./format.js";

let onBudgetChange = () => {};

export function setBudgetListener(callback) { onBudgetChange = callback; }

export function paintBudget() {
  const s = state.summary;
  if (!s) return;

  const amount = document.getElementById("budget-amount");
  const overrun = document.getElementById("budget-overrun");
  const reset = document.getElementById("budget-reset");
  const hint = document.getElementById("budget-hint");

  if (document.activeElement !== amount) amount.value = Math.round(s.budget_usd);
  if (document.activeElement !== overrun) overrun.value = Math.round(s.overrun_max_usd);

  const custom = state.budget !== null;
  reset.hidden = !custom;

  const committed = s.investment_usd;
  const share = s.budget_usd ? committed / s.budget_usd : 0;
  hint.innerHTML = custom
    ? `Scenario · the run itself budgets ${usdRound(s.budget_default_usd)} USD`
    : `${percent(share)} committed. Lower it to see what the continuity rule protects.`;
}

export function initBudget() {
  const form = document.getElementById("budget-bar");
  const amount = document.getElementById("budget-amount");
  const overrun = document.getElementById("budget-overrun");

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const budget = Number(amount.value);
    const ceiling = Number(overrun.value);
    if (!Number.isFinite(budget) || budget < 0) {
      toast("The budget has to be a positive number", true);
      return;
    }
    state.budget = budget;
    state.overrun = Number.isFinite(ceiling) && ceiling >= 0 ? ceiling : 0;
    await onBudgetChange();
  });

  document.getElementById("budget-reset").addEventListener("click", async () => {
    state.budget = null;
    state.overrun = null;
    await onBudgetChange();
  });
}
