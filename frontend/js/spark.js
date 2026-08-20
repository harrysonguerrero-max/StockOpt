/* Serie de consumo dibujada en SVG.
 *
 * Sostiene el primer paso de la narrativa: sin la serie, "1,9 unidades al mes"
 * es un numero que hay que creer; con ella se ve de donde sale y si el patron
 * que declara el sistema se corresponde con lo que la planta consumio.
 *
 * Los meses que genero el build para dar profundidad al entrenamiento van en
 * linea discontinua. Dibujarlos igual que los reales seria presentar como
 * observacion algo que es un supuesto.
 *
 * La incertidumbre se dibuja como un cono que nace en la ultima observacion
 * real, con anchura cero, y se abre hasta el rango del mes proyectado. Antes era
 * una barra vertical de altura constante, que sugeria que el error ya existe
 * sobre el dato observado. No es asi: sobre lo observado no hay error, y la
 * incertidumbre aparece y crece a medida que uno se aleja del ultimo dato. El
 * cono dice eso y ademas se lee mas cerrado, sin estrechar el intervalo, que
 * seria afirmar una precision que el modelo no tiene.
 */

const W = 600;
const H = 130;
const PAD = { top: 10, right: 8, bottom: 20, left: 8 };

const path = (points) => points.map((p, i) => `${i ? "L" : "M"}${p[0]} ${p[1]}`).join(" ");

export function spark(history, forecast) {
  if (!history || history.length < 2) return "";

  const q50 = Number(forecast?.q50 ?? 0);
  const q25 = Number(forecast?.q25 ?? q50);
  const q75 = Number(forecast?.q75 ?? q50);

  const top = Math.max(...history.map((h) => h.qty), q75, 1);
  const slots = history.length; // el ultimo hueco lo ocupa la proyeccion
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;

  const x = (i) => PAD.left + (i * innerW) / slots;
  const y = (v) => PAD.top + innerH - (v / top) * innerH;

  const points = history.map((record, i) => [x(i), y(record.qty)]);
  const lastSynthetic = history.reduce(
    (last, record, i) => (record.is_synthetic ? i : last), -1
  );

  // El tramo real arranca en el ultimo punto simulado para que la linea no se
  // corte a la mitad; el cambio de trazo marca donde termina el dato generado.
  const syntheticPart = lastSynthetic >= 0 ? points.slice(0, lastSynthetic + 1) : [];
  const realPart = points.slice(Math.max(0, lastSynthetic));

  const fx = x(slots);
  const lastReal = points[points.length - 1];

  const labels = [
    { i: 0, text: history[0].month },
    { i: history.length - 1, text: history[history.length - 1].month },
  ];

  return `
<svg class="spark" viewBox="0 0 ${W} ${H}" role="img"
     aria-label="Monthly consumption and next-month forecast">
  <line x1="${PAD.left}" y1="${y(0)}" x2="${W - PAD.right}" y2="${y(0)}"
        stroke="#E3E8EF" stroke-width="1"/>

  <path d="M${lastReal[0]} ${lastReal[1]} L${fx} ${y(q75)} L${fx} ${y(q25)} Z"
        fill="#D9EAF4" opacity=".85"/>

  ${syntheticPart.length > 1
    ? `<path d="${path(syntheticPart)}" fill="none" stroke="#CBD5E1"
             stroke-width="1.5" stroke-dasharray="3 3"/>` : ""}

  ${realPart.length > 1
    ? `<path d="${path(realPart)}" fill="none" stroke="#0067A0" stroke-width="2"/>` : ""}

  <path d="M${lastReal[0]} ${lastReal[1]} L${fx} ${y(q50)}" fill="none"
        stroke="#003B70" stroke-width="2" stroke-dasharray="2 3"/>
  <circle cx="${fx}" cy="${y(q50)}" r="3.5" fill="#003B70"/>

  ${labels.map((label) => `
    <text x="${x(label.i)}" y="${H - 6}" font-size="10" fill="#667085"
          text-anchor="${label.i === 0 ? "start" : "middle"}"
          font-family="ui-monospace, monospace">${label.text}</text>`).join("")}
  <text x="${W - PAD.right}" y="${H - 6}" font-size="10" fill="#003B70"
        text-anchor="end" font-family="ui-monospace, monospace">forecast</text>
</svg>
<span class="spark__key">
  <span><i class="k-real"></i>actual consumption</span>
  ${syntheticPart.length > 1 ? '<span><i class="k-sint"></i>simulated history</span>' : ""}
  <span><i class="k-proy"></i>forecast (likely range)</span>
</span>`;
}
