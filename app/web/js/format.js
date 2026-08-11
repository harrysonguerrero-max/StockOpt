/* Presentacion de cifras.
 *
 * La interfaz anterior escribia "4.003,38 USD", "14.5 dias" y "20.4 meses".
 * Ningun comprador decide sobre centavos ni sobre decimas de dia, y esa
 * precision inventada es lo que mas delata un numero generado. Aqui cada tipo
 * de dato se redondea al detalle que de verdad cambia una decision.
 */

const LOCALE = "es-MX";

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

/** Meses de cobertura: la decima solo informa cuando la cobertura es corta. */
export function months(value) {
  const n = Number(value || 0);
  if (n >= 10) return `${Math.round(n)} meses`;
  if (n >= 2) return `${decimal(n)} meses`;
  if (n >= 1) return "1 mes";
  const weeks = Math.max(1, Math.round(n * 4.3));
  return weeks === 1 ? "1 semana" : `${weeks} semanas`;
}

/** El patron viaja sin acentos en el CSV; en pantalla es texto para leer. */
const PATTERNS = {
  volatil: "volátil",
  estacional: "estacional",
  estable: "estable",
  "con tendencia": "con tendencia",
};

export function pattern(value) {
  const key = String(value || "").toLowerCase();
  return PATTERNS[key] || key;
}

/** El origen de la proyeccion sin el identificador interno del pipeline. */
const SOURCES = {
  "modelo+estadistico": "modelo y estadística combinados",
  estadistico: "solo estadística",
  modelo: "modelo entrenado",
};

export function source(value) {
  return SOURCES[String(value || "")] || String(value || "");
}

/** Plazo de entrega en la unidad en que lo piensa un comprador.
 *  Por debajo de tres semanas se queda en dias: redondear 10 dias a "1 semana"
 *  y 10,5 a "2 semanas" convierte una diferencia de horas en una de siete dias,
 *  y esa comparacion es justo la que decide entre dos proveedores. */
export function leadTime(days) {
  const n = Number(days || 0);
  if (!n) return "sin plazo";
  if (n < 21) return `${Math.round(n)} días`;
  return `~${Math.round(n / 7)} semanas`;
}

/** La confianza en palabras: 0,49 no significa nada por si solo. */
export function confidence(value) {
  const n = Number(value || 0);
  if (n >= 0.75) return { word: "alta", tone: "go" };
  if (n >= 0.55) return { word: "media", tone: "" };
  return { word: "baja", tone: "warn" };
}

/** Estado del flujo sin la abreviatura con que viaja en la base. */
const STATES = {
  "Pendiente aprobacion": ["Pendiente de aprobar", "Pendiente"],
  "Aprobado": ["Aprobado", "Aprobado"],
  "Contactado proveedor": ["Contactado proveedor", "Contactado"],
  "Orden confirmada": ["Orden confirmada", "Confirmada"],
  "Rechazado": ["Rechazado", "Rechazado"],
};

export const stateShort = (value) => (STATES[value] || [value, value])[1];

export function escape(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}
