/* El mapa de plantas.
 *
 * Antes la pantalla partia los casos en dos columnas, una por ciudad. Funcionaba
 * para decir el grano de la decision, pero no lo unico que una columna no puede
 * decir: que Nava y Ciudad Obregon estan a mil kilometros, con bodega propia y
 * proveedores que no coinciden. Sobre un mapa real eso se ve solo.
 *
 * Las teselas son de Carto en su version clara: gris y sin puntos de interes,
 * de modo que el unico color de la pantalla siga siendo el del semaforo. Un mapa
 * de calles saturado competiria con las burbujas, que es lo que hay que mirar.
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

let map = null;
let layer = null;

/* Las plantas son dos y no se mueven, asi que la vista es fija y no calculada.
   `fitBounds` depende del tamaño que el contenedor tenga en el momento exacto de
   la llamada, y con el reparto de espacio aun sin resolver elegia un zoom
   demasiado cerrado. Un centro y un zoom explicitos siempre encuadran las dos. */
const CENTER = [27.95, -105.35];
const ZOOM = 6;

function fit() {
  if (map) map.setView(CENTER, ZOOM, { animate: false });
}

/**
 * Dibuja el mapa con una burbuja por planta.
 *
 * El area de la burbuja —no su radio— crece con los casos abiertos, que es como
 * el ojo compara cantidades en un circulo. El color es el peor estado presente
 * en esa planta: si hay algo sin presupuesto manda el rojo.
 */
export function drawMap(plants, { selected, onSelect }) {
  const host = document.getElementById("map");
  if (!host) return;

  if (!map) {
    map = L.map(host, {
      zoomControl: true,
      scrollWheelZoom: false,
      attributionControl: true,
    });

    L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
      attribution: "&copy; OpenStreetMap &copy; CARTO",
      subdomains: "abcd",
      maxZoom: 14,
      minZoom: 4,
    }).addTo(map);

    /* Leaflet fija el zoom con el tamaño que tenga el contenedor en ese
       instante. Si se mide antes de que el navegador reparta el espacio, cree
       que mide cero y encuadra sobre una superficie inexistente: el mapa queda
       alejadisimo y solo bajan cuatro teselas. El observador reencuadra en
       cuanto el contenedor tiene medidas de verdad, y tambien cuando cambian. */
    new ResizeObserver(() => {
      map.invalidateSize({ animate: false });
      fit();
    }).observe(host);
  }

  if (layer) layer.remove();
  layer = L.layerGroup().addTo(map);

  const most = Math.max(...plants.map((p) => p.open), 1);

  plants.forEach((plant) => {
    const at = PLANTS[plant.id];
    if (!at) return;

    const on = selected === plant.id;
    const radius = 13 + Math.sqrt(plant.open / most) * 20;
    const color = TONE[plant.level] || "#667085";

    const disc = L.circleMarker(at, {
      radius,
      color,
      weight: on ? 3 : 1.5,
      opacity: 1,
      fillColor: color,
      fillOpacity: on ? 0.42 : 0.22,
      className: "bubble",
    }).addTo(layer);

    disc.bindTooltip(
      `<b>${escape(plant.short)}</b><br>${plant.open} open ${plant.open === 1 ? "case" : "cases"}`,
      { direction: "top", offset: [0, -radius - 2] }
    );

    L.marker(at, {
      icon: L.divIcon({
        className: "bubble-label",
        html: `<span class="bubble-label__n">${plant.open}</span>
               <span class="bubble-label__name">${escape(plant.short)}</span>`,
        iconSize: [90, 40],
        iconAnchor: [45, 12],
      }),
      interactive: false,
    }).addTo(layer);

    disc.on("click", () => onSelect(plant.id));
  });

  map.invalidateSize({ animate: false });
  fit();
}

/**
 * Ficha de la planta seleccionada.
 *
 * Responde lo que se pregunta al pinchar una burbuja: cuanto consume esa planta
 * al mes, cuanto tiene, cuan llena esta su bodega, cuantos casos esperan y
 * cuanto dinero mueven. La utilizacion es la cifra que no esta en ninguna otra
 * pantalla y la que dice si el problema es de espacio o de reposicion.
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
        ${stat("Monthly demand", `${decimal(plant.demand, 0)}`, "units")}
        ${stat("Stock on hand", units(plant.stock), `of ${units(plant.capacity)} refill level`)}
        ${stat("Utilisation", `${use.toFixed(0)}%`, use > 85 ? "warehouse nearly full" : "of the refill level")}
        ${stat("Open cases", plant.open, plant.escalated
          ? `${plant.escalated} need budget`
          : plant.deferred ? `${plant.deferred} deferred` : "waiting for a decision")}
        ${stat("Purchases", `${usdRound(plant.investment)}`, "USD automatic")}
      </div>
      <div class="pcard__bar">
        <span class="pcard__fill pcard__fill--${zone}" style="width:${Math.min(100, use)}%"></span>
      </div>
    </div>`;
}
