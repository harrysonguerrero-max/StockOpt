/* El estado de carga, en un solo sitio.
 *
 * Hay peticiones de esta pantalla que tardan: la historia de consumo son
 * noventa y dos mil filas y el servidor las manda enteras. Sin señal de que algo
 * esta pasando, la pantalla se queda igual que estaba y la lectura correcta por
 * parte de quien mira es que el clic no funciono. Entonces vuelve a hacer clic,
 * y lo unico que consigue es encolar la misma peticion otra vez y esperar el
 * doble.
 *
 * Por eso el modulo hace las dos cosas a la vez y no una: enseña que se esta
 * cargando **y** bloquea lo que dispararia la misma carga. Enseñarlo sin
 * bloquear no evita el segundo clic, y bloquear sin enseñarlo lo hace parecer
 * roto.
 *
 * Vive aparte porque no es un detalle del explorador de tablas. Cualquier vista
 * que llame a la API con volumen —el pipeline, la clasificacion, una descarga—
 * tiene el mismo problema y merece la misma respuesta.
 */

const ACTIVE = new Set();

/** El bloque que se pinta mientras se espera. Se exporta suelto porque a veces
 *  hace falta el marcado sin la mecanica: una tarjeta que nace vacia y se
 *  llenara despues, por ejemplo. */
export function loadingMarkup(message = "Loading…") {
  return `<div class="loading" role="status" aria-live="polite">
    <span class="loading__spin" aria-hidden="true"></span>
    <span class="loading__text">${message}</span>
  </div>`;
}

const resolve = (node) => (typeof node === "string" ? document.getElementById(node) : node);

/** Envuelve una tarea asincrona con su estado de carga.
 *
 *  `into` es donde se pinta el aviso, `disable` lo que se bloquea mientras
 *  tanto, y `key` identifica la carga para que dos clics seguidos sobre lo
 *  mismo no disparen dos peticiones. Devuelve lo que devuelva la tarea, o
 *  `undefined` si se ignoro por estar ya en curso.
 */
export async function whileLoading({ into, message, disable = [], key }, task) {
  const identity = key || String(into);
  if (ACTIVE.has(identity)) return undefined;
  ACTIVE.add(identity);

  const target = resolve(into);
  const blocked = disable.map(resolve).filter((node) => node && !node.disabled);

  if (target) target.innerHTML = loadingMarkup(message);
  blocked.forEach((node) => { node.disabled = true; });
  document.body.classList.add("is-loading");

  try {
    return await task();
  } finally {
    ACTIVE.delete(identity);
    blocked.forEach((node) => { node.disabled = false; });
    if (!ACTIVE.size) document.body.classList.remove("is-loading");
  }
}

/** Si una carga con esa identidad sigue en curso. Sirve para no repintar encima
 *  de un aviso que todavia vale. */
export function isLoading(key) { return ACTIVE.has(key); }
