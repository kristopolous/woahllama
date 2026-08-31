/* Minimal SVG/canvas charting for woah...llama. No dependencies: the page has to
   keep working from a plain static directory with no network. */
const NS = 'http://www.w3.org/2000/svg';
const DAY = 86400e3;
const tip = () => document.getElementById('tip');

const el = (n, a = {}, kids = []) => {
  const e = document.createElementNS(NS, n);
  for (const k in a) if (a[k] != null) e.setAttribute(k, a[k]);
  for (const c of [].concat(kids)) e.append(c);
  return e;
};
const fmtInt = n => n.toLocaleString('en-US');
const dayDate = (day0, i) => new Date((day0 + i * 86400) * 1000);
const fmtDay = d => d.toISOString().slice(0, 10);

/* Month boundaries, thinned so labels never collide. */
function monthTicks(day0, ndays, maxTicks) {
  const out = [];
  for (let i = 0; i < ndays; i++) {
    const d = dayDate(day0, i);
    if (d.getUTCDate() === 1) out.push({ i, d });
  }
  const step = Math.ceil(out.length / maxTicks);
  return out.filter((_, k) => k % step === 0);
}

function niceTicks(max, count = 5) {
  if (max <= 0) return [0];
  const raw = max / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].find(m => m * mag >= raw) * mag;
  const out = [];
  for (let v = 0; v <= max * 1.0001; v += step) out.push(v);
  return out;
}

function showTip(html, ev) {
  const t = tip();
  t.innerHTML = html;
  t.style.opacity = 1;
  const r = t.getBoundingClientRect();
  let x = ev.clientX + 16, y = ev.clientY - r.height / 2;
  if (x + r.width > innerWidth - 8) x = ev.clientX - r.width - 16;
  t.style.left = Math.max(8, x) + 'px';
  t.style.top = Math.min(Math.max(8, y), innerHeight - r.height - 8) + 'px';
}
const hideTip = () => { tip().style.opacity = 0; };

/* ---------------------------------------------------------------- line/area */
/* opts: {day0, ndays, series[{name,color,values}], height, stacked, percent,
          yFormat, valueFormat} */
function timeChart(host, opts) {
  const W = host.clientWidth || 1100, H = opts.height || 300;
  const M = { t: 10, r: 12, b: 24, l: 52 };
  const iw = W - M.l - M.r, ih = H - M.t - M.b;
  const { day0, ndays, series } = opts;
  const vis = series.filter(s => !s.hidden);

  // stack if asked, then find the y extent actually drawn
  let stacks = null, max = 0;
  if (opts.stacked) {
    stacks = [];
    let below = new Array(ndays).fill(0);
    for (const s of vis) {
      const top = s.values.map((v, i) => below[i] + v);
      stacks.push({ s, lo: below, hi: top });
      below = top;
    }
    max = Math.max(...below, 1);
  } else {
    for (const s of vis) for (const v of s.values) if (v > max) max = v;
    max = max || 1;
  }
  if (opts.percent) max = 100;

  const X = i => M.l + (ndays < 2 ? 0 : (i / (ndays - 1)) * iw);
  const Y = v => M.t + ih - (v / max) * ih;

  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, height: H });
  const grid = el('g', { class: 'grid' });
  const axis = el('g', { class: 'axis' });
  const ticks = niceTicks(max);
  for (const v of ticks) {
    grid.append(el('line', { x1: M.l, x2: W - M.r, y1: Y(v), y2: Y(v) }));
    axis.append(el('text', { x: M.l - 8, y: Y(v) + 4, 'text-anchor': 'end' },
      (opts.yFormat || fmtInt)(v)));
  }
  for (const t of monthTicks(day0, ndays, Math.floor(iw / 74))) {
    axis.append(el('text', { x: X(t.i), y: H - 6, 'text-anchor': 'middle' },
      t.d.toISOString().slice(0, 7)));
  }
  svg.append(grid, axis);

  const path = pts => pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' +
    p[1].toFixed(1)).join('');

  if (stacks) {
    // 2px surface gap between stacked fills, per the mark spec
    for (const { s, lo, hi } of stacks) {
      const up = hi.map((v, i) => [X(i), Y(v)]);
      const dn = lo.map((v, i) => [X(i), Y(v)]).reverse();
      svg.append(el('path', {
        d: path(up) + path(dn).replace('M', 'L') + 'Z',
        fill: s.color, stroke: 'var(--surface-1)', 'stroke-width': 2,
        'stroke-linejoin': 'round',
      }));
    }
  } else {
    for (const s of vis) {
      svg.append(el('path', {
        class: 'ser', stroke: s.color,
        d: path(s.values.map((v, i) => [X(i), Y(v)])),
        'stroke-dasharray': s.dashed ? '5 4' : null,
      }));
    }
  }

  // hover layer: nearest-day crosshair + one tooltip listing every visible series
  const cur = el('line', { class: 'cursor', y1: M.t, y2: M.t + ih, opacity: 0 });
  const dots = el('g');
  svg.append(cur, dots);
  const hit = el('rect', { x: M.l, y: M.t, width: iw, height: ih, fill: 'transparent' });
  svg.append(hit);

  const fmtV = opts.valueFormat || fmtInt;
  hit.addEventListener('mousemove', ev => {
    const bb = svg.getBoundingClientRect();
    const i = Math.round(((ev.clientX - bb.left) / bb.width * W - M.l) / iw * (ndays - 1));
    if (i < 0 || i >= ndays) return;
    cur.setAttribute('x1', X(i)); cur.setAttribute('x2', X(i));
    cur.setAttribute('opacity', 1);
    dots.replaceChildren();
    const rows = [];
    const list = stacks ? [...stacks].reverse().map(x => x.s) : vis;
    for (const s of list) {
      const v = s.values[i];
      if (opts.hideZero && !v) continue;
      if (!stacks) dots.append(el('circle', {
        cx: X(i), cy: Y(v), r: 4, fill: s.color,
        stroke: 'var(--surface-1)', 'stroke-width': 2,
      }));
      rows.push(`<tr><td><i style="background:${s.color}"></i>${s.name}</td>
        <td class="n">${fmtV(v)}</td></tr>`);
    }
    showTip(`<div class="d">${fmtDay(dayDate(day0, i))}</div>
      <table>${rows.join('')}</table>`, ev);
  });
  hit.addEventListener('mouseleave', () => {
    hideTip(); cur.setAttribute('opacity', 0); dots.replaceChildren();
  });

  host.replaceChildren(svg);
  return svg;
}

/* ------------------------------------------------------------------- legend */
function legend(host, series, onToggle) {
  host.replaceChildren(...series.map(s => {
    const sp = document.createElement('span');
    sp.className = s.hidden ? 'off' : '';
    sp.innerHTML = `<i style="background:${s.color}"></i>${s.name}`;
    if (onToggle) sp.onclick = () => onToggle(s);
    return sp;
  }));
}
