/* Arranque y navegacion entre las tres vistas. */

import { loadQueue, state, toast } from "./api.js";
import { openCase, closeCase, setCaseListener } from "./caso.js";
import { fillRawFilters, initRaw, renderRaw, setRawListener } from "./crudo.js";
import { initModel, loadModel } from "./modelo.js";
import { fillTableFilters, initTable, renderTable, setTableListener } from "./tabla.js";
import { renderTurno } from "./turno.js";

const VIEWS = ["turno", "tabla", "crudo", "modelo"];

function show(view) {
  state.view = view;
  VIEWS.forEach((name) => {
    document.getElementById(`view-${name}`).hidden = name !== view;
  });
  document.querySelectorAll(".navlink[data-view]").forEach((link) => {
    link.classList.toggle("navlink--on", link.dataset.view === view);
  });
  if (view === "modelo") loadModel();
  window.scrollTo({ top: 0 });
}

async function refresh(fromServer = false) {
  try {
    await loadQueue(fromServer);
    fillTableFilters();
    fillRawFilters();
    renderTurno(openCase);
    renderTable();
    renderRaw();
  } catch (error) {
    document.getElementById("opening-line").textContent = error.message;
    document.getElementById("opening-note").textContent = "";
  }
}

document.querySelectorAll(".navlink[data-view]").forEach((link) => {
  link.addEventListener("click", () => show(link.dataset.view));
});

document.getElementById("refresh").addEventListener("click", async () => {
  closeCase();
  await refresh(true);
  toast("Datos recargados");
});

setCaseListener(() => refresh(false));
setTableListener(openCase);
setRawListener(openCase);
initTable();
initRaw();
initModel();
refresh(false);
