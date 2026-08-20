/* Presentacion de cifras y de los codigos internos.
 *
 * La interfaz anterior escribia "4.003,38 USD", "14.5 dias" y "20.4 meses".
 * Ningun comprador decide sobre centavos ni sobre decimas de dia, y esa
 * precision inventada es lo que mas delata un numero generado. Aqui cada tipo
 * de dato se redondea al detalle que de verdad cambia una decision.
 *
 * Aqui vive tambien la traduccion de los codigos internos. La decision, el
 * patron y el estado del flujo viajan en español porque asi estan guardados en
 * los CSV y en la base de aprobaciones; traducirlos en el origen obligaria a
 * migrar dato ya escrito. Se traducen en el ultimo momento, que es justo antes
 * de pintarlos.
 */

const LOCALE = "en-US";

/** Cifra de dinero al detalle que importa: centavos solo por debajo de 10. */
export function usd(value) {
  const n = Number(value || 0);
  if (n === 0) return "0";
  if (n >= 10) return n.toLocaleString(LOCALE, { maximumFractionDigits: 0 });
  return n.toLocaleString(LOCALE, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** Decimal con la misma convencion que el resto de la pantalla. */
export function decimal(value, digits = 1) {
  return Number(value || 0).toLocaleString(LOCALE, {
    minimumFractionDigits: digits, maximumFractionDigits: digits,
  });
}

/** Dinero para titulares: se redondea a la magnitud que se recuerda. */
export function usdRound(value) {
  const n = Number(value || 0);
  const step = n >= 10000 ? 1000 : n >= 1000 ? 100 : 10;
  return (Math.round(n / step) * step).toLocaleString(LOCALE, { maximumFractionDigits: 0 });
}

/** Precio unitario: aqui los centavos si distinguen a un proveedor de otro. */
export function price(value) {
  return Number(value || 0).toLocaleString(LOCALE, {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  });
}

export function units(value) {
  return Math.round(Number(value || 0)).toLocaleString(LOCALE);
}

export const count = (value) => Number(value || 0).toLocaleString(LOCALE);

export function percent(value, digits = 0) {
  return `${(Number(value || 0) * 100).toFixed(digits)}%`;
}

/** Meses de cobertura: la decima solo informa cuando la cobertura es corta. */
export function months(value) {
  const n = Number(value || 0);
  if (n >= 10) return `${Math.round(n)} months`;
  if (n >= 2) return `${decimal(n)} months`;
  if (n >= 1) return "1 month";
  const weeks = Math.max(1, Math.round(n * 4.3));
  return weeks === 1 ? "1 week" : `${weeks} weeks`;
}

/** El patron viaja en español dentro del CSV; en pantalla es texto para leer. */
const PATTERNS = {
  volatil: "volatile",
  estacional: "seasonal",
  estable: "stable",
  tendencia: "trending",
  insuficiente: "insufficient",
  "con tendencia": "trending",
  "sin clasificar": "unclassified",
};

export function pattern(value) {
  const key = String(value || "").toLowerCase();
  return PATTERNS[key] || key;
}

/** Las cuatro decisiones y la escalada, con el nombre que usa una persona. */
const DECISIONS = {
  COMPRAR: "Buy",
  NO_COMPRAR: "No action",
  REVISAR: "Review",
  APLAZADO: "Deferred",
  ESCALAR: "Escalate",
};

export const decisionWord = (value) => DECISIONS[value] || String(value || "");

/** El origen de la proyeccion sin el identificador interno del pipeline. */
const SOURCES = {
  "modelo+estadistico": "model and statistics combined",
  estadistico: "statistics only",
  modelo: "trained model",
};

export function source(value) {
  return SOURCES[String(value || "")] || String(value || "");
}

/** Plazo de entrega en la unidad en que lo piensa un comprador.
 *  Por debajo de tres semanas se queda en dias: redondear 10 dias a "1 week"
 *  y 10,5 a "2 weeks" convierte una diferencia de horas en una de siete dias,
 *  y esa comparacion es justo la que decide entre dos proveedores. */
export function leadTime(days) {
  const n = Number(days || 0);
  if (!n) return "no lead time";
  if (n < 21) return `${Math.round(n)} days`;
  return `~${Math.round(n / 7)} weeks`;
}

/** La confianza en palabras: 0.49 no significa nada por si solo. */
export function confidence(value) {
  const n = Number(value || 0);
  if (n >= 0.75) return { word: "high", tone: "go" };
  if (n >= 0.55) return { word: "medium", tone: "" };
  return { word: "low", tone: "warn" };
}

/** Estado del flujo sin la abreviatura con que viaja en la base. */
const STATES = {
  "Pendiente aprobacion": ["Pending approval", "Pending"],
  "Aprobado": ["Approved", "Approved"],
  "Contactado proveedor": ["Supplier contacted", "Contacted"],
  "Orden confirmada": ["Order confirmed", "Confirmed"],
  "Rechazado": ["Rejected", "Rejected"],
};

export const stateLong = (value) => (STATES[value] || [value, value])[0];
export const stateShort = (value) => (STATES[value] || [value, value])[1];

export function escape(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}
