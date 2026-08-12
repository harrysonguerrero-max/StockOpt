/* Las nueve familias de refaccion, dibujadas.
 *
 * Un comprador no reconoce MRO-10045; reconoce un rodamiento. La descripcion lo
 * dice en ingles tecnico y en abreviaturas, asi que la forma llega antes que el
 * texto.
 *
 * Son planos de linea, no fotografias de catalogo. Tres razones: las fotos de
 * fabricante tienen derechos, un producto recortado sobre blanco no funciona
 * sobre fondo oscuro, y el dibujo de linea es justamente el lenguaje de la ficha
 * tecnica que esta pantalla imita. Trazo unico, sin relleno, heredando el color
 * del texto para que sirva igual en cualquier tamaño y sobre cualquier fondo.
 *
 * Convencion de plano: contorno en trazo continuo, ejes y lineas de centro en
 * trazo discontinuo.
 */

const AXIS = 'stroke-dasharray="1.5 2" opacity=".55"';

const SHAPES = {
  // Anillo exterior, anillo interior y los cuerpos rodantes entre ambos.
  Bearing: `
    <circle cx="20" cy="20" r="15"/><circle cx="20" cy="20" r="11.5"/>
    <circle cx="20" cy="20" r="7.5"/><circle cx="20" cy="20" r="4"/>
    ${[0, 45, 90, 135, 180, 225, 270, 315].map((a) => {
      const r = (a * Math.PI) / 180;
      return `<circle cx="${(20 + 9.5 * Math.cos(r)).toFixed(1)}"
                      cy="${(20 + 9.5 * Math.sin(r)).toFixed(1)}" r="1.9"/>`;
    }).join("")}
    <path d="M3 20h34M20 3v34" ${AXIS}/>`,

  // Junta torica: el anillo y, a la derecha, su seccion circular acotada.
  "Seal & Gasket": `
    <circle cx="16" cy="20" r="12.5"/><circle cx="16" cy="20" r="8"/>
    <path d="M3.5 20h25" ${AXIS}/>
    <circle cx="33" cy="15" r="2.6"/><circle cx="33" cy="25" r="2.6"/>
    <path d="M33 12.4V8M33 27.6V32" stroke-width="1"/>
    <path d="M30 8h6M30 32h6" stroke-width="1"/>`,

  // Correa cerrada sobre dos poleas, con la seccion trapecial marcada.
  "Drive Belt": `
    <path d="M13 8h14a12 12 0 0 1 0 24H13a12 12 0 0 1 0-24z"/>
    <path d="M13 12h14a8 8 0 0 1 0 16H13a8 8 0 0 1 0-16z"/>
    <circle cx="13" cy="20" r="3.2"/><circle cx="27" cy="20" r="3.2"/>
    <path d="M13 20h14" ${AXIS}/>`,

  // Cartucho filtrante: cilindro con el medio plisado.
  Filter: `
    <path d="M9 9h22v22H9z"/><path d="M9 9h22M9 31h22" stroke-width="1.6"/>
    <path d="M12 12l3 8-3 8M17 12l3 8-3 8M22 12l3 8-3 8M27 12l3 8-3 8"
          stroke-width="1"/>
    <path d="M20 5v4M20 31v4" ${AXIS}/>`,

  // Bloque de contactor con sus bornes.
  Electrical: `
    <path d="M11 12h18v16H11z"/>
    <path d="M15 12V7M20 12V7M25 12V7M15 28v5M20 28v5M25 28v5" stroke-width="1.4"/>
    <path d="M21.5 15l-4 6h5l-4 5" stroke-width="1.4" stroke-linejoin="round"/>`,

  // Estrella elastica de acoplamiento: cubo y garras radiales.
  Coupling: `
    <circle cx="20" cy="20" r="14"/><circle cx="20" cy="20" r="5"/>
    ${[0, 60, 120, 180, 240, 300].map((a) => {
      const r = (a * Math.PI) / 180;
      const x1 = 20 + 5 * Math.cos(r);
      const y1 = 20 + 5 * Math.sin(r);
      const x2 = 20 + 14 * Math.cos(r);
      const y2 = 20 + 14 * Math.sin(r);
      return `<path d="M${x1.toFixed(1)} ${y1.toFixed(1)}L${x2.toFixed(1)} ${y2.toFixed(1)}"/>`;
    }).join("")}`,

  // Cartucho de grasa con su boquilla.
  Lubrication: `
    <path d="M8 13h20v14H8z"/><path d="M28 17h5l3 3-3 3h-5"/>
    <path d="M11 13v14M14 13v14" stroke-width="1" opacity=".6"/>
    <path d="M36 20h2" ${AXIS}/>`,

  // Sensor de proximidad M12: cuerpo roscado, cara sensora y cable.
  Sensor: `
    <path d="M14 14h14v12H14z"/><path d="M28 16.5h4v7h-4z"/>
    <path d="M14 15.5h-3M14 18h-3M14 20.5h-3M14 23h-3M14 25.5h-3" stroke-width="1"/>
    <path d="M11 20H4" stroke-width="1.4"/>
    <path d="M32 20h4" ${AXIS}/>`,

  // Tornillo de cabeza hexagonal con vastago roscado.
  Fastener: `
    <path d="M8 13l4-3 4 3v10l-4 3-4-3z"/>
    <path d="M12 10v16" ${AXIS}/>
    <path d="M16 15.5h18M16 20.5h18" stroke-width="1.4"/>
    <path d="M19 15.5v5M23 15.5v5M27 15.5v5M31 15.5v5" stroke-width="1"/>`,
};

/** Pieza sin familia conocida: una caja de almacen, que es lo que se sabe. */
const FALLBACK = `<path d="M8 12h24v20H8z"/><path d="M8 18h24"/>
  <path d="M17 12v6M23 12v6" stroke-width="1"/>`;

/**
 * Devuelve el plano de una familia como SVG en linea.
 *
 * `title` se usa como texto accesible; sin el, el dibujo es decorativo y se
 * oculta al lector de pantalla, que es lo correcto cuando la descripcion de la
 * pieza ya esta escrita al lado.
 */
export function glyph(category, { size = 40, title = "" } = {}) {
  const shape = SHAPES[category] || FALLBACK;
  return `<svg class="glyph" viewBox="0 0 40 40" width="${size}" height="${size}"
    fill="none" stroke="currentColor" stroke-width="1.3"
    stroke-linecap="round" ${title ? `role="img" aria-label="${title}"` : 'aria-hidden="true"'}
  >${shape}</svg>`;
}

export const FAMILIES = Object.keys(SHAPES);
