/* El catalogo de formulas de cada etapa del pipeline.
 *
 * Cada paso del sistema aplica una formula concreta que viene de algun sitio de
 * la literatura. Sin eso, la pantalla de modelo y pipeline dice que hace cada
 * etapa pero no por que se puede defender lo que hace, que es exactamente la
 * pregunta que llega en una revision.
 *
 * Tres decisiones de forma.
 *
 * La primera: las formulas se escriben en MathML nativo y no como texto. Una
 * raiz cuadrada escrita `sqrt(...)` obliga a leer codigo; escrita como raiz se
 * lee como matematica. El navegador lo renderiza sin libreria, asi que no entra
 * ninguna dependencia nueva al paquete.
 *
 * La segunda: debajo de cada formula va el glosario de todos sus simbolos, con
 * su unidad. Una formula sin sus variables definidas no es una explicacion, es
 * una decoracion.
 *
 * La tercera: los valores de los parametros no se escriben aqui sino que llegan
 * del informe del pipeline, que los lee del codigo. Asi cambiar una constante en
 * Python cambia lo que dice la pantalla, y las dos no pueden discrepar.
 */

import { escape } from "./format.js";

/* ---------- Constructores de MathML ---------- */

const NS = 'xmlns="http://www.w3.org/1998/Math/MathML"';

const mi = (name) => `<mi>${name}</mi>`;
const mn = (value) => `<mn>${value}</mn>`;
const mo = (symbol) => `<mo>${symbol}</mo>`;
const mtext = (value) => `<mtext>${value}</mtext>`;
const row = (...parts) => `<mrow>${parts.join("")}</mrow>`;
const frac = (over, under) => `<mfrac>${over}${under}</mfrac>`;
const root = (inner) => `<msqrt>${inner}</msqrt>`;
const sub = (base, index) => `<msub>${base}${index}</msub>`;
const sup = (base, power) => `<msup>${base}${power}</msup>`;
const par = (inner) => row(mo("("), inner, mo(")"));
const brk = (inner) => row(mo("["), inner, mo("]"));
const block = (...parts) => `<math display="block" ${NS}>${row(...parts)}</math>`;
const eq = mo("=");
const times = mo("·");
const plus = mo("+");
const minus = mo("−");

const gap = '<mspace width="1.4em"/>';
const comma = mo(",");

/** Envuelve un texto suelto en el elemento que le corresponde, de modo que las
 *  formulas se puedan escribir con cadenas sin dejar texto crudo dentro del
 *  MathML, que es lo que hace que un navegador lo pinte torcido. */
const token = (value) => {
  const text = String(value);
  if (/^[0-9]+(\.[0-9]+)?$/.test(text)) return mn(text);
  if (/^[A-Za-z]+$/.test(text)) return mi(text);
  return mtext(text);
};

const fn = (name, ...args) =>
  row(mi(name), mo("("), args.map(token).join(comma), mo(")"));
const maxOf = (...parts) => row(mi("max"), mo("("), parts.join(comma), mo(")"));
const minOf = (...parts) => row(mi("min"), mo("("), parts.join(comma), mo(")"));
/* Techo y piso se escriben con su nombre y no con ⌈ ⌉ ⌊ ⌋: esos glifos no
   existen en todas las fuentes matematicas y donde faltan se sustituyen por
   corchetes, que dicen otra cosa. */
const ceilOf = (...parts) => row(mi("ceil"), mo("("), parts.join(""), mo(")"));
const floorOf = (...parts) => row(mi("floor"), mo("("), parts.join(""), mo(")"));
const sum = (index, body) => row(sub(mo("∑"), mi(index)), body);

/* ---------- Render ---------- */

/** Una formula con su nombre, su enunciado, el glosario de simbolos y de donde
 *  viene. El orden importa: primero como se llama, para poder buscarla; despues
 *  la formula; despues que significa cada letra; y solo al final la nota que
 *  matiza cuando deja de valer. */
export function renderFormula(formula, parameters) {
  const p = parameters || {};
  /* El glosario puede ser una lista fija o una funcion de los parametros, para
     los simbolos cuya unidad es el propio valor configurado —el presupuesto, el
     periodo de planificacion— y que por tanto tiene que llegar del codigo. */
  const symbols = typeof formula.where === "function" ? formula.where(p) : (formula.where || []);

  const glossary = symbols.map(([symbol, meaning, unit]) => `
    <tr>
      <th scope="row"><span class="sym">${symbol}</span></th>
      <td>${escape(meaning)}</td>
      <td class="unit">${escape(unit || "—")}</td>
    </tr>`).join("");

  return `
    <figure class="formula">
      <figcaption class="formula__head">
        <span class="formula__name">${escape(formula.name)}</span>
        <span class="formula__theory">${escape(formula.theory)}</span>
      </figcaption>
      <div class="formula__math">${formula.math(p)}</div>
      ${glossary ? `<table class="glossary">
        <thead><tr><th>Symbol</th><th>What it is</th><th>Unit</th></tr></thead>
        <tbody>${glossary}</tbody>
      </table>` : ""}
      ${formula.note ? `<p class="formula__note">${formula.note}</p>` : ""}
    </figure>`;
}

/** El bloque completo de una etapa: todas sus formulas en el orden en que el
 *  pipeline las aplica. */
export function renderTheory(stageId, parameters) {
  const formulas = FORMULAS[stageId] || [];
  if (!formulas.length) return "";

  return `<section class="theory">
    <h3 class="theory__title">Formulas applied in this step</h3>
    <p class="theory__lead">Every figure this stage publishes comes from one of these.
      Parameter values are read from the code, not typed here.</p>
    ${formulas.map((formula) => renderFormula(formula, parameters)).join("")}
  </section>`;
}

/* ---------- Etapa 0 · Limpieza ---------- */

const CLEANING = [
  {
    name: "Interquartile outlier band",
    theory: "Tukey (1977), Exploratory Data Analysis",
    math: (p) => block(
      mi("x"), mo("∉"),
      brk(row(
        sub(mi("Q"), mn(1)), minus, mn(p.iqr_factor ?? 1.5), times, mi("IQR"),
        mo(","),
        sub(mi("Q"), mn(3)), plus, mn(p.iqr_factor ?? 1.5), times, mi("IQR"),
      )),
      mo("⟹"), mtext("outlier"),
    ),
    where: [
      ["Q₁, Q₃", "First and third quartile of the column", "unit of the column"],
      ["IQR", "Interquartile range, Q₃ − Q₁", "unit of the column"],
      ["1.5", "Band width. Tukey's convention for a mild outlier", "dimensionless"],
    ],
    note: "It assumes nothing about the distribution, but it drags when more than a "
      + "quarter of the data is extreme. That is why it is not used alone.",
  },
  {
    name: "Modified z-score on the median absolute deviation",
    theory: "Iglewicz & Hoaglin (1993), NIST/SEMATECH e-Handbook",
    math: (p) => block(
      sub(mi("M"), mi("i")), eq,
      frac(
        row(mn(p.mad_scale ?? 0.6745), times, par(row(sub(mi("x"), mi("i")), minus, mi("x̃")))),
        mi("MAD"),
      ),
      mo(">"), mn(p.mad_threshold ?? 3.5),
    ),
    where: [
      ["xᵢ", "Observed value", "unit of the column"],
      ["x̃", "Median of the column", "unit of the column"],
      ["MAD", "Median of |xᵢ − x̃|", "unit of the column"],
      ["0.6745", "Scale factor that makes MAD comparable to a standard deviation "
        + "under normality", "dimensionless"],
      ["3.5", "Score above which the value is flagged", "dimensionless"],
    ],
    note: "It uses the median rather than the mean, so a handful of extreme values does "
      + "not move the criterion. When more than half the observations repeat, MAD is "
      + "zero and the rule goes blind; the code falls back to the mean absolute "
      + "deviation from the median, which keeps the robustness.",
  },
  {
    name: "Minimum observed days per month",
    theory: "Operating rule declared for this dataset",
    math: (p) => block(
      mtext("days recorded in the month"), mo("<"), mn(p.min_days_per_month ?? 20),
      mo("⟹"), mtext("month discarded"),
    ),
    where: [
      ["20", "Days with a record below which the month is not evidence of demand",
        "days/month"],
    ],
    note: "A month with a single day recorded would read as a collapse in demand. "
      + "Discarding it removes a false signal, not real data.",
  },
];

/* ---------- Etapa 1 · Dataset ---------- */

const DATASET = [
  {
    name: "Referential integrity of the dataset",
    theory: "Hard validation rules, rejected before any stage runs",
    math: () => block(
      mi("price"), mo("≥"), mn(0), comma, gap,
      mi("MOQ"), mo("≥"), mn(1), comma, gap,
      mi("L"), mo(">"), mn(0), comma, gap,
      mi("qty"), mo("≥"), mn(0), comma, gap,
      mo("∀"), mi("s"), mo(":"), mo("|"), mi("O"), par(mi("s")), mo("|"), mo("≥"), mn(2),
    ),
    where: [
      ["price", "Unit price of an offer", "USD/unit"],
      ["MOQ", "Minimum order quantity of an offer", "units"],
      ["L", "Supplier lead time", "days"],
      ["qty", "Quantity in any inventory or demand row", "units"],
      ["|O(s)|", "Number of offers that can serve series s", "offers"],
    ],
    note: "The last rule is the one that matters for the optimiser: with a single offer "
      + "there is nothing to choose between, and the supplier-selection model becomes "
      + "an arithmetic exercise instead of a decision.",
  },
  {
    name: "Seed reorder point of the synthetic inventory",
    theory: "Normal approximation, same service factors as the policy",
    math: () => block(
      mi("ROP"), eq,
      ceilOf(mi("μ"), plus, fn("z", "k"), times, mi("σ")),
    ),
    where: [
      ["μ", "Mean monthly consumption of the series", "units/month"],
      ["σ", "Standard deviation of monthly consumption", "units/month"],
      ["z(k)", "Service factor by criticality: A 1.65 · B 1.28 · C 0.84", "dimensionless"],
    ],
    note: "This is only the starting stock the build writes. The reorder point the "
      + "system actually decides on is recomputed in the forecast stage over the "
      + "real lead time, not over a calendar month.",
  },
];

/* ---------- Etapa 2 · Patrones ---------- */

const PATTERNS = [
  {
    name: "Coefficient of variation",
    theory: "Descriptive statistic. Threshold declared as business policy",
    math: (p) => block(
      mi("CV"), eq, frac(mi("σ"), mi("μ")), comma, gap,
      mi("CV"), mo(">"), mn(p.cv_volatile ?? 0.5), mo("⟹"), mtext("volatile"),
    ),
    where: [
      ["σ", "Standard deviation of monthly consumption", "units/month"],
      ["μ", "Mean monthly consumption", "units/month"],
      ["CV", "Relative dispersion, comparable across parts of any size", "dimensionless"],
    ],
    note: "Dividing by the mean is what makes a part moving 100 units a month "
      + "comparable with one moving 2. The absolute deviation alone is not.",
  },
  {
    name: "Seasonal strength of the decomposition",
    theory: "Wang, Smith & Hyndman (2006); STL decomposition, Cleveland et al. (1990)",
    math: (p) => block(
      sub(mi("F"), mi("s")), eq, mn(1), minus,
      frac(
        row(mtext("Var"), par(mi("R"))),
        row(mtext("Var"), par(row(mi("S"), plus, mi("R")))),
      ),
      comma, gap,
      sub(mi("F"), mi("s")), mo("≥"), mn(p.seasonal_strength_min ?? 0.45),
    ),
    where: [
      ["S", "Seasonal component of the decomposition", "units/month"],
      ["R", "Remainder after removing trend and season", "units/month"],
      ["Fₛ", "Share of the seasonal-plus-noise variance explained by the season",
        "0 to 1"],
      ["0.45", "Minimum strength to call a series seasonal", "dimensionless"],
    ],
    note: "Strength alone labels even pure noise as seasonal, so it is required "
      + "together with a significant month effect. Both conditions have to hold.",
  },
  {
    name: "Month-effect test",
    theory: "Kruskal & Wallis (1952), non-parametric one-way ANOVA",
    math: (p) => block(
      mi("H"), eq,
      frac(mn(12), row(mi("N"), par(row(mi("N"), plus, mn(1))))),
      sum("j", frac(sup(sub(mi("R"), mi("j")), mn(2)), sub(mi("n"), mi("j")))),
      minus, mn(3), par(row(mi("N"), plus, mn(1))),
      comma, gap,
      mi("p"), mo("<"), mn(p.seasonal_pvalue_max ?? 0.05),
    ),
    where: [
      ["N", "Total number of observations in the series", "months"],
      ["nⱼ", "Observations falling in calendar month j", "months"],
      ["Rⱼ", "Sum of ranks of the observations in month j", "ranks"],
      ["H", "Test statistic, approximately chi-square with 11 degrees of freedom",
        "dimensionless"],
      ["p", "Probability of seeing this month effect by chance", "0 to 1"],
    ],
    note: "It works on ranks, not on values, so it does not require the demand to be "
      + "normal — which it is not.",
  },
  {
    name: "Pattern confidence score",
    theory: "Weighted composite declared as business policy, not estimated",
    math: (p) => block(
      mi("γ"), eq,
      mn(p.weight_volume ?? 0.3), times, fn("V", "n"), plus,
      mn(p.weight_volatility ?? 0.45), times, fn("W", "CV"), plus,
      mn(p.weight_recent ?? 0.25), times, fn("R", "y"),
    ),
    where: [
      ["V(n)", "How much history the series has, saturating at the full window",
        "0 to 1"],
      ["W(CV)", "How stable the series is; falls as the coefficient of variation grows",
        "0 to 1"],
      ["R(y)", "How close the last three months are to the historical level", "0 to 1"],
      ["γ", "Confidence in the pattern label. Below 0.5 the row is flagged for a human",
        "0 to 1"],
    ],
    note: "The three weights are a declared policy, not a fit. They say what the "
      + "project considers a trustworthy series; they are not estimated from data.",
  },
];

/* ---------- Etapa 3 · Proyeccion e inventario minimo ---------- */

const MODEL = [
  {
    name: "The four point estimators, one per pattern",
    theory: "Moving average · moving median · OLS · Holt-Winters (1960)",
    math: () => block(
      sub(mi("D"), mn(50)), eq,
      mo("{"),
      row(
        frac(mn(1), mn(6)), sum("t", sub(mi("y"), mi("t"))), mtext("  stable"),
        mo(";  "), sub(mi("P"), mn(50)), mtext("  volatile"),
        mo(";  "), mi("a"), times, mi("n"), plus, mi("b"), mtext("  trending"),
        mo(";  "), sub(mi("ℓ"), mi("n")), plus, sub(mi("s"), row(mi("n"), minus, mn(11))),
        mtext("  seasonal"),
      ),
    ),
    where: [
      ["yₜ", "Consumption observed in month t", "units/month"],
      ["P₅₀", "Median of the last six months", "units/month"],
      ["a, b", "Slope and intercept of the least-squares line", "units/month² and units"],
      ["ℓₙ", "Holt-Winters level at the last month", "units/month"],
      ["sₙ₋₁₁", "Seasonal index of the same calendar month a year earlier",
        "units/month"],
      ["D₅₀", "Central forecast for next month", "units/month"],
    ],
    note: "The method is chosen by the pattern rather than fitted per series, so the "
      + "forecast is reproducible and the reason for each figure is the label, which "
      + "the previous stage already published.",
  },
  {
    name: "Plausible range of the forecast",
    theory: "Normal quantile at 25% and 75%",
    math: (p) => block(
      sub(mi("D"), mn(25)), mo("/"), sub(mi("D"), mn(75)), eq,
      maxOf(mn(0), row(sub(mi("D"), mn(50)), mo("∓"), mn(p.quantile_z ?? 0.674), times, mi("S"))),
    ),
    where: [
      ["S", "Dispersion of the series used as the forecast error", "units/month"],
      ["0.674", "Standard-normal quantile leaving 25% in each tail", "dimensionless"],
      ["D₂₅, D₇₅", "Low and high scenario for next month", "units/month"],
    ],
    note: "Clipping at zero is not cosmetic: a negative demand has no operating "
      + "meaning, and the normal assumption produces one whenever the mean is small "
      + "relative to the dispersion.",
  },
  {
    name: "Weighted error of the method, rolling origin",
    theory: "WMAPE with rolling-origin evaluation, Tashman (2000)",
    math: () => block(
      mi("WMAPE"), eq,
      frac(
        row(sum("j", row(mo("|"), sub(mi("e"), mi("j")), mo("|")))),
        row(sum("j", sub(mi("y"), mi("j")))),
      ),
    ),
    where: [
      ["eⱼ", "Error of month j: forecast minus observed", "units"],
      ["yⱼ", "Consumption observed in month j", "units"],
      ["WMAPE", "Error as a share of the volume actually moved", "0 to 1"],
    ],
    note: "Weighting by volume avoids the trap of MAPE, which explodes on the months a "
      + "part barely moves and would rank a method by its behaviour on the least "
      + "important months.",
  },
  {
    name: "Combination of the two forecasts",
    theory: "Bates & Granger (1969), combination of forecasts",
    math: (p) => block(
      sub(mi("D"), row(mn(50), mo(","), mtext("final"))), eq,
      mn(p.blend_weight ?? 0.5), times, mi("M"), plus,
      par(row(mn(1), minus, mn(p.blend_weight ?? 0.5))), times, sub(mi("D"), mn(50)),
    ),
    where: [
      ["M", "Forecast of the trained global model", "units/month"],
      ["D₅₀", "Forecast of the statistical method for the pattern", "units/month"],
      ["λ", "Weight given to the model", "0 to 1"],
    ],
    note: "The equal weight is a declared choice, not an estimate. It is the right one "
      + "when two estimators have similar error and weakly correlated mistakes, which "
      + "is what the validation shows here — but the optimal weight is not fitted.",
  },
  {
    name: "Daily basis of demand",
    theory: "Variance of a sum of independent daily variations",
    math: (p) => block(
      mi("d"), eq, frac(sub(mi("D"), row(mn(50), mo(","), mtext("final"))),
        mn(p.days_per_month ?? 30)),
      comma, gap,
      sub(mi("σ"), mi("d")), eq, frac(mi("σ"), root(mn(p.days_per_month ?? 30))),
    ),
    where: [
      ["d", "Mean daily demand", "units/day"],
      ["σ_d", "Standard deviation of daily demand", "units/day"],
      ["30", "Planning days per month. A planning constant, not the calendar", "days/month"],
    ],
    note: "The mean divides and the deviation divides by the square root, because the "
      + "variance of a sum of 30 independent daily variations is 30 times the daily "
      + "one. With autocorrelation the real exponent sits between 0.6 and 0.8, not "
      + "at 0.5, so this understates the buffer on correlated series.",
  },
  {
    name: "Variance of demand over a random lead time",
    theory: "Law of total variance. Hadley & Whitin (1963); Silver, Pyke & Peterson",
    math: () => block(
      row(mtext("Var"), par(sub(mi("D"), mi("L")))), eq,
      mi("L"), times, sup(sub(mi("σ"), mi("d")), mn(2)), plus,
      sup(mi("d"), mn(2)), times, sup(sub(mi("σ"), mi("L")), mn(2)),
    ),
    where: [
      ["L", "Mean planning lead time", "days"],
      ["σ_L", "Standard deviation of the lead time", "days"],
      ["d, σ_d", "Mean and deviation of daily demand", "units/day"],
      ["Var(D_L)", "Variance of the demand accumulated while the order is in transit",
        "units²"],
    ],
    note: "The first term is the uncertainty of demand; the second is the supplier's, "
      + "multiplied by demand squared. With σ_L/L near 0.53 in these suppliers both "
      + "terms are the same order: half the risk does not come from demand at all.",
  },
  {
    name: "Reorder point: the inventory minimum",
    theory: "Safety stock under stochastic demand and lead time. Hadley & Whitin (1963)",
    math: () => block(
      sub(mi("I"), mtext("min")), eq,
      ceilOf(
        mi("d"), times, mi("L"), plus,
        fn("z", "k"), times, root(row(mi("L"), times, sup(sub(mi("σ"), mi("d")), mn(2)),
          plus, sup(mi("d"), mn(2)), times, sup(sub(mi("σ"), mi("L")), mn(2)))),
      ),
    ),
    where: [
      ["d · L", "What gets consumed while the replenishment is in transit. Not a "
        + "buffer: the bare minimum", "units"],
      ["z(k)", "Service factor by criticality: A 1.65 (95%) · B 1.28 (90%) · C 0.84 (80%)",
        "dimensionless"],
      ["Imin", "Level at which an order is placed", "whole units"],
    ],
    note: "The three z values are the only declaration of service policy in the whole "
      + "system, and they are set by constant rather than derived from a shortage cost. "
      + "Eppen & Martin (1988): demand over a random lead time is a mixture and is "
      + "skewed, so the real service sits below the nominal one. The system does not "
      + "correct for that.",
  },
];

/* ---------- Etapa 4 · Optimizacion ---------- */

const OPTIMIZATION = [
  {
    name: "Economic order quantity",
    theory: "Harris (1913); Wilson (1934). Order-up-to link: Hadley & Whitin (1963)",
    math: (p) => block(
      sup(mi("Q"), mo("*")), eq,
      root(frac(row(mn(2), times, mi("K"), times, mi("D")), mi("h"))),
      comma, gap,
      mi("h"), eq, mn(p.holding_cost_rate_annual ?? 0.25), times, mi("c"),
      comma, gap,
      mi("D"), eq, mn(p.months_per_year ?? 12), times, sub(mi("D"), mn(50)),
    ),
    where: [
      ["K", "Fixed cost of bringing one order: the freight to that plant", "USD/order"],
      ["D", "Annual demand projected for the part", "units/year"],
      ["c", "Unit value of the part in the master", "USD/unit"],
      ["h", "Cost of holding one unit idle for a year: capital, storage, insurance "
        + "and obsolescence risk", "USD/unit/year"],
      ["i", "Annual carrying rate applied to the value of the part", "0 to 1"],
      ["Q*", "Quantity that minimises the annual sum of ordering plus holding cost",
        "units"],
    ],
    note: "This is the figure that replaced a fixed coverage in months. Ordering a lot "
      + "at once spreads the freight over more units but leaves more capital idle; "
      + "ordering little does the opposite. Q* is where both halves of the annual cost "
      + "cross. Because the supplier is not chosen until the next model runs, K uses "
      + "the mean freight of the applicable offers — the square root makes that "
      + "approximation cheap: being off by double moves the quantity only 41%.",
  },
  {
    name: "Order-up-to level and the obsolescence cap",
    theory: "(s, S) policy. Flat-cost property: Silver, Pyke & Peterson (1998)",
    math: (p) => block(
      mi("Q"), eq, minOf(
        ceilOf(sup(mi("Q"), mo("*"))),
        floorOf(sub(mi("D"), mn(50)), times, mn(p.eoq_max_coverage_months ?? 6)),
      ),
      comma, gap,
      mi("S"), eq, sub(mi("I"), mtext("min")), plus, mi("Q"),
      comma, gap,
      sub(mi("I"), mtext("max")), eq, mi("S"),
    ),
    where: [
      ["s", "Reorder point, which is Imin from the previous stage", "units"],
      ["S", "Level the order brings stock up to", "units"],
      ["Q", "Economic quantity after the coverage cap", "units"],
      ["6", "Months of coverage above which obsolescence outweighs the freight saving",
        "months"],
    ],
    note: "Because nothing is ever bought above S, that level is at once the "
      + "replenishment target and the inventory ceiling of the part: in an (s, S) "
      + "policy they are the same number. The cap costs little: the total-cost curve is "
      + "flat around the optimum, and being off by double the optimal lot raises the "
      + "total by only 25%. Wilson's formula does not know parts expire; this is what "
      + "tells it.",
  },
  {
    name: "Shelf-life ceiling",
    theory: "Anti-obsolescence rule declared for this dataset",
    math: (p) => block(
      sub(mi("I"), mtext("life")), eq,
      maxOf(mn(0), row(
        floorOf(mi("d"), times, mn(p.shelf_life_safety_ratio ?? 0.8), times, mi("V")),
        minus, mi("q"),
      )),
    ),
    where: [
      ["V", "Shelf life of the part", "days"],
      ["0.80", "Safety margin: only 80% of the shelf life is planned against",
        "dimensionless"],
      ["q", "Units already on hand, which are consumed first", "units"],
      ["I_life", "Units that can still be consumed before expiry", "units"],
    ],
  },
  {
    name: "Supplier selection",
    theory: "Fixed-charge problem, Balinski (1961). Solved exactly with CBC",
    math: () => block(
      mtext("min"), gap, sum("o", row(sub(mi("p"), mi("o")), times, sub(mi("x"), mi("o")),
        plus, sub(mi("f"), mi("o")), times, sub(mi("u"), mi("o")))),
      gap + mtext("subject to") + gap,
      sum("o", sub(mi("x"), mi("o"))), mo("≥"), sub(mi("R"), mtext("inf")), comma, gap,
      sum("o", sub(mi("u"), mi("o"))), mo("≤"), mn(1), comma, gap,
      sub(mi("x"), mi("o")), mo("≥"), sub(mi("m"), mi("o")), times, sub(mi("u"), mi("o")),
      comma, gap,
      sub(mi("x"), mi("o")), mo("≤"), sub(mi("U"), mi("o")), times, sub(mi("u"), mi("o")),
    ),
    where: [
      ["x_o", "Units bought from offer o", "whole units"],
      ["u_o", "Whether offer o is activated at all", "0 or 1"],
      ["p_o, f_o, m_o", "Unit price, fixed freight and minimum order quantity",
        "USD/unit, USD, units"],
      ["U_o", "Effective upper bound: the smaller of the ceiling and the supplier "
        + "capacity", "units"],
      ["R_inf", "Quantity that has to be covered", "units"],
    ],
    note: "The two linking constraints are the whole mechanism. With u_o = 0 both force "
      + "x_o = 0 and no freight is paid; with u_o = 1 they force the minimum lot. That "
      + "is what turns \"freight is only paid if the supplier is used\" and \"the "
      + "minimum lot only applies if you buy from them\" into linear constraints. "
      + "Limiting the order to a single supplier is an operating rule, not a "
      + "mathematical one: splitting would be equal or better on cost, but one order "
      + "has to be executable by one person.",
  },
  {
    name: "Valuing the stockout that ordering prevents",
    theory: "Deterministic valuation. The daily cost is a business parameter",
    math: (p) => block(
      sub(mi("C"), mi("q")), eq,
      par(row(
        maxOf(mn(0), row(mi("P"), plus, mi("L"), minus, mtext("cover"))), minus,
        maxOf(mn(0), row(mi("L"), minus, mtext("cover"))),
      )),
      times, mi("r"), times, fn("c", "k"),
    ),
    where: (p) => [
      ["cover", "Days the stock on hand lasts at the forecast rate", "days"],
      ["P", "Planning period until the next run", `${p.planning_period_days ?? 30} days`],
      ["L", "Replenishment lead time", "days"],
      ["r", "Issue rate: share of days the part is actually requested", "0 to 1"],
      ["c(k)", "Cost of one unmet request, by criticality: the line stops until the "
        + "part arrives", "USD/request"],
      ["C_q", "Value of the stockout that ordering now instead of waiting prevents",
        "USD"],
    ],
    note: "The r factor is what makes the figure defensible. A day without stock only "
      + "costs money if somebody asks for the part that day. Which tells you what the "
      + "units really are: days times issue rate is not days, it is the expected number "
      + "of requests that cannot be served, so c(k) is the cost of one unmet request — "
      + "the line stops until the part arrives, which with OEM material is weeks. It is "
      + "still deterministic: it assumes demand arrives exactly at the forecast rate, so "
      + "it understates the risk on the least predictable series. And c(k) is a fixed "
      + "parameter, not an estimate — its magnitude alone decides how much criticality "
      + "weighs against price, so it has to be validated with maintenance.",
  },
  {
    name: "Budget allocation with production continuity as a hard constraint",
    theory: "0/1 knapsack, Lorie & Savage (1955); Weingartner (1963) on capital rationing",
    math: (p) => block(
      mtext("max"), gap,
      sub(mo("∑"), row(mi("s"), mo("∈"), sub(mi("Cand"), mtext("flex")))),
      row(sub(mi("b"), mi("s")), times, sub(mi("v"), mi("s"))),
      gap + mtext("subject to") + gap,
      sub(mi("v"), mi("s")), eq, mn(1), mo("  ∀"), mi("s"), mo("∈"),
      sub(mi("Cand"), mtext("crit")), comma, gap,
      sum("s", row(sub(mi("C"), mi("s")), times, sub(mi("v"), mi("s")))),
      mo("≤"), mi("B"), plus, mi("E"), comma, gap,
      mi("E"), mo("≤"), sub(mi("E"), mtext("max")),
    ),
    where: (p) => [
      ["Cand_crit", "Replenishments whose stockout stops a line: criticality A",
        "set"],
      ["Cand_flex", "The rest, which compete for what is left", "set"],
      ["b_s", "Net benefit: stockout prevented minus what preventing it costs", "USD"],
      ["C_s", "Total cost of the replenishment already resolved by the previous model",
        "USD"],
      ["v_s", "Whether the purchase is funded this run", "0 or 1"],
      ["B", "Nominal budget of the run", `${p.budget_usd ?? 2500} USD`],
      ["E", "Overrun actually consumed to cover the critical parts", "USD"],
      ["E_max", "Authorised ceiling on that overrun",
        `${p.overrun_max_usd ?? 1500} USD`],
    ],
    note: "This inverts the chain of command of the previous model. The budget used to "
      + "rule over everything, and a part could be deferred even though its stockout "
      + "stops a line, simply because others returned more per dollar — a bad trade the "
      + "knapsack could not see, because it priced every part in the same currency. "
      + "Now continuity does not compete: criticality A is funded first, the budget "
      + "stretches by an authorised overrun to achieve it, and the overrun is reported "
      + "rather than hidden. What does not fit even then is returned as ESCALATE "
      + "instead of being silently dropped, because widening the budget is a management "
      + "call and not the optimiser's.",
  },
  {
    name: "Minimum service level per criticality class",
    theory: "Consistency with the z values declared in the reorder point",
    math: () => block(
      sub(mo("∑"), row(mi("s"), mo("∈"), sub(mi("Class"), mi("k")))),
      sub(mi("v"), mi("s")), mo("≥"),
      ceilOf(sub(mi("θ"), mi("k")), times, mo("|"), sub(mi("Class"), mi("k")), mo("|")),
    ),
    where: [
      ["Class_k", "Replenishments of criticality k that were due", "set"],
      ["θ_k", "Share of the class that has to be funded: A 1.00 · B 0.80 · C 0.50",
        "0 to 1"],
      ["v_s", "Whether the purchase is funded", "0 or 1"],
    ],
    note: "It exists for coherence with the previous stage. If a 90% service level was "
      + "declared for class B when computing the reorder point, the budget should not "
      + "contradict it by deferring most of them. When the money does not stretch even "
      + "to the floors, they are released from the least demanding class upwards rather "
      + "than declaring the model infeasible, and the service level actually reached is "
      + "published next to the one that was declared.",
  },
];

export const FORMULAS = {
  limpieza: CLEANING,
  dataset: DATASET,
  patrones: PATTERNS,
  modelo: MODEL,
  optimizacion: OPTIMIZATION,
};
