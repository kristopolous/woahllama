/* woah...llama - page wiring */
const PAL = n => `var(--series-${n})`;
const SERIES_COLORS = [1, 2, 3, 4, 5, 6, 7, 8].map(PAL);
function vendorColors(vendors) {
  const top = Object.keys(vendors.clean)
    .sort((a, b) => Math.max(...vendors.clean[b]) - Math.max(...vendors.clean[a]))
    .slice(0, 8);
  const map = {};
  top.forEach((v, i) => { map[v] = SERIES_COLORS[i]; });
  return { map, top, other: 'var(--decoy)', colorFor: v => map[v] || 'var(--decoy)' };
}
const SOURCE_LABEL = {
  'awesome-ollama-server': 'Awesome-Ollama-Server (FOFA)',
  'ollamalist': 'ollamalist (accumulated)',
  'ollamaspider': 'OllamaSpider (Shodan)',
  'fofa-survey': 'FOFA survey (point-in-time)',
  'shodan-survey': 'Shodan survey (point-in-time)',
};

const load = n => fetch(`data/${n}.json`).then(r => {
  if (!r.ok) throw new Error(`${n}.json: ${r.status}`);
  return r.json();
});

const $ = id => document.getElementById(id);
const pct = v => v.toFixed(0) + '%';
const pair = (onA, onB, a, b, fn) => {
  const set = which => {
    onA.setAttribute('aria-pressed', which === 'a');
    onB.setAttribute('aria-pressed', which === 'b');
    fn(which === 'a');
  };
  onA.onclick = () => set('a');
  onB.onclick = () => set('b');
};

Promise.all(['counts', 'vendors', 'models', 'geo', 'octets', 'lifetime', 'world', 'pools', 'map', 'sizes', 'strange', 'probe', 'template', 'survey', 'hoarding', 'population_model', 'fake_size'].map(load))
  .then(([counts, vendors, models, geo, octets, life, world, pools, mapd, sizes, strange, probe, template, survey, hoarding, popmodel, fakeSize]) => {
    window.__popmodel = popmodel; window.__fakesize = fakeSize;
    window.__models = models; window.__geo = geo; window.__counts = counts;
    stats(counts, life, pools, mapd);
    population(counts);
    vendorChart(vendors, counts);
    modelChart(models);
    geoChart(geo);
    worldMap(world, mapd);
    bubbles(octets);
    versionSurvey(survey);
    strangeSection(strange);
    probeChart(probe);
    versionChart(probe);
    templateDecoder(template);
    sizeChart(sizes);
    quantChart(sizes);
    poolScatter(pools);
    blocksChart(models, vendors);
    lifespanHist(life);
    retentionCurve(popmodel);
    populationModel(popmodel);
    fakeSizeChart(fakeSize);
    hoardingChart(hoarding, vendors);
    addEventListener('resize', debounce(() => {
      population(counts); vendorChart(vendors, counts);
      modelChart(models, true); geoChart(geo, true);
      versionSurvey(survey);
    strangeSection(strange);
    probeChart(probe);
    versionChart(probe);
    templateDecoder(template);
    sizeChart(sizes);
    quantChart(sizes);
    poolScatter(pools); blocksChart(models, vendors); lifespanHist(life);
      retentionCurve(window.__popmodel); populationModel(window.__popmodel);
      fakeSizeChart(window.__fakesize);
      hoardingChart(hoarding, vendors);
      drawFrame(octets, +$('frame').value);
      worldMap(world, mapd);
    }, 180));
  })
  .catch(err => {
    document.querySelector('.wrap').insertAdjacentHTML('afterbegin',
      `<p style="color:var(--series-8)"><b>Could not load data:</b> ${err.message}.
       This page reads JSON with fetch(), so it needs to be served over HTTP.
       Run <code>./serve.sh</code> rather than opening the file directly.</p>`);
  });

/* Centred moving average. The scanners run at different times of day, so the
   raw daily series carries sampling noise that hides the trend. */
let SMOOTH_W = 3;
function smooth(vals, w = SMOOTH_W) {
  if (w <= 1) return vals;
  const half = (w - 1) / 2;
  return vals.map((_, i) => {
    let sum = 0, n = 0;
    for (let k = Math.max(0, i - half); k <= Math.min(vals.length - 1, i + half); k++) {
      sum += vals[k]; n++;
    }
    return sum / n;
  });
}

const debounce = (fn, ms) => { let t; return () => { clearTimeout(t); t = setTimeout(fn, ms); }; };

/* ------------------------------------------------------------------- stats */
function stats(counts, life, pools, mapd) {
  const peak = Math.max(...counts.clean);
  const peakDay = counts.clean.indexOf(peak);
  let us = 0, cn = 0;
  for (const cc in mapd.countries) {
    const o = mapd.countries[cc].o;
    us += o.US.reduce((a, b) => a + b, 0);
    cn += o.CN.reduce((a, b) => a + b, 0);
  }
  const lone = pools.scatter.filter(r => r[0] === 1).length;
  const yr = life.clean.survival.find(s => s[0] === 365)[1];
  const cells = [
    [counts.ndays, 'days watched', 'Feb 2025 – Aug 2026'],
    [life.n.toLocaleString(), 'servers found', 'each seen at least once'],
    [peak.toLocaleString(), 'open at the peak',
     new Date((counts.day0 + peakDay * 86400) * 1000).toISOString().slice(0, 10)],
    [(cn / (us + cn) * 100).toFixed(0) + '%', 'of model installs', 'come from Chinese labs'],
    [life.clean.median.toFixed(1) + 'd', 'median lifetime', 'first to last sighting'],
    [(lone / pools.scatter.length * 100).toFixed(0) + '%', 'are one machine alone',
     'not part of any fleet'],
  ];
  $('stats').innerHTML = cells.map(([v, k, s]) =>
    `<div class="stat"><div class="v">${v}</div>
     <div class="k"><b>${k}</b><br>${s}</div></div>`).join('');
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const run = () => $('stats').querySelectorAll('.v')
    .forEach((el, i) => countUp(el, cells[i][0]));
  if (reduce) { /* leave the final values in place */ }
  else if (document.hidden) {
    // rAF is paused in a background tab; animate when it first becomes visible
    const once = () => { if (!document.hidden) {
      document.removeEventListener('visibilitychange', once); run(); } };
    document.addEventListener('visibilitychange', once);
  } else run();
  void yr;
}

/* count a stat value up from zero on load, preserving its prefix/suffix and
   number format (commas, one decimal, %, d) */
function countUp(el, finalStr) {
  const m = String(finalStr).match(/^(\D*?)([\d,]+(?:\.\d+)?)(\D*)$/);
  if (!m) { el.textContent = finalStr; return; }
  const [, pre, numStr, suf] = m;
  const comma = numStr.includes(',');
  const dec = (numStr.split('.')[1] || '').length;
  const target = parseFloat(numStr.replace(/,/g, ''));
  const fmt = v => {
    let s = dec ? v.toFixed(dec) : String(Math.round(v));
    if (comma) s = Number(s).toLocaleString('en-US',
      dec ? { minimumFractionDigits: dec } : {});
    return pre + s + suf;
  };
  const dur = 950, t0 = performance.now();
  const step = now => {
    let p = Math.min(1, (now - t0) / dur);
    p = 1 - Math.pow(1 - p, 3);
    el.textContent = fmt(target * p);
    if (p < 1) requestAnimationFrame(step); else el.textContent = finalStr;
  };
  requestAnimationFrame(step);
}

/* -------------------------------------------------------------- population */
function population(counts) {
  const render = clean => {
    const src = clean ? counts.sources_clean : counts.sources;
    const series = Object.keys(src).map((k, i) => ({
      name: SOURCE_LABEL[k] || k, color: [PAL(2), PAL(3), PAL(7), PAL(4), PAL(5)][i] || PAL(6), values: src[k],
    }));
    series.push({
      name: 'Total (deduplicated)', color: PAL(1),
      values: clean ? counts.clean : counts.union,
    });
    timeChart($('pop'), { ...counts, series, height: 320 });
    legend($('pop').parentNode.querySelector('.legend') || mkLegend($('pop')), series);
  };
  pair($('pop-clean'), $('pop-all'), 1, 0, render);
  render(true);
}
function mkLegend(host) {
  const d = document.createElement('div');
  d.className = 'legend';
  host.after(d);
  return d;
}

/* ----------------------------------------------------------------- vendors */
function vendorChart(vendors, counts) {
  const totals = {};
  for (const k in vendors.clean) totals[k] = Math.max(...vendors.clean[k]);
  const top = Object.keys(totals).sort((a, b) => totals[b] - totals[a]).slice(0, 8);
  // cohort denominator: total lab attributions that day, so share reads as
  // "of the models we can trace to a lab, whose" and the shrinking overall
  // coverage cancels instead of dragging every line down together
  const allV = Object.keys(vendors.clean);
  const ndays = vendors.clean[top[0]].length;
  const cohort = Array.from({ length: ndays }, (_, d) =>
    allV.reduce((s, k) => s + vendors.clean[k][d], 0));
  const render = share => {
    const series = top.map((k, i) => ({
      name: k, color: SERIES_COLORS[i],
      values: smooth(vendors.clean[k].map((v, d) =>
        share ? (cohort[d] ? v / cohort[d] * 100 : 0) : v)),
    }));
    timeChart($('vendors'), {
      ...vendors, series, height: 340,   // no percent cap: scale to the data, not to 100
      yFormat: share ? v => v + '%' : undefined,
      valueFormat: share ? v => v.toFixed(1) + '%' : undefined,
    });
    legend($('vendors-legend'), series);
  };
  pair($('ven-share'), $('ven-abs'), 1, 0, render);
  $('smooth-w').onchange = e => {
    SMOOTH_W = +e.target.value;
    render($('ven-share').getAttribute('aria-pressed') === 'true');
    modelChart(window.__models, true);
    geoChart(window.__geo, true);
  };
  render(true);
}

/* ------------------------------------------------------------------ models */
let modelPick = null;
function modelChart(models, keep) {
  const names = Object.keys(models.clean);
  const peak = n => Math.max(...models.clean[n]);
  if (!modelPick || !keep) modelPick = names.slice().sort((a, b) => peak(b) - peak(a)).slice(0, 6);
  const sel = $('model-pick');
  if (!sel.options.length) {
    sel.innerHTML = '<option value="">Add a model…</option>' + names.slice()
      .sort((a, b) => peak(b) - peak(a))
      .map(n => { const label = n.length > 30 ? n.slice(0, 29) + '…' : n;
        return `<option value="${n}">${label} · ${peak(n).toLocaleString()}</option>`; }).join('');
    sel.onchange = () => {
      if (sel.value && !modelPick.includes(sel.value)) modelPick = [...modelPick, sel.value].slice(-8);
      sel.value = '';
      modelChart(models, true);
    };
    $('model-reset').onclick = () => { modelPick = null; modelChart(models); };
  }
  // cohort denominator: total instances of the tracked models that day, so each
  // line is share-of-the-model-mix and the coverage collapse cancels out
  const allM = Object.keys(models.clean);
  const nd = models.clean[allM[0]].length;
  const cohort = Array.from({ length: nd }, (_, d) =>
    allM.reduce((s, k) => s + models.clean[k][d], 0));
  const share = arr => smooth(arr.map((v, d) => cohort[d] ? v / cohort[d] * 100 : 0));
  const series = modelPick.map((n, i) => ({
    name: n, color: SERIES_COLORS[i % 8], values: share(models.clean[n]),
  }));
  timeChart($('models'), { ...models, series, height: 300,
    valueFormat: v => v.toFixed(1) + '%', yFormat: v => v + '%' });
  legend($('models-legend'), series, s => {
    modelPick = modelPick.filter(n => n !== s.name);
    modelChart(models, true);
  });
}

/* --------------------------------------------------------------- geography */
function geoChart(geo, keep) {
  const cc = geo.clean, N = geo.ndays;
  // total across ALL countries per day, so the stack is a true share and the
  // survey's swings in coverage cancel out
  const total = new Array(N).fill(0);
  for (const k in cc) for (let d = 0; d < N; d++) total[d] += cc[k][d];
  const top = Object.keys(cc).sort((a, b) => Math.max(...cc[b]) - Math.max(...cc[a])).slice(0, 7);
  const share = arr => smooth(arr.map((v, d) => total[d] ? v / total[d] * 100 : 0));
  const series = top.map((k, i) => ({ name: k, color: SERIES_COLORS[i], values: share(cc[k]) }));
  // everything else, as one band, so the stack reaches 100%
  const topSum = top.map(k => cc[k]);
  const other = total.map((tot, d) =>
    tot ? (tot - topSum.reduce((s, a) => s + a[d], 0)) / tot * 100 : 0);
  series.push({ name: 'Other', color: 'var(--decoy)', values: smooth(other) });
  timeChart($('geo'), { day0: geo.day0, ndays: N, series, stacked: true, percent: true,
    height: 320, hideZero: true, yFormat: v => v + '%', valueFormat: v => v.toFixed(1) + '%' });
  legend($('geo-legend'), series);
}

/* ------------------------------------------------------------ octet canvas */
/* Area = servers in that /16. With a lab selected the fill runs light-to-dark
   with that neighbourhood's share running its models, so a big pale circle
   (many servers, little of that lab) reads differently from a small dark one. */
const OCT_BREAKS = [1, 20, 40, 60, 80];
let playing = null;

function drawFrame(oct, f) {
  const c = $('octets'), dpr = devicePixelRatio || 1;
  const w = c.clientWidth || 1100, h = 620;
  if (c.width !== Math.round(w * dpr)) { c.width = w * dpr; c.height = h * dpr; }
  const g = c.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  const M = { t: 12, r: 12, b: 34, l: 46 };
  const iw = w - M.l - M.r, ih = h - M.t - M.b;
  const css = getComputedStyle(document.body);
  const sel = $('oct-vendor');
  const active = sel.dataset.hover !== undefined
    ? +sel.dataset.hover : (+sel.dataset.i || 0);
  const vi = active - 1;   // -1 = all servers, else index into oct.vendors

  g.clearRect(0, 0, w, h);
  g.strokeStyle = css.getPropertyValue('--grid'); g.lineWidth = 1;
  g.fillStyle = css.getPropertyValue('--text-muted');
  g.font = '11px ui-monospace, Menlo, monospace';
  // First octet (X) tops out at 224: 224-255 is multicast/reserved, never a host.
  // Second octet (Y) uses the full 0-255 range.
  const XMAX = 224, YMAX = 256;
  for (let t = 0; t <= XMAX; t += 32) {           // vertical grid + X labels
    const x = M.l + t / XMAX * iw;
    g.beginPath(); g.moveTo(x, M.t); g.lineTo(x, M.t + ih); g.stroke();
    g.textAlign = 'center'; g.fillText(t, x, h - 16);
  }
  for (let t = 0; t <= YMAX; t += 32) {           // horizontal grid + Y labels
    const y = M.t + ih - t / YMAX * ih;
    g.beginPath(); g.moveTo(M.l, y); g.lineTo(M.l + iw, y); g.stroke();
    g.textAlign = 'right'; g.fillText(t, M.l - 8, y + 4);
  }
  g.textAlign = 'center';
  g.fillText('first octet  \u2192', M.l + iw / 2, h - 3);

  const frame = oct.frames[f], stride = 2 + oct.vendors.length;
  let maxv = 1;
  for (let i = 1; i < frame.length; i += stride) if (frame[i] > maxv) maxv = frame[i];
  const ring = css.getPropertyValue('--surface-1');
  for (let i = 0; i < frame.length; i += stride) {
    const [o1, o2] = oct.cells[frame[i]], n = frame[i + 1];
    const x = M.l + o1 / XMAX * iw, y = M.t + ih - o2 / YMAX * ih;
    const r = 2 + Math.sqrt(n / maxv) * 17;
    let alpha;
    if (vi < 0) {
      let best = -1, bestN = 0;
      for (let k = 0; k < oct.vendors.length; k++) {
        const vn = frame[i + 2 + k];
        if (vn > bestN) { bestN = vn; best = k; }
      }
      g.fillStyle = css.getPropertyValue(best >= 0 ? `--series-${best + 1}` : '--series-1');
      alpha = 0.55;
    } else {
      // colour by the selected lab; how solid = its share of that /16
      const share = n ? frame[i + 2 + vi] / n : 0;
      g.fillStyle = css.getPropertyValue(`--series-${vi + 1}`);
      alpha = 0.08 + 0.85 * share;
    }
    g.globalAlpha = alpha;
    g.beginPath(); g.arc(x, y, r, 0, 7); g.fill();
    g.globalAlpha = Math.min(alpha, 0.5); g.strokeStyle = ring; g.lineWidth = 1.5; g.stroke();
    g.globalAlpha = 1;
  }
  $('frame-date').textContent =
    new Date((oct.day0 + f * 7 * 86400) * 1000).toISOString().slice(0, 10);
  $('oct-ramp').textContent = '';
}

function bubbles(oct) {
  const sel = $('oct-vendor');
  const redraw = () => drawFrame(oct, +$('frame').value);
  if (!sel.dataset.built) {
    sel.className = 'legend';
    const items = [{ label: 'All servers', color: 'var(--series-1)' },
      ...oct.vendors.map((v, k) => ({ label: v, color: `var(--series-${k + 1})` }))];
    const mark = () => sel.querySelectorAll('span').forEach(s =>
      s.classList.toggle('active', s.dataset.i === sel.dataset.i));
    sel.replaceChildren(...items.map((it, i) => {
      const sp = document.createElement('span');
      sp.dataset.i = i;
      sp.innerHTML = `<i style="background:${it.color}"></i>${it.label}`;
      sp.addEventListener('mouseenter', () => { sel.dataset.hover = i; redraw(); });
      sp.addEventListener('mouseleave', () => { delete sel.dataset.hover; redraw(); });
      sp.addEventListener('click', () => { sel.dataset.i = i; mark(); redraw(); });
      return sp;
    }));
    sel.dataset.built = '1'; sel.dataset.i = '0'; mark();
  }
  const slider = $('frame');
  slider.max = oct.nweeks - 1;
  slider.value = oct.nweeks - 1;
  const stop = () => { if (playing) { clearInterval(playing); playing = null; $('play').textContent = '\u25b6 Play'; } };
  slider.oninput = () => { stop(); drawFrame(oct, +slider.value); };
  $('play').onclick = () => {
    if (playing) return stop();
    if (+slider.value >= oct.nweeks - 1) slider.value = 0;
    $('play').textContent = '\u275a\u275a Pause';
    playing = setInterval(() => {
      const n = +slider.value + 1;
      if (n >= oct.nweeks) return stop();
      slider.value = n; drawFrame(oct, n);
    }, 260);
  };
  drawFrame(oct, oct.nweeks - 1);
}

/* ---- top table */
/* -------------------------------------------------------- lifespan histogram */
function lifespanHist(life) {
  const host = $('lifespan');
  const data = life.clean.hist;                 // [[label, count], ...]
  const W = host.clientWidth || 1100, rowH = 34, pad = 8;
  const H = data.length * rowH + pad * 2;
  const labelW = 108, numW = 70, iw = W - labelW - numW - 12;
  const max = Math.max(...data.map(d => d[1]));
  const total = data.reduce((a, d) => a + d[1], 0);
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, height: H });
  data.forEach(([label, n], i) => {
    const y = pad + i * rowH, bw = Math.max(2, n / max * iw);
    const last = i === data.length - 1;
    svg.append(el('text', { x: labelW - 10, y: y + rowH / 2 + 4, 'text-anchor': 'end',
      style: 'fill:var(--text-secondary);font-size:12.5px' }, label));
    const bar = el('rect', { x: labelW, y: y + 5, width: bw, height: rowH - 12, rx: 4,
      fill: last ? 'var(--series-2)' : 'var(--series-1)', opacity: last ? 0.95 : 0.85 });
    svg.append(bar);
    svg.append(el('text', { x: labelW + bw + 8, y: y + rowH / 2 + 4,
      style: 'fill:var(--text-primary);font-size:12.5px;font-family:ui-monospace,Menlo,monospace' },
      n.toLocaleString() + '  ' + (n / total * 100).toFixed(0) + '%'));
    const hit = el('rect', { x: 0, y, width: W, height: rowH, fill: 'transparent' });
    hit.addEventListener('mousemove', ev => showTip(
      `<b>${label}</b><br>${n.toLocaleString()} servers (${(n / total * 100).toFixed(1)}%)`, ev));
    hit.addEventListener('mouseleave', hideTip);
    svg.append(hit);
  });
  host.replaceChildren(svg);
  const yr = data[data.length - 1][1];
  $('lifespan-note').innerHTML =
    `Median lifespan is <b>${life.clean.median.toFixed(1)} days</b>, but
     <b>${yr.toLocaleString()}</b> servers stayed reachable for over a year.`;
}


/* continuous two-colour blend through OKLab, so a value maps to a weighted mix
   of the two endpoints (0.2 blue + 0.8 pink) with no muddy grey midpoint */
const _hex = h => { h = h.trim().replace('#', '');
  if (h.length === 3) h = h.split('').map(c => c + c).join('');
  return [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16)); };
const _lin = c => { c /= 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
const _srgb = c => Math.max(0, Math.min(255, Math.round(255 *
  (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055))));
const _oklab = (r, g, b) => { r = _lin(r); g = _lin(g); b = _lin(b);
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b),
        m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b),
        s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return [0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
          1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
          0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s]; };
const _unoklab = (L, a, b) => {
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3,
        m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3,
        s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3;
  return [_srgb(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
          _srgb(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
          _srgb(-0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)]; };
function blendOklab(hexA, hexB, t) {
  const A = _oklab(..._hex(hexA)), B = _oklab(..._hex(hexB));
  return 'rgb(' + _unoklab(...A.map((v, i) => v + (B[i] - v) * t)).join(',') + ')';
}

/* -------------------------------------------------------------- world map */
/* Every metric is a composition drawn against a midpoint, because a choropleth
   of a raw magnitude is just a population map. Two midpoints are in use: the
   lab-origin split is centred on "even", the rest on the world rate that month,
   so the colour always means "unlike everywhere else". */
const MIN_INSTALLS = 25;   // a country needs enough installs for a ratio to mean anything
const LEAD_INSTALLS = 80;  // and rather more before it heads the leaderboard
const WINDOW = 10;  // weeks either side: a ~5-month sample sits behind every
                    // frame, so the finer step smooths the animation, not the data

function worldMap(world, M) {
  const host = $('map');
  const W = host.clientWidth || 1100, H = Math.round(W * 0.46);
  const LAT0 = 84, LAT1 = -58;
  const X = lon => (lon + 180) / 360 * W;
  const Y = lat => (LAT0 - lat) / (LAT0 - LAT1) * H;
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('height', H);
  svg.innerHTML = `<defs><pattern id="nodata" width="6" height="6"
      patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
      <rect width="6" height="6" fill="var(--land)"/>
      <line x1="0" y1="0" x2="0" y2="6" stroke="var(--coast)" stroke-width="2"/>
    </pattern></defs>`;

  const SLICES = {
    lean: { label: 'Chinese vs American labs' },
    unc:  { label: 'Uncensored models', num: 'unc', den: 'inst' },
    big:  { label: 'Models 30B and larger', num: 'big', den: 'sized' },
    lowq: { label: '4-bit or coarser weights', num: 'lowq', den: 'qknown' },
  };
  const slice = k => SLICES[k] || { num: null, den: 'inst' };
  const pick = (c, key, m) => win(key.startsWith('v:') ? c.v[key.slice(2)] : c[slice(key).num], m);
  const base_of = (c, key, m) => win(key.startsWith('v:') ? c.inst : c[slice(key).den], m);

  const host_pills = $('map-metric');
  const items = [...Object.entries(SLICES).map(([k, v]) => [k, v.label]),
                 ...M.vendors.map(v => ['v:' + v, v])];
  if (!host_pills.dataset.built) {
    host_pills.className = 'pills';
    host_pills.innerHTML = items.map(([k, label]) =>
      `<button class="pill" data-key="${k}">${label}</button>`).join('');
    host_pills.dataset.built = '1';
  }
  const sel = { value: host_pills.dataset.value || 'lean' };
  const syncPills = () => host_pills.querySelectorAll('.pill').forEach(b =>
    b.setAttribute('aria-pressed', b.dataset.key === sel.value));

  const win = (arr, m) => {
    let s = 0;
    for (let k = Math.max(0, m - WINDOW); k <= Math.min(M.months.length - 1, m + WINDOW); k++) s += arr[k];
    return s;
  };

  // metric on a record (country or city — identical shape)
  const metric = (c, m) => {
    if (!c) return null;
    const srv = win(c.srv, m);
    if (!srv) return null;
    const key = sel.value || 'lean';
    if (key === 'lean') {
      const us = win(c.o.US, m), cn = win(c.o.CN, m);
      if (us + cn === 0) return null;
      const d = (cn - us) / (cn + us);
      return { d, srv, installs: us + cn,
        label: d > 0 ? `${(d * 100).toFixed(0)}% toward Chinese labs`
                     : `${(-d * 100).toFixed(0)}% toward American labs`,
        detail: `${cn} installs from Chinese labs · ${us} from American` };
    }
    const inst = base_of(c, key, m);
    if (!inst) return null;
    const num = pick(c, key, m);
    const rate = num / inst, base = window.__mapBase;
    if (!base) return null;
    const d = Math.max(-1, Math.min(1, Math.log2(rate / base) / 2));
    return { d, srv, rate, base, installs: inst,
      label: `${(rate * 100).toFixed(1)}% of installs (world ${(base * 100).toFixed(1)}%)`,
      detail: `${(rate / base).toFixed(1)}× the world rate · ${num} of ${inst} installs` };
  };

  const worldBase = m => {
    const key = sel.value || 'lean';
    if (key === 'lean') return null;
    let num = 0, den = 0;
    for (const cc in M.countries) {
      den += base_of(M.countries[cc], key, m);
      num += pick(M.countries[cc], key, m);
    }
    return den ? num / den : null;
  };

  const css = getComputedStyle(document.body);
  const BLUE = css.getPropertyValue('--map-blue') || '#2f7fd6';
  const PINK = css.getPropertyValue('--map-pink') || '#d63f95';
  const ramp = t => blendOklab(BLUE, PINK, Math.max(0, Math.min(1, t)));
  const toRamp = r => ramp(0.5 + 0.5 * Math.tanh(r.d * 2.2));
  const toOp = r => 0.08 + 0.82 * Math.min(1, (r.installs || 0) / 300);

  // country layer
  const gCountries = document.createElementNS(NS, 'g');
  const paths = {};
  for (const f of world) {
    const d = f.g.map(r => r.map((p, i) =>
      (i ? 'L' : 'M') + X(p[0]).toFixed(1) + ' ' + Y(p[1]).toFixed(1)).join('') + 'Z').join('');
    const p = document.createElementNS(NS, 'path');
    p.setAttribute('d', d);
    p.setAttribute('fill', 'url(#nodata)');
    p.setAttribute('vector-effect', 'non-scaling-stroke');
    (paths[f.cc] = paths[f.cc] || []).push(p);
    p.addEventListener('mousemove', ev => {
      const m = +$('map-frame').value;
      window.__mapBase = worldBase(m);
      const r = metric(M.countries[f.cc], m);
      const body = !r ? 'no servers seen'
        : `<b>${r.label}</b><br>${r.detail}`
          + (r.installs < 30 ? '<br><span style="color:var(--text-muted)">small sample</span>' : '');
      showTip(`<div class="d">${f.n} · ${M.months[m]}</div>${body}`, ev);
    });
    p.addEventListener('mouseleave', hideTip);
    gCountries.append(p);
  }

  // plain-land backdrop for city mode
  const gLand = document.createElementNS(NS, 'g');
  gLand.setAttribute('display', 'none');
  for (const f of world) {
    const d = f.g.map(r => r.map((p, i) =>
      (i ? 'L' : 'M') + X(p[0]).toFixed(1) + ' ' + Y(p[1]).toFixed(1)).join('') + 'Z').join('');
    gLand.append(el('path', { d, fill: 'var(--land)', stroke: 'var(--coast)',
      'stroke-width': 0.5, 'vector-effect': 'non-scaling-stroke' }));
  }

  // city layer
  const maxWin = (() => {
    let mx = 1;
    for (const c of M.cities) for (let m = 0; m < M.months.length; m++) mx = Math.max(mx, win(c.srv, m));
    return mx;
  })();
  const gCities = document.createElementNS(NS, 'g');
  gCities.setAttribute('display', 'none');
  const cityMarks = M.cities.map(c => {
    const circ = el('circle', { cx: X(c.lon), cy: Y(c.lat), r: 0,
      fill: 'var(--text-muted)', 'fill-opacity': 0.62, stroke: 'var(--surface-1)',
      'stroke-width': 1, 'vector-effect': 'non-scaling-stroke' });
    circ.addEventListener('mousemove', ev => {
      const m = +$('map-frame').value;
      window.__mapBase = worldBase(m);
      const r = metric(c, m), n = win(c.srv, m);
      const body = !r ? `${n} server${n === 1 ? '' : 's'}`
        : `<b>${r.label}</b><br>${r.detail}`;
      showTip(`<div class="d">${c.city}, ${c.cc} · ${M.months[m]}</div>${body}`, ev);
    });
    circ.addEventListener('mouseleave', hideTip);
    gCities.append(circ);
    return { c, circ };
  });

  svg.append(gLand, gCountries, gCities);
  host.replaceChildren(svg);
  addZoom(host, svg, W, H);

  let mode = host.dataset.mode || 'country';

  const paint = m => {
    window.__mapBase = worldBase(m);
    const lean = (sel.value || 'lean') === 'lean';
    const scored = [];
    if (mode === 'country') {
      for (const cc in paths) {
        const r = metric(M.countries[cc], m);
        let fill = 'url(#nodata)', op = 1;
        if (r) { fill = toRamp(r); op = toOp(r); scored.push([cc, r]); }
        for (const el of paths[cc]) { el.setAttribute('fill', fill); el.setAttribute('fill-opacity', op); }
      }
    } else {
      for (const { c, circ } of cityMarks) {
        const n = win(c.srv, m);
        const r = n ? metric(c, m) : null;
        circ.setAttribute('r', n ? 2 + Math.sqrt(n / maxWin) * 22 : 0);
        if (r) {
          circ.setAttribute('fill', toRamp(r));
          circ.setAttribute('fill-opacity', 0.35 + 0.4 * toOp(r));
          scored.push([c.city, r]);
        } else {
          circ.setAttribute('fill', 'var(--text-muted)');
          circ.setAttribute('fill-opacity', 0.3);
        }
      }
    }
    $('map-date').textContent = M.months[m];
    const loLab = lean ? 'American' : 'below world', hiLab = lean ? 'Chinese' : 'above world';
    $('map-ramp').innerHTML = (lean ? 'installs lean '
      : `vs the world rate (${(window.__mapBase * 100).toFixed(1)}%) `)
      + `<span class="b">${loLab}</span>`
      + `<i style="width:140px;height:12px;border-radius:3px;opacity:0.9;`
      + `background:linear-gradient(90deg,${ramp(0)},${ramp(0.5)},${ramp(1)})"></i>`
      + `<span class="b">${hiLab}</span>`;
    const rank = scored.filter(([, r]) => r.installs >= LEAD_INSTALLS)
                       .sort((a, b) => b[1].d - a[1].d);
    const fmt = ([nm, r]) => `<b>${nm}</b> ${lean
      ? (r.d > 0 ? '+' : '') + (r.d * 100).toFixed(0)
      : (r.rate / r.base).toFixed(1) + '×'}`;
    $('map-lead').innerHTML = rank.length
      ? (lean ? 'most Chinese: ' : 'highest: ') + rank.slice(0, 3).map(fmt).join(' · ')
        + (lean ? ' &nbsp;·&nbsp; most American: ' + rank.slice(-3).reverse().map(fmt).join(' · ') : '')
      : '';
  };

  // mode toggle
  const modeHost = $('map-mode');
  if (!modeHost.dataset.built) {
    modeHost.className = 'seg';
    modeHost.innerHTML = '<button data-mode="country" aria-pressed="true">By country</button>'
      + '<button data-mode="city">By city</button>';
    modeHost.dataset.built = '1';
  }
  const applyMode = () => {
    gCountries.setAttribute('display', mode === 'country' ? 'block' : 'none');
    gLand.setAttribute('display', mode === 'city' ? 'block' : 'none');
    gCities.setAttribute('display', mode === 'city' ? 'block' : 'none');
    modeHost.querySelectorAll('button').forEach(b =>
      b.setAttribute('aria-pressed', b.dataset.mode === mode));
  };
  modeHost.onclick = e => {
    const b = e.target.closest('button');
    if (!b) return;
    mode = host.dataset.mode = b.dataset.mode;
    applyMode(); paint(+$('map-frame').value);
  };
  applyMode();

  const slider = $('map-frame');
  slider.max = M.months.length - 1;
  if (!slider.dataset.init) { slider.value = M.months.length - 2; slider.dataset.init = '1'; }
  let timer = null;
  const stop = () => { clearInterval(timer); timer = null; $('map-play').textContent = '▶ Play'; };
  slider.oninput = () => { stop(); paint(+slider.value); };
  host_pills.onclick = e => {
    const b = e.target.closest('.pill');
    if (!b) return;
    sel.value = host_pills.dataset.value = b.dataset.key;
    syncPills(); paint(+slider.value);
  };
  syncPills();
  $('map-play').onclick = () => {
    if (timer) return stop();
    if (+slider.value >= M.months.length - 2) slider.value = 0;
    $('map-play').textContent = '❚❚ Pause';
    timer = setInterval(() => {
      const n = +slider.value + 1;
      if (n >= M.months.length) return stop();
      slider.value = n; paint(n);
    }, 90);
  };
  paint(+slider.value);
}


/* ------------------------------------------------------ operator behaviour */
/* Block sizes are small integers, so a scatter leaves broad empty bands between
   1, 2, 3... on a log axis. Bucketing into evenly spaced columns and drawing the
   distribution of lifespans in each shows the same thing with no dead space. */
const POOL_BUCKETS = [
  [1, 1, '1'], [2, 2, '2'], [3, 4, '3–4'], [5, 9, '5–9'],
  [10, 19, '10–19'], [20, 1e9, '20+'],
];

function poolScatter(pools) {
  const host = $('pools');
  const W = host.clientWidth || 1100, H = 420;
  const M = { t: 18, r: 18, b: 52, l: 62 };
  const iw = W - M.l - M.r, ih = H - M.t - M.b;
  const q = (v, p) => v[Math.min(v.length - 1, Math.floor(v.length * p))];
  const stats = POOL_BUCKETS.map(([lo, hi, label]) => {
    const v = pools.scatter.filter(r => r[0] >= lo && r[0] <= hi)
      .map(r => Math.max(r[1], 1)).sort((a, b) => a - b);
    return { label, n: v.length, p10: q(v, .10), p25: q(v, .25),
             med: q(v, .50), p75: q(v, .75), p90: q(v, .90) };
  });
  // domain from the data, not a round number: whiskers top out near 280 days and
  // a fixed 600-day axis spends half the height on nothing
  const top = Math.max(...stats.map(s => s.p90)) * 1.2;
  const Y = d => M.t + ih - Math.log10(Math.max(d, 1)) / Math.log10(top) * ih;

  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, height: H });
  const grid = el('g', { class: 'grid' }), axis = el('g', { class: 'axis' });
  for (const d of [1, 3, 7, 14, 30, 60, 90, 180, 365].filter(d => d <= top)) {
    grid.append(el('line', { x1: M.l, x2: W - M.r, y1: Y(d), y2: Y(d) }));
    axis.append(el('text', { x: M.l - 9, y: Y(d) + 4, 'text-anchor': 'end' },
      d >= 365 ? '1yr' : d >= 30 ? (d / 30 | 0) + 'mo' : d + 'd'));
  }
  svg.append(grid, axis);

  const step = iw / stats.length;
  const bw = Math.min(74, step * 0.52);
  stats.forEach((s, i) => {
    const cx = M.l + step * (i + 0.5);
    const g = el('g');
    // whisker p10-p90, box p25-p75, median rule
    g.append(el('line', { x1: cx, x2: cx, y1: Y(s.p10), y2: Y(s.p90),
                          stroke: 'var(--text-muted)', 'stroke-width': 1.5 }));
    g.append(el('rect', { x: cx - bw / 2, y: Y(s.p75), width: bw,
                          height: Math.max(2, Y(s.p25) - Y(s.p75)), rx: 4,
                          fill: 'var(--series-1)', opacity: .85,
                          stroke: 'var(--surface-1)', 'stroke-width': 2 }));
    g.append(el('line', { x1: cx - bw / 2, x2: cx + bw / 2, y1: Y(s.med), y2: Y(s.med),
                          stroke: 'var(--surface-1)', 'stroke-width': 3 }));
    g.append(el('text', { x: cx, y: Y(s.med) - 12, 'text-anchor': 'middle',
                          fill: 'var(--text-primary)',
                          style: 'font:600 12px ui-sans-serif,system-ui,sans-serif' },
                          s.med + 'd'));
    const hit = el('rect', { x: cx - step / 2, y: M.t, width: step, height: ih,
                             fill: 'transparent' });
    hit.addEventListener('mousemove', ev => showTip(
      `<div class="d">${s.label} server${s.label === '1' ? '' : 's'} in one /24</div>
       <table>
        <tr><td>blocks</td><td class="n">${s.n.toLocaleString()}</td></tr>
        <tr><td>median lifespan</td><td class="n">${s.med}d</td></tr>
        <tr><td>middle half</td><td class="n">${s.p25}–${s.p75}d</td></tr>
        <tr><td>10th–90th pct</td><td class="n">${s.p10}–${s.p90}d</td></tr>
       </table>`, ev));
    hit.addEventListener('mouseleave', hideTip);
    g.append(hit);
    svg.append(g);
    axis.append(el('text', { x: cx, y: H - 30, 'text-anchor': 'middle' }, s.label));
    axis.append(el('text', { x: cx, y: H - 16, 'text-anchor': 'middle',
                             style: 'font-size:10px' }, 'n=' + s.n.toLocaleString()));
  });
  axis.append(el('text', { x: M.l + iw / 2, y: H - 2, 'text-anchor': 'middle' },
                 'most servers the block ever ran at once'));
  host.replaceChildren(svg);

  const big = pools.scatter.filter(r => r[0] >= 20).sort((a, b) => b[0] - a[0]);
  const peak = stats.reduce((a, b) => (b.med > a.med ? b : a));
  $('pools-note').innerHTML =
    `Median lifespan climbs from <b>${stats[0].med} day</b> for a lone server to
     <b>${peak.med} days</b> at ${peak.label} servers, then falls to
     <b>${stats[5].med} days</b> for the ${stats[5].n} blocks that ever ran 20 or more
     at once. The two largest (${big[0][0]} servers in ${big[0][2]}, ${big[1][0]} in
     ${big[1][2]}) were each gone within a day. Whoever stands up a big fleet of these
     is not standing it up for long.`;
}



/* ------------------------------------------------- model size & quantisation */
/* Size and quantisation are ordered magnitudes, not categories, so both stacks
   use the sequential ramp light-to-dark rather than eight unrelated hues - the
   stack then reads as "getting bigger" on sight. Denominator is installs whose
   size is known, not all installs. */
const SEQ = i => `var(--seq-${i})`;
function pctOf(num, den, share) {
  return num.map((v, i) => share ? (den[i] ? v / den[i] * 100 : 0) : v);
}

function coverage(known, total) {
  const k = known.reduce((a, b) => a + b, 0), t = total.reduce((a, b) => a + b, 0);
  return `Resolved for ${(k / t * 100).toFixed(0)}% of installs `
       + `(${k.toLocaleString()} of ${t.toLocaleString()}); the rest are custom or
          re-uploaded names that state neither.`;
}

function sizeChart(sz) {
  const render = share => {
    const shown = sz.bands.filter(b => sz.band[b].some(v => v));
    const series = shown.map((b, i) => ({
      name: b, color: SEQ(Math.round(i / Math.max(1, shown.length - 1) * 6)),
      values: smooth(pctOf(sz.band[b], sz.known_size, share)),
    }));
    timeChart($('sizes'), {
      day0: sz.day0, ndays: sz.ndays, series, stacked: true, height: 320,
      percent: share, hideZero: true,
      yFormat: share ? v => v + '%' : undefined,
      valueFormat: share ? v => v.toFixed(1) + '%' : v => Math.round(v).toLocaleString(),
    });
    legend($('sizes-legend'), series);
  };
  pair($('sz-share'), $('sz-abs'), 1, 0, render);
  render(true);
  $('sizes-note').textContent = coverage(sz.known_size, sz.installs);
}

function quantChart(sz) {
  const order = ['q2', 'q3', 'q4', 'q5', 'q6', 'q8', '16-bit', '32-bit'];
  const keys = order.filter(k => sz.quant[k]).concat(
    Object.keys(sz.quant).filter(k => !order.includes(k)));
  const series = keys.map((k, i) => ({
    name: k, color: SEQ(Math.round(i / Math.max(1, keys.length - 1) * 6)),
    values: smooth(pctOf(sz.quant[k], sz.known_quant, true)),
  }));
  timeChart($('quants'), {
    day0: sz.day0, ndays: sz.ndays, series, stacked: true, height: 280,
    percent: true, hideZero: true,
    yFormat: v => v + '%', valueFormat: v => v.toFixed(1) + '%',
  });
  legend($('quants-legend'), series);
  $('quants-note').textContent = coverage(sz.known_quant, sz.installs);
}


/* ------------------------------------------------------- strange servers */
/* Mostly tables and one bar chart: the claims here are specific enough that
   naming the port and the number beats shading a region. */
function strangeSection(S) {
  $('phantom-cat').textContent = S.phantom.catalogue.join('\n');
  const snap = S.phantom.snapshot;
  $('phantom-note').innerHTML =
    `Today <b>${snap.now_phantom.toLocaleString()} of ${snap.now_total.toLocaleString()}</b>
     servers in OllamaSpider's live snapshot carry this exact list,
     <b>${snap.now_pct}%</b> of the feed, up from ${snap.early_pct}% when it first
     appeared in early 2025. Over the full seventeen months
     ${S.phantom.exact.toLocaleString()} distinct entries matched it exactly and
     ${S.phantom.near.toLocaleString()} more matched it bar an entry or two. The list is
     frozen, never once joined by a model newer than early 2024, yet fresh copies keep
     appearing every month.`;

  const inf = S.inflation;
  $('inflation-note').innerHTML =
    `The raw count also double-counts. Across the whole history these
     ${inf.hostport.toLocaleString()} bogus host:port entries resolve to only
     <b>${inf.distinct_ip.toLocaleString()} distinct machines</b>.
     ${inf.multi_port_ips.toLocaleString()} answer the same fixed catalogue on more than
     one port, one on <b>${inf.max_ports}</b> at once, and a scanner logs every port as a
     separate server. It is one more reason not to trust any single feed's headline
     number.`;

  $('phantom-sizes').innerHTML = '<thead><tr><th>model</th>'
    + '<th style="text-align:right">size to the byte</th>'
    + '<th style="text-align:right">servers</th>'
    + '<th style="text-align:right">distinct sizes</th>'
    + '<th style="text-align:right">on the one value</th></tr></thead><tbody>'
    + S.phantom.size_fingerprint.map(([name, bytes, n, distinct, share]) =>
        `<tr><td><code>${name}</code></td>
         <td class="n">${(bytes / 1e9).toFixed(2)} GB</td>
         <td class="n">${n.toLocaleString()}</td>
         <td class="n">${distinct}</td>
         <td class="n"><b>${share}%</b></td></tr>`).join('') + '</tbody>';

  $('phantom-ports').innerHTML = '<thead><tr><th>port</th>'
    + '<th style="text-align:right">addresses in the fleet</th></tr></thead><tbody>'
    + S.phantom.ports.map(([name, n]) =>
        `<tr><td>${name}</td><td class="n">${n.toLocaleString()}</td></tr>`).join('')
    + '</tbody>';

  // horizontal bars: a ranked magnitude over named categories
  const max = S.ports.top[0][1];
  $('ports').innerHTML = '<table class="data"><tbody>' + S.ports.top.slice(0, 16)
    .map(([port, n, name]) => {
      const own = port === 11434 || port === 11435;
      return `<tr class="barrow">
        <td style="width:64px"><code>${port}</code></td>
        <td style="width:150px;color:var(--text-secondary)">${name || ''}</td>
        <td><span class="bar" style="width:${Math.max(1.5, n / max * 100)}%;
            background:${own ? 'var(--series-1)' : 'var(--decoy)'}"></span></td>
        <td class="n" style="width:70px">${n.toLocaleString()}</td></tr>`;
    }).join('') + '</tbody></table>';

  // dumbbell: real published size (small dot) vs the size the host reports (big dot)
  (function () {
    const host = $('invented');
    const rows = S.invented.examples.slice(0, 12);
    const W = host.clientWidth || 1000, rowH = 30;
    const M = { t: 26, r: 66, b: 6, l: 196 };
    const H = rows.length * rowH + M.t + M.b, iw = W - M.l - M.r;
    const gb = b => b / 1e9;
    const lo = Math.min(...rows.map(r => Math.min(gb(r[2]), gb(r[3])))) * 0.7;
    const hi = Math.max(...rows.map(r => Math.max(gb(r[2]), gb(r[3])))) * 1.3;
    const X = g => M.l + (Math.log10(g) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo)) * iw;
    const REAL = 'var(--series-3)', REP = 'var(--series-8)';
    const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, height: H });
    const grid = el('g', { class: 'grid' }), axis = el('g', { class: 'axis' });
    for (const g of [0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000]) {
      if (g < lo || g > hi) continue;
      grid.append(el('line', { x1: X(g), x2: X(g), y1: M.t - 6, y2: H - M.b }));
      axis.append(el('text', { x: X(g), y: M.t - 12, 'text-anchor': 'middle' },
        g >= 1000 ? (g / 1000) + 'TB' : g + 'GB'));
    }
    svg.append(grid, axis);
    rows.forEach(([url, name, got, real, ratio], i) => {
      const y = M.t + i * rowH + rowH / 2;
      const xr = X(gb(real)), xg = X(gb(got));
      const g = el('g');
      g.append(el('text', { x: M.l - 12, y: y + 4, 'text-anchor': 'end',
        style: 'fill:var(--text-secondary);font-size:12px;font-family:ui-monospace,Menlo,monospace' },
        name.length > 24 ? name.slice(0, 23) + '…' : name));
      g.append(el('line', { x1: xr, x2: xg, y1: y, y2: y,
        stroke: 'var(--text-muted)', 'stroke-width': 2 }));
      g.append(el('circle', { cx: xr, cy: y, r: 4.5, fill: REAL,
        stroke: 'var(--surface-1)', 'stroke-width': 1.5 }));
      g.append(el('circle', { cx: xg, cy: y, r: 6.5, fill: REP,
        stroke: 'var(--surface-1)', 'stroke-width': 1.5 }));
      g.append(el('text', { x: W - M.r + 10, y: y + 4,
        style: 'fill:var(--text-primary);font-size:12px;font-family:ui-monospace,Menlo,monospace' },
        ratio + '\u00d7'));
      const hit = el('rect', { x: 0, y: y - rowH / 2, width: W, height: rowH, fill: 'transparent' });
      hit.addEventListener('mousemove', ev => showTip(
        `<b>${name}</b><br>reports ${gb(got).toFixed(1)} GB<br>real ${gb(real).toFixed(1)} GB` +
        `<br>out by ${ratio}\u00d7`, ev));
      hit.addEventListener('mouseleave', hideTip);
      g.append(hit);
      svg.append(g);
    });
    host.replaceChildren(svg);
    legend($('invented-legend'), [
      { name: 'real published size', color: REAL },
      { name: 'size the host reports', color: REP },
    ]);
  })();

}


/* --------------------------------------------------- the live probe result */
/* One bar per probed model. The saturated colour is the servers that actually
   answered the question; everything else is a way of not answering, in greys. */
function probeChart(P) {
  const grey = ['var(--decoy)', '#b8b8ae', '#8f8f86', '#a5a59b'];
  const catOf = r => [
    ['Answered', r.genuine, 'var(--series-1)'],
    ['Silent', r.silent, grey[0]],
    ['Madlibs filler', r.canned, grey[1]],
    ['Cloud stub', r.cloud_stub || 0, grey[2]],
    ['Refused', r.refusal || 0, grey[3]],
  ].filter(c => c[1]);
  const rows = P.runs.map(r => {
    const bar = catOf(r).map(([lab, n, c]) =>
      `<div title="${lab}: ${n}" style="width:${n / r.probed * 100}%;background:${c};
        min-width:${n ? 2 : 0}px"></div>`).join('');
    return `<div style="margin-bottom:14px">
      <div style="display:flex;justify-content:space-between;font-size:12.5px;
          margin-bottom:5px;gap:10px;flex-wrap:wrap">
        <span><b><code>${r.model}</code></b>
          <span class="askedfor" data-prompt="${(r.prompt || '').replace(/"/g, '&quot;')}"
            style="color:var(--text-muted);cursor:help;text-decoration:underline dotted">
            · asked for ${r.test}</span></span>
        <span style="color:var(--text-secondary)">${r.genuine} of ${r.probed} answered
          <b style="color:var(--text-primary)">${(r.genuine / r.probed * 100).toFixed(1)}%</b></span>
      </div>
      <div style="display:flex;height:36px;border-radius:8px;overflow:hidden;
          border:1px solid var(--border)">${bar}</div></div>`;
  }).join('');
  const legend = [
    ['Answered the question', 'var(--series-1)'],
    ['Silent', grey[0]], ['Madlibs filler, never answered', grey[1]],
    ['Cloud stub', grey[2]], ['Refused', grey[3]],
  ].map(([l, c]) => `<span><i style="background:${c}"></i>${l}</span>`).join('');
  $('probe').innerHTML = rows +
    `<div class="legend" style="margin-top:4px;gap:6px 20px">${legend}</div>`;
  $('probe').querySelectorAll('.askedfor').forEach(el => {
    el.addEventListener('mousemove', ev => showTip(
      `<div class="d">prompt sent</div>${el.dataset.prompt}`, ev));
    el.addEventListener('mouseleave', hideTip);
  });
  const lo = Math.min(...P.runs.map(r => r.genuine / r.probed * 100));
  const hi = Math.max(...P.runs.map(r => r.genuine / r.probed * 100));
  $('tpl-note') && 0;
  $('probe-note').innerHTML =
    `Three models, two different test questions, on different days, and the answer barely
     moves. <b>${lo.toFixed(1)} to ${hi.toFixed(1)}%</b> of the probed hosts run a model that
     can follow a one-line instruction. The same
     <b>${P.stable_real_count || 0}</b> IPs answer across probes, so the split is
     a real property of this population, not sampling luck. The rest reply with fluent
     filler that quotes your prompt back and never answers it. <b>Every one of these
     probed hosts came from OllamaSpider's feed.</b> This is a statement about that
     population, not about open servers in general.`;
}

/* ------------------------------------------------ the template phrase banks */
/* Three columns, one per slot, with a live sample assembled from them so the
   reader can watch the "AI reply" being built out of fixed parts. */
function templateDecoder(T) {
  $('tpl-combos').textContent = T.combos.toLocaleString();
  const col = (title, items, cls) => `<div style="flex:1;min-width:200px">
    <div style="font-size:11px;color:var(--text-muted);text-transform:uppercase;
      letter-spacing:.05em;margin-bottom:6px">${title}</div>
    ${items.map((x, i) => `<div class="tpl-chip" data-${cls}="${i}"
        style="padding:5px 9px;margin-bottom:4px;border-radius:6px;font-size:12px;
        background:var(--surface-2);border:1px solid var(--border);cursor:default">
        ${x}</div>`).join('')}</div>`;
  $('template').innerHTML =
    `<div style="display:flex;gap:14px;flex-wrap:wrap;align-items:flex-start">
      ${col('opener × ' + T.opener.length, T.opener, 'o')}
      ${col('middle × ' + T.middle.length, T.middle, 'm')}
      ${col('closer × ' + T.closer.length, T.closer, 'c')}
    </div>`;
  // rotate a live assembled sample
  const YOUR = 'This is test do not be conversational...';
  const pick = a => a[Math.floor(Math.random() * a.length)];
  const roll = () => {
    $('tpl-note').innerHTML = `<span style="color:var(--text-muted)">one of
      ${T.combos} outputs:</span> <b>${pick(T.opener)}</b>
      Regarding &ldquo;<span style="color:var(--text-muted)">${YOUR}</span>&rdquo;,
      ${pick(T.middle)} ${pick(T.closer)}`;
  };
  roll();
  clearInterval(window.__tplTimer);
  window.__tplTimer = setInterval(roll, 2600);
}


/* ------------------------------------------------ the rotating version field */
function versionChart(P) {
  if (!P.versions) return;
  const rows = P.versions.counts;
  const total = rows.reduce((a, [, n]) => a + n, 0);
  const max = Math.max(...rows.map(r => r[1]));
  $('versions').innerHTML = '<table class="data"><tbody>' + rows.map(([v, n]) =>
    `<tr class="barrow">
      <td style="width:90px"><code>${v}</code></td>
      <td><span class="bar" style="width:${n / max * 100}%;background:var(--decoy)"></span></td>
      <td class="n" style="width:110px">${n} · ${(n / total * 100).toFixed(0)}%</td></tr>`
    ).join('') + '</tbody></table>';
}


/* --------------------------------------------------- the version-probe survey */
/* A version histogram, tallest first. The four templated strings are the four
   tallest bars and sit in a tight band with a visible gap below them; colouring
   them makes the "four spikes over a natural tail" shape read at a glance. */
function versionSurvey(S) {
  const max = S.hist[0][1];
  const bars = S.hist.map(([v, n, ph]) =>
    `<tr class="barrow">
      <td style="width:74px"><code>${v}</code></td>
      <td><span class="bar" style="width:${Math.max(1, n / max * 100)}%;
        background:${ph ? 'var(--series-2)' : 'var(--decoy)'}"></span></td>
      <td class="n" style="width:52px">${n}</td></tr>`).join('');
  $('survey').innerHTML =
    `<div class="scroll" style="max-height:340px;overflow-y:auto">
       <table class="data"><tbody>${bars}</tbody></table></div>`;
  const pctT = (S.templated / S.responded * 100).toFixed(0);
  const pctR = (S.real / S.responded * 100).toFixed(0);
  $('survey-note').innerHTML =
    `Of the ${S.responded.toLocaleString()} that answered, <b>${S.templated.toLocaleString()}</b>
     (${pctT}%) gave one of the four fixed strings, and
     <b>${S.ports_templated.on_11434}</b> of those sat on Ollama's own port 11434; the rest
     answer on database and service-mesh ports. The other
     <b>${S.real.toLocaleString()}</b> (${pctR}%) reported real, varied versions, and
     <b>${(S.ports_real.on_11434 / S.real * 100).toFixed(0)}%</b> of them are on 11434. Two
     independent tells, the version string and the port, point at the same split, and
     two-thirds of what answers here is a real, ordinary Ollama server.`;
}


/* ------------------------------------------------ block arrivals/departures */
/* A model's daily count normally drifts by its own small churn. A jump many
   robust deviations past that is a coordinated block coming online or going
   offline. Everything here is computed from the model series already loaded;
   no extra data. Up is arrival, down is departure, area is servers moved. */
const BLK_ZMIN = 5, BLK_DMIN = 25;

function blockEvents(models) {
  const median = xs => {
    const s = [...xs].sort((a, b) => a - b), n = s.length;
    return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2;
  };
  const out = [];
  for (const name in models.clean) {
    const series = models.clean[name];
    const d = [];
    for (let i = 1; i < series.length; i++) d.push(series[i] - series[i - 1]);
    if (d.filter(x => x).length < 8) continue;
    const med = median(d);
    const scale = Math.max(1.4826 * median(d.map(x => Math.abs(x - med))), 1.5);
    for (let i = 0; i < d.length; i++) {
      const z = (d[i] - med) / scale;
      if (Math.abs(z) >= BLK_ZMIN && Math.abs(d[i]) >= BLK_DMIN)
        out.push({ day: i + 1, name, z, delta: d[i],
                   from: series[i], to: series[i + 1], series });
    }
  }
  return out;
}

function blocksChart(models, vendors) {
  const host = $('blocks');
  const W = host.clientWidth || 1100, H = 380;
  const M = { t: 16, r: 14, b: 26, l: 46 };
  const iw = W - M.l - M.r, ih = H - M.t - M.b;
  const ev = blockEvents(models);
  const day0 = models.day0, ndays = models.ndays;

  // collapse the empty |z| < threshold core: the axis starts at the threshold,
  // both directions, with a thin band in the middle standing for "no event"
  const slog = a => Math.log10(1 + Math.abs(a));
  const base = slog(BLK_ZMIN);
  const smax = (Math.max(...ev.map(e => slog(e.z))) - base) || 1;
  const cy = M.t + ih / 2, gap = 9;
  const X = d => M.l + (d / (ndays - 1)) * iw;
  const Y = z => {
    const s = Math.max(0, slog(z) - base) / smax * (ih / 2 - gap);
    return z >= 0 ? cy - gap - s : cy + gap + s;
  };
  const R = delta => 2.5 + Math.min(13, Math.sqrt(Math.abs(delta)) * 1.05);
  const vc = vendorColors(vendors);
  const colOf = e => vc.colorFor(models.vendor[e.name]);

  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, height: H });
  const grid = el('g', { class: 'grid' }), axis = el('g', { class: 'axis' });
  // the collapsed core: a faint band between the +threshold and -threshold edges
  grid.append(el('rect', { x: M.l, y: cy - gap, width: iw, height: gap * 2,
                           fill: 'var(--surface-2)', opacity: 0.6 }));
  grid.append(el('line', { x1: M.l, x2: W - M.r, y1: cy, y2: cy,
                           stroke: 'var(--border)', 'stroke-dasharray': '2 3' }));
  const zmax = Math.max(...ev.map(e => Math.abs(e.z)));
  for (const z of [5, 10, 25, 100, 300]) {
    if (z > zmax) continue;
    for (const s of [1, -1]) {
      grid.append(el('line', { x1: M.l, x2: W - M.r, y1: Y(z * s), y2: Y(z * s) }));
      axis.append(el('text', { x: M.l - 7, y: Y(z * s) + 4, 'text-anchor': 'end' },
        (s > 0 ? '+' : '−') + z));
    }
  }
  for (const t of monthTicks(day0, ndays, Math.floor(iw / 72)))
    axis.append(el('text', { x: X(t.i), y: H - 6, 'text-anchor': 'middle' },
      t.d.toISOString().slice(0, 7)));
  axis.append(el('text', { x: W - M.r, y: M.t + 12, 'text-anchor': 'end',
    style: 'fill:var(--series-3)' }, 'came online ↑'));
  axis.append(el('text', { x: W - M.r, y: M.t + ih - 4, 'text-anchor': 'end',
    style: 'fill:var(--series-8)' }, 'went offline ↓'));
  svg.append(grid, axis);

  // paint smallest first so big blocks sit on top
  ev.sort((a, b) => Math.abs(a.delta) - Math.abs(b.delta));
  for (const e of ev) {
    const c = el('circle', { cx: X(e.day), cy: Y(e.z), r: R(e.delta),
      fill: colOf(e), 'fill-opacity': 0.62,
      stroke: 'var(--surface-1)', 'stroke-width': 1,
      'data-vendor': models.vendor[e.name] || 'other' });
    c.addEventListener('mousemove', ev2 => showTip(blockTip(e, day0), ev2));
    c.addEventListener('mouseleave', hideTip);
    svg.append(c);
  }
  host.replaceChildren(svg);
  const lg = $('blocks-legend');
  const dim = v => svg.querySelectorAll('circle').forEach(c =>
    c.setAttribute('fill-opacity',
      v === null || c.getAttribute('data-vendor') === v ? 0.62 : 0.05));
  lg.replaceChildren(...vc.top.map(v => {
    const sp = document.createElement('span');
    sp.innerHTML = `<i style="background:${vc.map[v]}"></i>${v}`;
    sp.addEventListener('mouseenter', () => dim(v));
    sp.addEventListener('mouseleave', () => dim(null));
    return sp;
  }));
}

/* tooltip: the event, plus a mini histogram of the model's daily changes with
   this one marked out in the tail */
function blockTip(e, day0) {
  const d = [];
  for (let i = 1; i < e.series.length; i++) {
    const x = e.series[i] - e.series[i - 1];
    if (x) d.push(x);
  }
  const lo = Math.min(...d, e.delta), hi = Math.max(...d, e.delta);
  const BINS = 21, span = (hi - lo) || 1;
  const bin = x => Math.min(BINS - 1, Math.floor((x - lo) / span * BINS));
  const counts = new Array(BINS).fill(0);
  for (const x of d) counts[bin(x)]++;
  const cmax = Math.max(...counts, 1), evBin = bin(e.delta), zeroBin = bin(0);
  const bw = 6, hgt = 34;
  const bars = counts.map((n, i) => {
    const h = n / cmax * hgt;
    const col = i === evBin ? 'var(--series-8)' : i === zeroBin ? 'var(--text-muted)'
      : 'var(--decoy)';
    return `<rect x="${i * bw}" y="${hgt - h}" width="${bw - 1}" height="${h || 1}"
      fill="${col}"/>`;
  }).join('');
  const date = fmtDay(dayDate(day0, e.day));
  return `<div class="d">${date}</div>
    <b>${e.name}</b><br>
    ${e.from.toLocaleString()} → ${e.to.toLocaleString()} servers
    (${e.delta > 0 ? '+' : ''}${e.delta}) at ${e.z > 0 ? '+' : ''}${e.z.toFixed(0)} MAD
    <div style="margin-top:6px;color:var(--text-muted);font-size:11px">its daily changes;
      red is this one</div>
    <svg width="${BINS * bw}" height="${hgt}" style="margin-top:2px">${bars}</svg>`;
}



/* viewBox pan/zoom with +/- buttons, drag, and wheel */
function addZoom(host, svg, W, H) {
  let k = 1, cx = W / 2, cy = H / 2;
  const apply = () => {
    k = Math.max(1, Math.min(14, k));
    const vw = W / k, vh = H / k;
    cx = Math.max(vw / 2, Math.min(W - vw / 2, cx));
    cy = Math.max(vh / 2, Math.min(H - vh / 2, cy));
    svg.setAttribute('viewBox', `${cx - vw / 2} ${cy - vh / 2} ${vw} ${vh}`);
  };
  const zoomAt = (factor, px, py) => {
    // keep the point under the cursor fixed
    const vw = W / k, vh = H / k;
    const wx = cx - vw / 2 + (px / host.clientWidth) * vw;
    const wy = cy - vh / 2 + (py / (host.clientWidth * H / W)) * vh;
    k *= factor;
    const nvw = W / Math.max(1, Math.min(14, k)), nvh = H / Math.max(1, Math.min(14, k));
    cx = wx - (px / host.clientWidth - 0.5) * nvw;
    cy = wy - (py / (host.clientWidth * H / W) - 0.5) * nvh;
    apply();
  };
  const btns = document.createElement('div');
  btns.className = 'zoombtns';
  btns.innerHTML = '<button aria-label="zoom in">+</button><button aria-label="zoom out">\u2212</button>';
  const [zin, zout] = btns.querySelectorAll('button');
  zin.onclick = () => { k *= 1.6; apply(); };
  zout.onclick = () => { k /= 1.6; apply(); };
  host.append(btns);
  svg.style.cursor = 'grab';
  svg.addEventListener('wheel', e => {
    e.preventDefault();
    const rect = host.getBoundingClientRect();
    zoomAt(e.deltaY < 0 ? 1.15 : 1 / 1.15, e.clientX - rect.left, e.clientY - rect.top);
  }, { passive: false });
  let drag = null;
  svg.addEventListener('pointerdown', e => {
    drag = { x: e.clientX, y: e.clientY }; svg.setPointerCapture(e.pointerId);
    svg.style.cursor = 'grabbing';
  });
  svg.addEventListener('pointermove', e => {
    if (!drag) return;
    const s = (W / k) / host.clientWidth;
    cx -= (e.clientX - drag.x) * s; cy -= (e.clientY - drag.y) * s;
    drag = { x: e.clientX, y: e.clientY }; apply();
  });
  const end = () => { drag = null; svg.style.cursor = 'grab'; };
  svg.addEventListener('pointerup', end);
  svg.addEventListener('pointercancel', end);
}


/* ------------------------------------------------ per-model library size */
/* Each dot is a model: x = how many hosts run it (log), y = the average library
   size of those hosts. Popular defaults sit low (minimal boxes); specialised and
   cloud-proxied models sit high (big multi-model rigs). Colour by lab. */
function hoardingChart(H, vendors) {
  const host = $('hoarding');
  const W = host.clientWidth || 1100, ht = 440;
  const M = { t: 26, r: 16, b: 40, l: 46 };
  const iw = W - M.l - M.r, ih = ht - M.t - M.b;
  const vc = vendorColors(vendors);
  const hostsMax = Math.max(...H.models.map(m => m[1]));
  const avgMax = Math.max(...H.models.map(m => m[2])) * 1.08;
  const sized = H.models.filter(m => m[4]);
  const lp = Math.log10(Math.min(...sized.map(m => m[4])));
  const hp = Math.log10(Math.max(...sized.map(m => m[4])));
  const R = pb => pb == null ? 3 : 3.5 + (Math.log10(pb) - lp) / (hp - lp) * 13;
  const fmtP = pb => pb == null ? 'size unknown'
    : '\u2248' + (pb >= 1000 ? (pb / 1000) + 'T' : pb < 1 ? Math.round(pb * 1000) + 'M' : pb + 'B') + ' params';
  const X = n => M.l + Math.log10(n / 10) / Math.log10(hostsMax * 1.3 / 10) * iw;
  const Y = a => M.t + ih - a / avgMax * ih;

  const svg = el('svg', { viewBox: `0 0 ${W} ${ht}`, height: ht });
  const grid = el('g', { class: 'grid' }), axis = el('g', { class: 'axis' });
  for (const a of [0, 10, 20, 30, 40]) {
    if (a > avgMax) continue;
    grid.append(el('line', { x1: M.l, x2: W - M.r, y1: Y(a), y2: Y(a) }));
    axis.append(el('text', { x: M.l - 8, y: Y(a) + 4, 'text-anchor': 'end' }, a));
  }
  for (const n of [12, 20, 50, 100, 200, 500, 1000]) {
    if (n > hostsMax * 1.3) continue;
    grid.append(el('line', { x1: X(n), x2: X(n), y1: M.t, y2: M.t + ih }));
    axis.append(el('text', { x: X(n), y: ht - 6, 'text-anchor': 'middle' }, n));
  }
  // typical-library reference line
  grid.append(el('line', { x1: M.l, x2: W - M.r, y1: Y(H.overall_mean), y2: Y(H.overall_mean),
    stroke: 'var(--text-muted)', 'stroke-dasharray': '3 3' }));
  axis.append(el('text', { x: W - M.r, y: Y(H.overall_mean) - 5, 'text-anchor': 'end',
    style: 'fill:var(--text-muted)' }, `typical (${H.overall_mean})`));
  axis.append(el('text', { x: M.l, y: 13, 'text-anchor': 'start',
    style: 'fill:var(--text-muted)' }, 'avg library size'));
  axis.append(el('text', { x: M.l + iw / 2, y: ht - 4, 'text-anchor': 'middle',
    style: 'fill:var(--text-muted)' }, 'hosts running the model  \u2192'));
  svg.append(grid, axis);

  const UNC = '#f01e5a';   // uncensored / abliterated: a deliberate operator choice
  [...H.models].sort((a, b) => (b[4] || 0) - (a[4] || 0)).forEach(([name, hosts, avg, vend, pb, unc]) => {
    const grp = unc ? 'Uncensored' : vend;
    const c = el('circle', { cx: X(hosts), cy: Y(avg), r: R(pb),
      fill: unc ? UNC : vc.colorFor(vend), 'fill-opacity': 0.55,
      stroke: 'var(--surface-1)', 'stroke-width': 1, 'data-vendor': grp });
    c.addEventListener('mousemove', ev => showTip(
      `<b>${name}</b><br>${hosts.toLocaleString()} hosts · ${fmtP(pb)}<br>` +
      `their libraries average <b>${avg}</b> models<br>` +
      `<span style="color:var(--text-muted)">${unc ? 'uncensored · ' + vend : vend}</span>`, ev));
    c.addEventListener('mouseleave', hideTip);
    svg.append(c);
  });
  host.replaceChildren(svg);
  const lg = $('hoarding-legend');
  const dim = v => svg.querySelectorAll('circle').forEach(c =>
    c.setAttribute('fill-opacity',
      v === null || c.getAttribute('data-vendor') === v ? 0.55 : 0.05));
  const items = [{ name: 'Uncensored', color: UNC }, ...vc.top.map(v => ({ name: v, color: vc.map[v] }))];
  lg.replaceChildren(...items.map(it => {
    const sp = document.createElement('span');
    sp.innerHTML = `<i style="background:${it.color}"></i>${it.name}`;
    sp.addEventListener('mouseenter', () => dim(it.name));
    sp.addEventListener('mouseleave', () => dim(null));
    return sp;
  }));
}

/* ========================= survival + population model ===================== */
/* Retention curve: P(an exposed server is still reachable) t days after it is
   first seen, Kaplan-Meier on the dense-coverage window with a 95% band. */
function retentionCurve(pm) {
  const host = $('retention'); if (!host) return;
  const S = pm.survival;                       // [[t,S,Slo,Shi], ...]
  const W = host.clientWidth || 1100, H = 320;
  const M = { t: 12, r: 16, b: 30, l: 46 };
  const iw = W - M.l - M.r, ih = H - M.t - M.b, TMAX = 180;
  const X = t => M.l + Math.min(t, TMAX) / TMAX * iw;
  const Y = s => M.t + ih - s * ih;
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, height: H });
  const grid = el('g', { class: 'grid' }), axis = el('g', { class: 'axis' });
  for (let p = 0; p <= 1.0001; p += 0.25) {
    grid.append(el('line', { x1: M.l, x2: W - M.r, y1: Y(p), y2: Y(p) }));
    axis.append(el('text', { x: M.l - 8, y: Y(p) + 4, 'text-anchor': 'end' }, (p * 100) + '%'));
  }
  for (const t of [0, 30, 60, 90, 120, 150, 180])
    axis.append(el('text', { x: X(t), y: H - 8, 'text-anchor': 'middle' }, t + 'd'));
  svg.append(grid, axis);
  const step = pts => pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join('');
  const up = S.map(r => [X(r[0]), Y(r[3])]), dn = S.map(r => [X(r[0]), Y(r[2])]).reverse();
  svg.append(el('path', { d: step(up) + step(dn).replace('M', 'L') + 'Z',
    fill: PAL(2), 'fill-opacity': 0.16, stroke: 'none' }));
  svg.append(el('path', { class: 'ser', stroke: PAL(2), d: step(S.map(r => [X(r[0]), Y(r[1])])) }));
  const med = pm.median_lifespan_days;
  if (med != null) {
    svg.append(el('line', { x1: X(med), x2: X(med), y1: Y(0.5), y2: M.t + ih,
      stroke: 'var(--text-muted)', 'stroke-dasharray': '4 4' }));
    svg.append(el('line', { x1: M.l, x2: X(med), y1: Y(0.5), y2: Y(0.5),
      stroke: 'var(--text-muted)', 'stroke-dasharray': '4 4' }));
    svg.append(el('text', { x: X(med) + 6, y: Y(0.5) - 6, style: 'fill:var(--text-secondary);font-size:12px' },
      `median ${med}d`));
  }
  const cur = el('line', { class: 'cursor', y1: M.t, y2: M.t + ih, opacity: 0 });
  const dot = el('circle', { r: 4, fill: PAL(2), stroke: 'var(--surface-1)', 'stroke-width': 2, opacity: 0 });
  svg.append(cur, dot);
  const hit = el('rect', { x: M.l, y: M.t, width: iw, height: ih, fill: 'transparent' });
  svg.append(hit);
  hit.addEventListener('mousemove', ev => {
    const bb = svg.getBoundingClientRect();
    const t = Math.round(((ev.clientX - bb.left) / bb.width * W - M.l) / iw * TMAX);
    let best = S[0]; for (const r of S) if (Math.abs(r[0] - t) < Math.abs(best[0] - t)) best = r;
    cur.setAttribute('x1', X(best[0])); cur.setAttribute('x2', X(best[0])); cur.setAttribute('opacity', 1);
    dot.setAttribute('cx', X(best[0])); dot.setAttribute('cy', Y(best[1])); dot.setAttribute('opacity', 1);
    showTip(`<div class="d">${best[0]} days after first seen</div>` +
      `<b>${(best[1] * 100).toFixed(0)}%</b> still reachable ` +
      `<span style="color:var(--text-muted)">(${(best[2]*100).toFixed(0)}–${(best[3]*100).toFixed(0)}%)</span>`, ev);
  });
  hit.addEventListener('mouseleave', () => { hideTip(); cur.setAttribute('opacity', 0); dot.setAttribute('opacity', 0); });
  host.replaceChildren(svg);
  $('retention-note').innerHTML =
    `Half of all exposed servers vanish within <b>${med} days</b> of first being seen, ` +
    `and roughly <b>15%</b> settle into a persistent core that lasts for months.`;
}

/* Modelled population: a survival estimate of how many servers were alive each
   month, drawn against the raw scanner count that only ever saw a slice. */
function populationModel(pm) {
  const host = $('popmodel'); if (!host) return;
  const mo = pm.months, est = pm.estimate, lo = pm.lo, hi = pm.hi, obs = pm.observed;
  const n = mo.length, W = host.clientWidth || 1100, H = 340;
  const M = { t: 12, r: 16, b: 26, l: 52 };
  const iw = W - M.l - M.r, ih = H - M.t - M.b;
  const max = Math.max(...hi, ...obs, 1);
  const X = i => M.l + (n < 2 ? 0 : i / (n - 1) * iw);
  const Y = v => M.t + ih - v / max * ih;
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, height: H });
  const grid = el('g', { class: 'grid' }), axis = el('g', { class: 'axis' });
  for (const v of niceTicks(max)) {
    grid.append(el('line', { x1: M.l, x2: W - M.r, y1: Y(v), y2: Y(v) }));
    axis.append(el('text', { x: M.l - 8, y: Y(v) + 4, 'text-anchor': 'end' }, fmtInt(v)));
  }
  for (let i = 0; i < n; i += 3)
    axis.append(el('text', { x: X(i), y: H - 8, 'text-anchor': 'middle' }, mo[i]));
  svg.append(grid, axis);
  const step = pts => pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join('');
  const up = hi.map((v, i) => [X(i), Y(v)]), dn = lo.map((v, i) => [X(i), Y(v)]).reverse();
  svg.append(el('path', { d: step(up) + step(dn).replace('M', 'L') + 'Z',
    fill: PAL(1), 'fill-opacity': 0.15, stroke: 'none' }));
  svg.append(el('path', { class: 'ser', stroke: PAL(1), d: step(est.map((v, i) => [X(i), Y(v)])) }));
  svg.append(el('path', { class: 'ser', stroke: PAL(3), 'stroke-dasharray': '5 4',
    d: step(obs.map((v, i) => [X(i), Y(v)])) }));
  const cur = el('line', { class: 'cursor', y1: M.t, y2: M.t + ih, opacity: 0 });
  const dots = el('g'); svg.append(cur, dots);
  const hit = el('rect', { x: M.l, y: M.t, width: iw, height: ih, fill: 'transparent' });
  svg.append(hit);
  hit.addEventListener('mousemove', ev => {
    const bb = svg.getBoundingClientRect();
    const i = Math.round(((ev.clientX - bb.left) / bb.width * W - M.l) / iw * (n - 1));
    if (i < 0 || i >= n) return;
    cur.setAttribute('x1', X(i)); cur.setAttribute('x2', X(i)); cur.setAttribute('opacity', 1);
    dots.replaceChildren(
      el('circle', { cx: X(i), cy: Y(est[i]), r: 4, fill: PAL(1), stroke: 'var(--surface-1)', 'stroke-width': 2 }),
      el('circle', { cx: X(i), cy: Y(obs[i]), r: 4, fill: PAL(3), stroke: 'var(--surface-1)', 'stroke-width': 2 }));
    showTip(`<div class="d">${mo[i]}</div>` +
      `<table><tr><td><i style="background:${PAL(1)}"></i>Modelled alive</td>` +
      `<td class="n">${fmtInt(est[i])}</td></tr>` +
      `<tr><td><i style="background:${PAL(1)};opacity:.4"></i>95% band</td>` +
      `<td class="n">${fmtInt(lo[i])}–${fmtInt(hi[i])}</td></tr>` +
      `<tr><td><i style="background:${PAL(3)}"></i>Scanners saw</td>` +
      `<td class="n">${fmtInt(obs[i])}</td></tr></table>`, ev);
  });
  hit.addEventListener('mouseleave', () => { hideTip(); cur.setAttribute('opacity', 0); dots.replaceChildren(); });
  host.replaceChildren(svg);
  legend($('popmodel-legend'), [
    { name: 'Modelled alive (survival estimate)', color: PAL(1) },
    { name: 'What the scanners actually saw', color: PAL(3) },
  ]);
}

/* ===================== fake-carrying vs clean: model size ================== */
/* Grouped bars: for each per-host median model-size bucket, the share of
   fake-carrying hosts vs clean hosts. Shows the premium-named boxes skew small. */
function fakeSizeChart(fs) {
  const host = $('fakesize'); if (!host || !fs) return;
  const B = fs.buckets, n = B.length;
  const W = host.clientWidth || 1100, H = 300;
  const M = { t: 12, r: 12, b: 42, l: 42 };
  const iw = W - M.l - M.r, ih = H - M.t - M.b;
  const max = Math.max(...fs.fake, ...fs.clean, 1);
  const gw = iw / n, pad = gw * 0.18, bw = (gw - 2 * pad) / 2;
  const Y = v => M.t + ih - v / max * ih;
  const CF = PAL(2), CC = PAL(1);
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, height: H });
  const grid = el('g', { class: 'grid' }), axis = el('g', { class: 'axis' });
  for (const v of niceTicks(max)) {
    grid.append(el('line', { x1: M.l, x2: W - M.r, y1: Y(v), y2: Y(v) }));
    axis.append(el('text', { x: M.l - 8, y: Y(v) + 4, 'text-anchor': 'end' }, v + '%'));
  }
  B.forEach((lab, i) => {
    const gx = M.l + i * gw + pad;
    [['fake', CF, fs.fake[i]], ['clean', CC, fs.clean[i]]].forEach(([k, col, v], j) => {
      const x = gx + j * bw, y = Y(v), h = M.t + ih - y;
      const r = el('rect', { x, y, width: bw - 1, height: Math.max(0, h), rx: 3, fill: col, 'fill-opacity': 0.9 });
      r.addEventListener('mousemove', ev => showTip(
        `<b>${lab} GB</b><br>${k === 'fake' ? 'fake-carrying' : 'clean'} hosts: <b>${v}%</b>`, ev));
      r.addEventListener('mouseleave', hideTip);
      svg.append(r);
    });
    axis.append(el('text', { x: M.l + i * gw + gw / 2, y: H - 24, 'text-anchor': 'middle' }, lab));
  });
  axis.append(el('text', { x: M.l + iw / 2, y: H - 6, 'text-anchor': 'middle',
    style: 'fill:var(--text-muted)' }, 'median model size on the host (GB)'));
  svg.append(grid, axis);
  host.replaceChildren(svg);
  legend($('fakesize-legend'), [
    { name: `Hosts carrying a fake premium model (${fs.fake_n})`, color: CF },
    { name: `Clean hosts (${fs.clean_n})`, color: CC },
  ]);
}

/* ===================== section outline nav + scrollspy ==================== */
function buildNav() {
  const wrap = document.querySelector('.wrap');
  if (!wrap) return;
  const nav = document.createElement('nav');
  nav.className = 'sidenav';
  nav.innerHTML = '<div class="nav-title">Woah\u2026llama</div>';
  const targets = [];
  let i = 0;
  const addLink = (el, text, sub) => {
    if (!el.id) el.id = 'nv-' + (i++);
    const a = document.createElement('a');
    a.href = '#' + el.id; a.textContent = text;
    if (sub) a.className = 'sub';
    nav.append(a);
    targets.push({ el, link: a });
  };
  for (const node of wrap.children) {
    if (node.classList.contains('chapter')) {
      const t = node.querySelector('.chapter-title');
      if (t) { const c = document.createElement('div'); c.className = 'chap'; c.textContent = t.textContent; nav.append(c); }
    } else if (node.tagName === 'SECTION') {
      const h = node.querySelector(':scope > h2');
      if (h) addLink(node, h.textContent, false);
      for (const card of node.querySelectorAll(':scope > .card')) {
        const ch = card.querySelector(':scope > h2');
        if (ch) addLink(card, ch.textContent, true);
      }
    }
  }
  const btn = document.createElement('button');
  btn.className = 'navtoggle'; btn.setAttribute('aria-label', 'Sections');
  btn.innerHTML = '<span></span>';
  const scrim = document.createElement('div');
  scrim.className = 'navscrim';
  const close = () => { nav.classList.remove('open'); scrim.classList.remove('open'); };
  btn.addEventListener('click', () => {
    const open = nav.classList.toggle('open'); scrim.classList.toggle('open', open);
  });
  scrim.addEventListener('click', close);
  nav.addEventListener('click', e => { if (e.target.tagName === 'A') close(); });
  document.body.append(nav, scrim, btn);

  let raf = 0;
  const spy = () => {
    raf = 0;
    const line = 130;
    let active = targets[0];
    for (const t of targets) {
      if (t.el.getBoundingClientRect().top <= line) active = t; else break;
    }
    for (const t of targets) t.link.classList.toggle('active', t === active);
  };
  addEventListener('scroll', () => { if (!raf) raf = requestAnimationFrame(spy); }, { passive: true });
  spy();
}
buildNav();
