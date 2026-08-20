/* Criticidad, valor y rotacion: como se lee el catalogo antes de decidir.
 *
 * Las tablas en crudo dicen que hay. Esto dice que significa: donde esta el
 * dinero, que se mueve y que para una linea cuando falta. Son las tres
 * dimensiones con que la literatura de repuestos decide donde poner el control,
 * y ninguna basta por si sola.
 *
 * Tres graficas, cada una con un trabajo distinto.
 *
 * La curva de Pareto responde a donde esta el valor. Se dibuja como curva
 * acumulada y no como barras porque la pregunta no es cuanto vale cada pieza
 * sino cuantas piezas hacen falta para llegar al 80 % del gasto.
 *
 * La dispersion de valor contra rotacion responde a que politica merece cada
 * pieza. El color es la criticidad, que es la dimension que no se puede deducir
 * de los otros dos ejes: es un juicio de mantenimiento, no una medida.
 *
 * Los dos cruces responden a donde las tres lecturas se contradicen. Esa es la
 * unica parte que no se ve en ninguna de las otras dos graficas, y es donde
 * aparece el hallazgo: piezas que rotan poco y valen poco, y que aun asi hay que
 * tener, porque paran la produccion.
 *
 * Todo se dibuja en SVG a mano. Una libreria de graficas por tres figuras
 * pesaria mas que el resto de la interfaz junta.
 */

import { api } from "./api.js";
import { count, escape, percent, usd } from "./format.js";

const el = (id) => document.getElementById(id);

const CRIT_COLOR = { A: "#C62828", B: "#C88700", C: "#0067A0" };

const report = { data: null };

/* ---------- Curva de Pareto del valor anual ---------- */

function paretoChart(parts, thresholds) {
  const width = 720;
  const height = 260;
  const pad = { top: 16, right: 16, bottom: 34, left: 46 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;

  const n = parts.length;
  const x = (index) => pad.left + ((index + 1) / n) * innerW;
  const y = (share) => pad.top + innerH - share * innerH;

  const bars = parts.map((part, index) => {
    const barW = Math.max(2, (innerW / n) * 0.72);
    const top = y(part.value_share / (parts[0].value_share || 1));
    return `<rect x="${(x(index) - barW / 2).toFixed(1)}" y="${top.toFixed(1)}"
      width="${barW.toFixed(1)}" height="${(pad.top + innerH - top).toFixed(1)}"
      fill="${CRIT_COLOR[part.criticality] || "#667085"}" opacity=".28"
      ><title>${escape(part.sku_id)} · ${usd(part.annual_value_usd)} USD/year</title></rect>`;
  }).join("");

  const curve = parts.map((part, index) =>
    `${index ? "L" : "M"}${x(index).toFixed(1)},${y(part.value_cum_share).toFixed(1)}`).join(" ");

  const dots = parts.map((part, index) => `
    <circle cx="${x(index).toFixed(1)}" cy="${y(part.value_cum_share).toFixed(1)}" r="3.4"
            fill="${CRIT_COLOR[part.criticality] || "#667085"}" stroke="#fff" stroke-width="1">
      <title>${escape(part.sku_id)} — ${escape(part.description)}
${percent(part.value_cum_share, 1)} cumulative · class ${part.value_class} · criticality ${part.criticality}</title>
    </circle>`).join("");

  /* La etiqueta del corte va a la izquierda y no a la derecha: la curva
     acumulada termina en el 100 % por la derecha, que es justo donde caeria el
     texto del corte del 95 % y donde se solaparian. */
  const cut = (share, label) => `
    <line x1="${pad.left}" y1="${y(share)}" x2="${width - pad.right}" y2="${y(share)}"
          stroke="#CBD5E1" stroke-width="1" stroke-dasharray="4 3"/>
    <text x="${pad.left + 6}" y="${(y(share) - 5).toFixed(1)}"
          font-size="10" fill="#667085">${label}</text>`;

  const ticks = [0, 0.25, 0.5, 0.75, 1].map((share) => `
    <text x="${pad.left - 8}" y="${(y(share) + 3.5).toFixed(1)}" text-anchor="end"
          font-size="10" fill="#667085">${percent(share)}</text>`).join("");

  return `
    <svg class="chart" viewBox="0 0 ${width} ${height}" role="img"
         aria-label="Cumulative share of annual value by part">
      ${ticks}
      ${cut(thresholds.value_class_a_max, `class A cut · ${percent(thresholds.value_class_a_max)}`)}
      ${cut(thresholds.value_class_b_max, `class B cut · ${percent(thresholds.value_class_b_max)}`)}
      <line x1="${pad.left}" y1="${y(0)}" x2="${width - pad.right}" y2="${y(0)}"
            stroke="#CBD5E1" stroke-width="1"/>
      ${bars}
      <path d="${curve}" fill="none" stroke="#003B70" stroke-width="2"/>
      ${dots}
      <text x="${pad.left}" y="${height - 10}" font-size="10" fill="#667085">
        parts ordered by annual value, highest first</text>
      <text x="${width - pad.right}" y="${height - 10}" text-anchor="end"
            font-size="10" fill="#667085">${n} parts</text>
    </svg>`;
}

/* ---------- Dispersion valor contra rotacion ---------- */

function scatterChart(parts, thresholds) {
  const width = 720;
  const height = 320;
  // El margen superior deja sitio al radio de la burbuja mayor: sin el, la
  // pieza que mas valor mueve —justo la que hay que mirar— sale cortada.
  const pad = { top: 30, right: 18, bottom: 40, left: 62 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;

  const maxValue = Math.max(...parts.map((p) => p.annual_value_usd), 1);
  const ceiling = Math.log10(maxValue) * 1.06;
  const x = (rate) => pad.left + Math.min(1, rate) * innerW;
  // Escala logaritmica en el valor: con un catalogo donde la pieza mayor vale
  // cien veces la menor, una escala lineal apila todo contra el eje.
  const y = (value) => {
    const share = Math.log10(Math.max(value, 1)) / ceiling;
    return pad.top + innerH - share * innerH;
  };

  const dots = parts.map((part) => `
    <circle cx="${x(part.issue_rate).toFixed(1)}" cy="${y(part.annual_value_usd).toFixed(1)}"
            r="${(5 + Math.sqrt(part.annual_units) / 4).toFixed(1)}"
            fill="${CRIT_COLOR[part.criticality] || "#667085"}" opacity=".55"
            stroke="${CRIT_COLOR[part.criticality] || "#667085"}" stroke-width="1.2">
      <title>${escape(part.sku_id)} — ${escape(part.description)}
${usd(part.annual_value_usd)} USD/year · issued on ${percent(part.issue_rate)} of days
criticality ${part.criticality} · value ${part.value_class} · rotation ${part.rotation_class}</title>
    </circle>`).join("");

  const band = (rate, label) => `
    <line x1="${x(rate)}" y1="${pad.top}" x2="${x(rate)}" y2="${pad.top + innerH}"
          stroke="#CBD5E1" stroke-width="1" stroke-dasharray="4 3"/>
    <text x="${(x(rate) + 4).toFixed(1)}" y="${pad.top + 11}" font-size="10"
          fill="#667085">${label}</text>`;

  const ticks = [1, 10, 100, 1000, 10000].filter((v) => v <= maxValue * 1.2).map((value) => `
    <text x="${pad.left - 8}" y="${(y(value) + 3.5).toFixed(1)}" text-anchor="end"
          font-size="10" fill="#667085">${usd(value)}</text>
    <line x1="${pad.left}" y1="${y(value)}" x2="${width - pad.right}" y2="${y(value)}"
          stroke="#EEF2F6" stroke-width="1"/>`).join("");

  return `
    <svg class="chart" viewBox="0 0 ${width} ${height}" role="img"
         aria-label="Annual value against rotation, coloured by criticality">
      ${ticks}
      ${band(thresholds.rotation_slow_min, `N | S · ${percent(thresholds.rotation_slow_min)}`)}
      ${band(thresholds.rotation_fast_min, `S | F · ${percent(thresholds.rotation_fast_min)}`)}
      ${dots}
      <text x="${pad.left}" y="${height - 12}" font-size="10" fill="#667085">
        rotation → share of days the part is issued</text>
      <text x="${pad.left - 8}" y="${pad.top - 4}" text-anchor="end" font-size="10"
            fill="#667085">USD/year</text>
      <text x="${width - pad.right}" y="${height - 12}" text-anchor="end" font-size="10"
            fill="#667085">bubble size = annual units · log scale on value</text>
    </svg>`;
}

/* ---------- Los cruces ---------- */

/** Una celda vacia no se atenua: se deja en blanco. Lo que la matriz tiene que
 *  hacer visible es la celda ocupada que no deberia estarlo. */
function matrix(rows, title, note, rowLabel, columnLabel) {
  const columns = rows[0] ? rows[0].cells.map((cell) => cell.column) : [];
  const most = Math.max(...rows.flatMap((row) => row.cells.map((cell) => cell.count)), 1);

  const body = rows.map((row) => `
    <tr>
      <th scope="row"><span class="matrix__key">${escape(row.row)}</span></th>
      ${row.cells.map((cell) => {
    const weight = cell.count / most;
    const names = cell.parts.map((part) => `${part.sku_id} — ${part.description}`).join("\n");
    return `<td class="matrix__cell${cell.count ? "" : " matrix__cell--empty"}"
        style="--w:${weight.toFixed(2)}"
        title="${cell.count ? escape(names) : "no parts"}">
        <b>${cell.count || ""}</b>
        ${cell.count ? `<span class="matrix__usd">${usd(cell.annual_value_usd)}</span>` : ""}
      </td>`;
  }).join("")}
      <th scope="row" class="matrix__total">${row.total}</th>
    </tr>`).join("");

  return `
    <div class="matrix">
      <h4>${escape(title)}</h4>
      <p class="meta">${note}</p>
      <table class="matrix__grid">
        <thead>
          <tr>
            <th><span class="matrix__axis">${escape(rowLabel)}</span></th>
            ${columns.map((name) =>
    `<th><span class="matrix__key">${escape(name)}</span></th>`).join("")}
            <th class="matrix__total">all</th>
          </tr>
          <tr class="matrix__axisrow">
            <td colspan="${columns.length + 2}">${escape(columnLabel)} →</td>
          </tr>
        </thead>
        <tbody>${body}</tbody>
      </table>
    </div>`;
}

/* ---------- Perfiles ---------- */

function profileTable(profile, heading) {
  return `
    <table class="mini">
      <thead>
        <tr><th>${escape(heading)}</th><th>Parts</th><th>% of variety</th>
          <th>% of value</th><th>Concentration</th></tr>
      </thead>
      <tbody>${profile.map((level) => `
        <tr>
          <td>${escape(level.label)}</td>
          <td class="num mono">${level.count}</td>
          <td class="num mono">${percent(level.variety_share, 1)}</td>
          <td class="num mono"><b>${percent(level.value_share, 1)}</b></td>
          <td class="num mono">${level.concentration === null
    ? "—" : `${level.concentration.toFixed(2)}×`}</td>
        </tr>`).join("")}</tbody>
    </table>`;
}

/* ---------- La celda que importa ---------- */

/** El hallazgo del cruce: piezas que ninguna clasificacion por separado salvaria
 *  y que la criticidad obliga a tener igual. */
function findings(data) {
  /* Basta con que una de las dos lecturas economicas diga que no invierta:
     rotar poco y valer poco son señales distintas, y cualquiera de las dos
     apunta en contra de una pieza que aun asi hay que tener. */
  const conflicted = data.parts
    .filter((part) => part.criticality === "A"
      && (part.rotation_class === "N" || part.value_class === "C"))
    .map((part) => ({
      ...part,
      against: [
        part.rotation_class === "N" ? "rotation says non-moving" : null,
        part.value_class === "C" ? "value puts it in the bottom 5%" : null,
      ].filter(Boolean).join(" and "),
    }));

  if (!conflicted.length) {
    return '<p class="finding">No criticality-A part currently sits in the low-value or '
      + "low-rotation corner. That is the cell to watch: where value and rotation both say "
      + "do not invest and criticality says the opposite.</p>";
  }

  return `
    <div class="finding">
      <p><b>Where the three readings disagree.</b>
      ${conflicted.length} criticality-A
      ${conflicted.length === 1 ? "part sits" : "parts sit"} in a corner an economic
      classification would write off: it barely moves, or it barely costs anything, so an
      ABC on value or an FSN on rotation would both say do not invest. Both are wrong here,
      because these stop a line when they run out. No single classification reaches that
      conclusion — only the cross does.</p>
      <ul>${conflicted.map((part) => `
        <li><span class="mono">${escape(part.sku_id)}</span> ${escape(part.description)} —
          ${usd(part.annual_value_usd)} USD/year, issued on ${percent(part.issue_rate)} of
          days, ${part.on_hand_qty} on hand · <i>${escape(part.against)}</i></li>`).join("")}</ul>
    </div>`;
}

/* ---------- Montaje ---------- */

function paint(data) {
  const t = data.thresholds;

  el("class-figures").innerHTML = `
    <div class="fig"><span class="label">Parts in the catalogue</span>
      <strong class="fig__n">${data.totals.parts}</strong>
      <span class="meta">across two plants</span></div>
    <div class="fig"><span class="label">Annual consumption value</span>
      <strong class="fig__n">${usd(data.totals.annual_value_usd)}</strong>
      <span class="meta">USD/year projected</span></div>
    <div class="fig"><span class="label">Capital on the shelf</span>
      <strong class="fig__n">${usd(data.totals.stock_value_usd)}</strong>
      <span class="meta">USD in stock today</span></div>
    <div class="fig"><span class="label">Units per year</span>
      <strong class="fig__n">${count(Math.round(data.totals.annual_units))}</strong>
      <span class="meta">projected across the catalogue</span></div>`;

  el("class-pareto").innerHTML = paretoChart(data.parts, t);
  el("class-scatter").innerHTML = scatterChart(data.parts, t);

  el("class-profiles").innerHTML = `
    <section class="subpanel"><h3>Criticality — what happens if it is missing</h3>
      ${profileTable(data.profiles.criticality, "Class")}
      <p class="meta">It comes from the parts master, not from the data. It is a
        maintenance judgement, and it is the only one of the three that cannot be
        derived from consumption.</p></section>
    <section class="subpanel"><h3>Value — where the money is</h3>
      ${profileTable(data.profiles.value, "Class")}
      <p class="meta">Pareto on projected annual consumption. The concentration column is
        what makes an ABC readable: 1.95× means that class holds nearly twice the value
        its share of references would suggest.</p></section>
    <section class="subpanel"><h3>Rotation — how often it moves</h3>
      ${profileTable(data.profiles.rotation, "Class")}
      <p class="meta">FSN over the issue rate, the share of days the part records any
        consumption. It is what defines obsolescence risk and the replenishment
        rhythm.</p></section>`;

  el("class-matrices").innerHTML =
    matrix(data.matrices.value_by_criticality,
      "Value × Criticality",
      "The A/A cell is where the money and the risk coincide: tight control, no debate. "
      + "The C/A cell is the one worth arguing about.",
      "value", "criticality")
    + matrix(data.matrices.rotation_by_criticality,
      "Rotation × Criticality",
      "The N/A cell is the classic case: it barely moves, so stock sits idle, but when it "
      + "fails the line stops.",
      "rotation", "criticality");

  el("class-finding").innerHTML = findings(data);
}

export async function loadClassification() {
  if (report.data) return;
  try {
    report.data = await api("/data/classification");
    paint(report.data);
  } catch (error) {
    el("class-finding").innerHTML = `<p class="meta">${escape(error.message)}</p>`;
  }
}
