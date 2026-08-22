/* El mapa de plantas.
 *
 * Nava y Ciudad Obregon estan a mil kilometros, con bodega propia y proveedores
 * que no coinciden. Sobre un mapa real eso se ve solo, y por eso el mapa existe
 * en vez de dos columnas.
 *
 * Las teselas son de Carto en su version clara: gris y sin puntos de interes,
 * de modo que el unico color de la pantalla siga siendo el del semaforo.
 *
 * Dos decisiones que costaron un fallo cada una.
 *
 * La primera: los marcadores se crean **una vez por cambio de datos** y despues
 * solo se les cambia el estilo. La version anterior rehacia la capa entera en
 * cada movimiento del raton, y eso rompia el clic: al salir del circulo se
 * destruia el marcador que estaba a punto de recibirlo, asi que seleccionar una
 * planta no filtraba nada. Un mapa que no responde al clic no es un mapa, es un
 * dibujo.
 *
 * La segunda: la etiqueta va debajo de la burbuja y no encima. Encima tapaba el
 * circulo justo donde hay que pinchar.
 */

import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { decimal, escape, units, usdRound } from "./format.js";

const PLANTS = {
  NAVA: [28.42, -100.77],
  OBRE: [27.49, -109.94],
};

const TONE = {
  go: "#2E7D32",
  hold: "#C88700",
  stop: "#C62828",
  escalate: "#003B70",
};

const CENTER = [27.95, -105.35];
const ZOOM = 5;

let map = null;
let layer = null;
const marks = new Map();

function fit() {
  if (map) map.setView(CENTER, ZOOM, { animate: false });
}

/**
 * Dibuja el mapa con una burbuja por planta.
 *
 * El area de la burbuja —no su radio— crece con los casos abiertos, que es como
 * el ojo compara cantidades en un circulo. El color es el peor estado presente
 * en esa planta: si hay algo critico sin resolver manda el rojo.
 */
export function drawMap(plants, { onSelect, onPreview }) {
  const host = document.getElementById("map");
  if (!host) return;

  if (!map) {
    map = L.map(host, {
      zoomControl: false,
      scrollWheelZoom: false,
      doubleClickZoom: false,
      dragging: false,
      attributionControl: false,
    });

    L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
      subdomains: "abcd",
      maxZoom: 8,
      minZoom: 4,
    }).addTo(map);

    /* Leaflet fija el zoom con el tamaño que tenga el contenedor en ese
       instante. Si se mide antes de que el navegador reparta el espacio, cree
       que mide cero y encuadra sobre una superficie inexistente. El observador
       reencuadra en cuanto el contenedor tiene medidas de verdad. */
    new ResizeObserver(() => {
      map.invalidateSize({ animate: false });
      fit();
    }).observe(host);
  }

  if (layer) layer.remove();
  layer = L.layerGroup().addTo(map);
  marks.clear();

  const most = Math.max(...plants.map((plant) => plant.open), 1);

  plants.forEach((plant) => {
    const at = PLANTS[plant.id];
    if (!at) return;

    const radius = 16 + Math.sqrt(plant.open / most) * 22;
    const color = TONE[plant.level] || "#667085";

    const halo = L.circleMarker(at, {
      radius: radius + 7,
      color,
      weight: 0,
      fillColor: color,
      fillOpacity: 0,
      interactive: false,
    }).addTo(layer);

    const disc = L.circleMarker(at, {
      radius,
      color,
      weight: 2,
      opacity: 1,
      fillColor: color,
      fillOpacity: 0.22,
      className: "bubble",
    }).addTo(layer);

    const label = L.marker(at, {
      icon: L.divIcon({
        className: "bubble-label",
        html: `<span class="bubble-label__n">${plant.open}</span>
               <span class="bubble-label__name">${escape(plant.short)}</span>
               <span class="bubble-label__usd">${usdRound(plant.investment)} USD</span>`,
        iconSize: [120, 54],
        iconAnchor: [60, -radius + 4],
      }),
      interactive: false,
    }).addTo(layer);

    marks.set(plant.id, { disc, halo, label, radius, color });

    disc.on("mouseover", () => onPreview && onPreview(plant.id));
    disc.on("mouseout", () => onPreview && onPreview(null));
    disc.on("click", () => onSelect(plant.id));
  });

  map.invalidateSize({ animate: false });
  fit();
}

/**
 * Marca cual esta fijada y cual se esta mirando de paso, sin rehacer la capa.
 *
 * Separar el estilo del dibujo es lo que arregla el clic: mover el raton ya no
 * destruye el marcador que iba a recibirlo. Y de paso el mapa deja de parpadear
 * en cada movimiento.
 */
export function highlightPlant({ selected, preview }) {
  marks.forEach((mark, id) => {
    const pinned = selected === id;
    const shown = pinned || preview === id;
    const dimmed = selected && !pinned;

    mark.disc.setStyle({
      weight: pinned ? 4 : shown ? 3 : 2,
      fillOpacity: dimmed ? 0.08 : shown ? 0.5 : 0.22,
      opacity: dimmed ? 0.35 : 1,
    });

    mark.halo.setStyle({ fillOpacity: pinned ? 0.14 : 0 });

    const node = mark.label.getElement();
    if (node) {
      node.classList.toggle("bubble-label--on", shown);
      node.classList.toggle("bubble-label--off", Boolean(dimmed));
    }
  });
}

/**
 * Ficha de la planta seleccionada.
 *
 * Responde lo que se pregunta al senalar una burbuja: cuanto consume esa planta
 * al mes, cuanto tiene, cuan llena esta su bodega, cuantos casos esperan y
 * cuanto dinero se comprometio alli. La utilizacion es la cifra que no esta en
 * ninguna otra pantalla y la que dice si el problema es de espacio o de
 * reposicion.
 */
export function plantCard(plant) {
  if (!plant) return "";
  const use = plant.capacity ? (plant.stock / plant.capacity) * 100 : 0;
  const zone = use > 85 ? "stop" : use > 60 ? "hold" : "go";

  const stat = (label, value, sub = "") => `
    <div class="pstat">
      <span class="label">${label}</span>
      <strong class="pstat__n">${value}</strong>
      ${sub ? `<span class="meta">${sub}</span>` : ""}
    </div>`;

  return `
    <div class="pcard">
      <div class="pcard__head">
        <h3>${escape(plant.name)}</h3>
        <span class="meta mono">${escape(plant.warehouse)} · ${plant.parts} parts</span>
      </div>
      <div class="pcard__stats">
        ${stat("Committed here", `${usdRound(plant.investment)}`, "USD in automatic purchases")}
        ${stat("Waiting", plant.open, plant.critical
    ? `${plant.critical} of them critical`
    : plant.deferred ? `${plant.deferred} deferred` : "none critical")}
        ${stat("Stock on hand", units(plant.stock), `of ${units(plant.capacity)} refill level`)}
        ${stat("Monthly demand", `${decimal(plant.demand, 0)}`, "units")}
      </div>
      <div class="pcard__bar" title="Warehouse utilisation ${use.toFixed(0)}%">
        <span class="pcard__fill pcard__fill--${zone}" style="width:${Math.min(100, use)}%"></span>
      </div>
      <p class="meta pcard__use">${use.toFixed(0)}% of the refill level in stock</p>
    </div>`;
}
