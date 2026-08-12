/* Arranque y navegacion entre las vistas. */

import { apiUrl, loadQueue, state, toast } from "./api.js";
import { openCase, closeCase, setCaseListener } from "./caso.js";
import { initDatos, loadCatalog } from "./datos.js";
import { initPipeline, loadPipeline, refreshTracer } from "./pipeline.js";
import { fillTableFilters, initTable, renderTable, setTableListener } from "./tabla.js";
import { renderTurno } from "./turno.js";

const VIEWS = ["turno", "tabla", "modelo", "datos"];

/* Los datos en crudo no tienen entrada propia en la barra: se llega desde el
   pipeline, que es donde surge la pregunta de que hay detras de una cifra. */
function show(view) {
  state.view = view;
  VIEWS.forEach((name) => {
    document.getElementById(`view-${name}`).hidden = name !== view;
  });
  document.querySelectorAll(".navlink[data-view]").forEach((link) => {
    link.classList.toggle("navlink--on",
      link.dataset.view === view || (view === "datos" && link.dataset.view === "modelo"));
  });
  if (view === "modelo") loadPipeline();
  if (view === "datos") loadCatalog();
  window.scrollTo({ top: 0 });
}

async function refresh(fromServer = false) {
  try {
    await loadQueue(fromServer);
    fillTableFilters();
    renderTurno(openCase, () => refresh(false));
    renderTable();
    refreshTracer();
  } catch (error) {
    document.getElementById("opening-line").textContent = error.message;
    document.getElementById("opening-note").textContent = "";
  }
}

document.querySelectorAll(".navlink[data-view]").forEach((link) => {
  link.addEventListener("click", () => show(link.dataset.view));
});

// La descarga apunta a la API, que en Amplify vive en otro dominio.
document.getElementById("export-all").href = apiUrl("/recommendations/export");

document.getElementById("go-datos").addEventListener("click", () => show("datos"));
document.getElementById("back-modelo").addEventListener("click", () => show("modelo"));

document.getElementById("refresh").addEventListener("click", async () => {
  closeCase();
  await refresh(true);
  toast("Datos recargados");
});

setCaseListener(() => refresh(false));
setTableListener(openCase);
initTable();
initPipeline();
initDatos();
refresh(false);
