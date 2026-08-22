/* Arranque y navegacion entre las vistas. */

import { apiUrl, loadQueue, state, toast } from "./api.js";
import { openCase, closeCase, setCaseListener } from "./caso.js";
import { initDatos, loadCatalog } from "./datos.js";
import { loadClassification } from "./clasificacion.js";
import { initPipeline, loadPipeline, refreshTracer } from "./pipeline.js";
import { initBudget, paintBudget, setBudgetListener } from "./presupuesto.js";
import { fillTableFilters, initTable, renderTable, setTableListener } from "./tabla.js";
import { renderTurno } from "./turno.js";

const VIEWS = ["turno", "tabla", "modelo", "datos"];

/* Los datos en crudo tienen entrada propia en la barra. La tenian escondida
   detras del pipeline, con el argumento de que a los datos se llega cuando
   surge la pregunta de que hay detras de una cifra. Pero ahi vive tambien la
   lectura del catalogo en criticidad, valor y rotacion, y el control de
   presupuesto: tres cosas que se buscan a proposito y no de paso. El enlace
   desde el pipeline sigue existiendo, porque ese camino tambien es real. */
function show(view) {
  state.view = view;
  VIEWS.forEach((name) => {
    document.getElementById(`view-${name}`).hidden = name !== view;
  });
  document.querySelectorAll(".navlink[data-view]").forEach((link) => {
    link.classList.toggle("navlink--on", link.dataset.view === view);
  });
  if (view === "modelo") loadPipeline();
  if (view === "datos") {
    loadCatalog();
    loadClassification();
  }
  window.scrollTo({ top: 0 });
}

async function refresh(fromServer = false) {
  try {
    await loadQueue(fromServer);
    fillTableFilters();
    renderTurno(openCase, () => refresh(false));
    renderTable();
    paintBudget();
    refreshTracer();
  } catch (error) {
    document.getElementById("health").innerHTML =
      `<h2 class="health__verdict">${error.message}</h2>`;
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
  toast("Data reloaded");
});

setCaseListener(() => refresh(false));
setBudgetListener(() => refresh(false));
setTableListener(openCase);
initTable();
initBudget();
initPipeline();
initDatos();
refresh(false);
