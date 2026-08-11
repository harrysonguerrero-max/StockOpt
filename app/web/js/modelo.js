/* La salud del modelo de demanda.
 *
 * Antes eran cinco cifras en cajas iguales, un parrafo de tres frases y cinco
 * graficas con titulo en forma de pregunta —"¿El modelo aporta algo?"—, que es
 * voz de tutorial y no de instrumento. Aqui quedan a la vista las dos graficas
 * que responden si el modelo sirve; el resto del diagnostico vive detras de un
 * plegable, para quien vaya a mirarlo de verdad.
 */

import { api } from "./api.js";

const PRIMARY = {
  comparison: "Error frente a las referencias",
  series: "Proyección contra consumo real",
};

const DIAGNOSTIC = {
  scatter: "Predicho contra observado",
  errors: "Distribución del error",
  importance: "Peso de cada variable",
};

let loaded = false;

export async function loadModel() {
  if (loaded) return;

  try {
    const data = await api("/training/metrics");
    const pct = (value) => `${((value || 0) * 100).toFixed(0)}%`;
    const gain = data.metrics.mejora_vs_promedio_movil || 0;

    document.getElementById("m-line").innerHTML = `
      <div><span class="label">Error en validación</span>
        <b class="go">${(data.metrics.wmape * 100).toFixed(0)}%</b></div>
      <div><span class="label">Sobre el promedio móvil</span>
        <b class="${gain < 0.05 ? "hold" : "go"}">${(gain * 100).toFixed(1)}%</b></div>
      <div><span class="label">Sobre repetir el último mes</span>
        <b>${pct(data.metrics.mejora_vs_ultimo_mes)}</b></div>
      <div><span class="label">Sesgo</span>
        <b>${data.metrics.bias.toFixed(1)}</b></div>
      <div><span class="label">Series</span>
        <b>${data.n_series}</b></div>`;

    document.getElementById("m-verdict").textContent = gain < 0.05
      ? `Gana ${(gain * 100).toFixed(1)}% al promedio móvil: dos tercios de las series `
        + `son planas y ahí no hay estructura que aprender. La proyección final promedia `
        + `ambos métodos en lugar de apostar por el modelo.`
      : `Gana ${(gain * 100).toFixed(0)}% al promedio móvil. La proyección final combina `
        + `ambos métodos para reducir la varianza.`;

    paint("charts", PRIMARY);
    paint("charts-extra", DIAGNOSTIC);
    document.getElementById("m-fold").hidden = false;
    loaded = true;
  } catch (error) {
    document.getElementById("m-verdict").textContent = error.message;
  }
}

function paint(hostId, charts) {
  document.getElementById(hostId).innerHTML = Object.entries(charts)
    .map(([name, title]) => `
      <section class="card">
        <h3>${title}</h3>
        <img src="/api/v1/training/charts/${name}" alt="${title}" loading="lazy">
      </section>`).join("");
}

export function initModel() {
  const fold = document.getElementById("m-fold");
  fold.querySelector(".fold__head").addEventListener("click", () => {
    fold.dataset.open = fold.dataset.open === "true" ? "false" : "true";
  });
}
