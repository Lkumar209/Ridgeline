// Ridgeline map page: plain JavaScript, no build step. Reads /api/rankings, /api/sites and
// /api/sites/{id}. Charts are small hand-written SVGs with a pointer readout.
"use strict";

const RANK_GROUPS = 5; // ranks within ~4 places are ties, so color by group, not by exact rank
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const money = (v) => `${v < 0 ? "-" : ""}$${Math.abs(Math.round(v)).toLocaleString()}`;
const words = (camel) => camel.replace(/([a-z])([A-Z])/g, "$1 $2"); // "PrimarySchool" -> "Primary School"
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

const state = { sites: [], byId: new Map(), markers: new Map(), selected: null, request: 0, map: null, halo: null };

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `${url}: HTTP ${response.status}`);
  }
  return response.json();
}

function rankGroup(rank, total) {
  return Math.min(RANK_GROUPS, Math.floor(((rank - 1) * RANK_GROUPS) / total) + 1);
}
const rankColor = (rank) => css(`--rank-${rankGroup(rank, state.sites.length)}`);

function drawLegend(total) {
  const size = Math.ceil(total / RANK_GROUPS);
  const items = [];
  for (let g = 1; g <= RANK_GROUPS; g++) {
    const lo = (g - 1) * size + 1;
    const hi = Math.min(g * size, total);
    items.push(`<span><i style="background:${css(`--rank-${g}`)}"></i>${lo}–${hi}</span>`);
  }
  document.getElementById("legend").innerHTML = `<strong>Robustness rank (P10 NPV)</strong> ${items.join("")}`;
}

// --- map -----------------------------------------------------------------------------------

function markerStyle(site) {
  const on = site.site_id === state.selected;
  return {
    radius: on ? 11 : 8,
    color: on ? css("--text") : css("--card"),
    weight: on ? 3 : 2,
    fillColor: rankColor(site.rank),
    fillOpacity: 1,
  };
}

function drawMap(sites) {
  const map = L.map("map", { scrollWheelZoom: false, zoomSnap: 0.25 });
  state.map = map;
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 14,
    attribution: "&copy; OpenStreetMap contributors",
  }).addTo(map);
  // Draw worst first so the best-ranked pins sit on top.
  for (const site of [...sites].sort((a, b) => b.rank - a.rank)) {
    const marker = L.circleMarker([site.location.lat, site.location.lon], markerStyle(site)).addTo(map);
    marker.bindTooltip(
      `<b>${esc(site.site_id)}</b> · ${esc(words(site.building_type))}<br>` +
        `Rank ${site.rank} of ${sites.length} · ${esc(site.breakeven_label)}`,
      { direction: "top", offset: [0, -8] },
    );
    marker.on("click", () => selectSite(site.site_id));
    state.markers.set(site.site_id, marker);
  }
  map.fitBounds(L.featureGroup([...state.markers.values()]).getBounds().pad(0.12));
}

function restyleMarkers() {
  for (const [id, marker] of state.markers) {
    marker.setStyle(markerStyle(state.byId.get(id)));
    if (id === state.selected) marker.bringToFront();
  }
  // A ring around the selected site, so the map always shows which site the panel describes.
  const chosen = state.markers.get(state.selected);
  if (!chosen || !state.map) return;
  const ring = { radius: 16, color: css("--series-1"), weight: 2, opacity: 0.9, fill: false, interactive: false };
  if (!state.halo) state.halo = L.circleMarker(chosen.getLatLng(), ring).addTo(state.map);
  state.halo.setLatLng(chosen.getLatLng()).setStyle(ring);
}

// --- charts --------------------------------------------------------------------------------

function svgEl(tag, attrs) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

// Round tick values: steps of 1, 2 or 5 x 10^k covering [lo, hi].
function niceTicks(lo, hi, count = 4) {
  const raw = (hi - lo) / count || 1;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((f) => f * mag).find((s) => s >= raw);
  const ticks = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) ticks.push(v);
  return ticks;
}

function scale(domain, range) {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  return (v) => r0 + ((v - d0) / (d1 - d0 || 1)) * (r1 - r0);
}

function chart({ points, series, band, label, xFormat, yFormat, zeroLine, readout }) {
  const W = 460, H = 200, m = { l: 74, r: 10, t: 10, b: 26 };
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": label });
  const xs = points.map((p) => p.x);
  const ys = points.flatMap((p) => [...series.map((s) => p[s.key]), ...(band ? [p[band[0]], p[band[1]]] : [])]);
  if (zeroLine) ys.push(0);
  const ticks = niceTicks(Math.min(...ys), Math.max(...ys));
  const yLo = Math.min(Math.min(...ys), ticks[0]);
  const yHi = Math.max(Math.max(...ys), ticks[ticks.length - 1]);
  const x = scale([Math.min(...xs), Math.max(...xs)], [m.l, W - m.r]);
  const y = scale([yLo, yHi], [H - m.b, m.t]);
  for (const v of ticks) {
    svg.append(svgEl("line", { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), class: "grid" }));
    const t = svgEl("text", { x: m.l - 8, y: y(v) + 4, "text-anchor": "end" });
    t.textContent = yFormat(v);
    svg.append(t);
  }
  const anchors = ["start", "middle", "end"]; // keep edge labels inside the chart
  for (const [k, i] of [0, Math.floor(points.length / 2), points.length - 1].entries()) {
    const t = svgEl("text", { x: x(xs[i]), y: H - 6, "text-anchor": anchors[k] });
    t.textContent = xFormat(points[i]);
    svg.append(t);
  }
  if (band) {
    const top = points.map((p) => `${x(p.x)},${y(p[band[1]])}`);
    const bottom = points.map((p) => `${x(p.x)},${y(p[band[0]])}`).reverse();
    svg.append(svgEl("polygon", { points: [...top, ...bottom].join(" "), fill: css("--band") }));
  }
  if (zeroLine) svg.append(svgEl("line", { x1: m.l, x2: W - m.r, y1: y(0), y2: y(0), class: "zero" }));
  for (const s of series) {
    const d = points.map((p, i) => `${i ? "L" : "M"}${x(p.x)},${y(p[s.key])}`).join("");
    svg.append(svgEl("path", { d, fill: "none", stroke: s.color, "stroke-width": 1.75, "stroke-linejoin": "round" }));
  }
  const cross = svgEl("line", { y1: m.t, y2: H - m.b, class: "cross", visibility: "hidden" });
  svg.append(cross);
  const dots = series.map((s) => {
    const dot = svgEl("circle", { r: 3.5, fill: s.color, class: "dot", visibility: "hidden" });
    svg.append(dot);
    return dot;
  });
  const hit = svgEl("rect", { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: "transparent" });
  // Pointer events, so the readout follows a finger as well as a mouse, from the first touch.
  const track = (event) => {
    const box = svg.getBoundingClientRect();
    const px = ((event.clientX - box.left) / box.width) * W;
    let best = points[0];
    for (const p of points) if (Math.abs(x(p.x) - px) < Math.abs(x(best.x) - px)) best = p;
    cross.setAttribute("x1", x(best.x));
    cross.setAttribute("x2", x(best.x));
    cross.setAttribute("visibility", "visible");
    series.forEach((s, i) => {
      dots[i].setAttribute("cx", x(best.x));
      dots[i].setAttribute("cy", y(best[s.key]));
      dots[i].setAttribute("visibility", "visible");
    });
    readout.textContent = `${xFormat(best)} · ` + series.map((s) => `${s.label} ${yFormat(best[s.key])}`).join(" · ") +
      (band ? ` · range ${yFormat(best[band[0]])} to ${yFormat(best[band[1]])}` : "");
  };
  const clear = () => {
    cross.setAttribute("visibility", "hidden");
    dots.forEach((d) => d.setAttribute("visibility", "hidden"));
    readout.textContent = "";
  };
  hit.addEventListener("pointerdown", track);
  hit.addEventListener("pointermove", track);
  hit.addEventListener("pointerleave", clear);
  svg.append(hit);
  return svg;
}

const keyItem = (cls, color, text) =>
  `<span><i class="${cls}" style="${color ? `background:${color}` : ""}"></i>${text}</span>`;

// --- detail panel --------------------------------------------------------------------------

async function selectSite(siteId) {
  state.selected = siteId;
  restyleMarkers();
  document.getElementById("site-select").value = siteId;
  const body = document.getElementById("detail");
  const ticket = ++state.request; // only the latest request may render (fast clicks race)
  body.classList.add("is-busy");
  let d;
  try {
    d = await getJson(`/api/sites/${encodeURIComponent(siteId)}`);
  } catch (err) {
    if (ticket !== state.request) return;
    body.classList.remove("is-busy");
    body.innerHTML = `<p class="hint"></p>`;
    body.firstChild.textContent = err.message;
    return;
  }
  if (ticket !== state.request) return;
  renderSite(body, d);
  body.classList.remove("is-busy");
  body.classList.add("is-entering");
  requestAnimationFrame(() => requestAnimationFrame(() => body.classList.remove("is-entering")));
}

function renderSite(body, d) {
  const r = d.ranking;
  const total = state.sites.length;
  const stat = (k, v, cls = "") => `<div class="stat ${cls}"><div class="k">${k}</div><div class="v">${v}</div></div>`;
  body.innerHTML = `
    <div class="site-head">
      <div>
        <h2 class="site-title">${esc(d.site.site_id)}</h2>
        <div class="site-type">${esc(words(d.site.building_type))}</div>
      </div>
      <span class="rank-badge"><i style="background:${rankColor(r.rank)}"></i>Rank ${r.rank} of ${total}</span>
    </div>
    <dl class="meta">
      <div><dt>Where</dt><dd>${esc(d.site.county_name)}</dd></div>
      <div><dt>Peak</dt><dd>${Math.round(d.site.peak_kw)} kW</dd></div>
      <div><dt>Tariff</dt><dd>${esc(d.site.tariff)}</dd></div>
    </dl>
    <div class="stats">
      ${stat("Robustness rank", `${r.rank} <small>by median: ${r.rank_by_p50}</small>`)}
      ${stat("Other revenue to break even", `${money(r.required_other_revenue_usd_per_kw_year)}<small>/kW-yr</small>`)}
      ${stat("Breakeven battery cost", esc(r.breakeven_label), "wide")}
      ${stat("15-year NPV", `<div class="npv">
        <div><span class="label">P10 · bad case</span>${money(r.npv_p10)}</div>
        <div><span class="label">P50 · median</span>${money(r.npv_p50)}</div>
        <div><span class="label">P90 · good case</span>${money(r.npv_p90)}</div></div>`, "wide")}
    </div>
    <div class="section">
      <h3>Daily load</h3><div class="sub">2018 · ComStock modeled building</div>
      <div id="load"></div>
      <div class="key">${keyItem("", css("--series-2"), "Daily peak kW")}${keyItem("", css("--series-1"), "Daily mean kW")}</div>
      <div class="readout" id="load-readout"></div>
    </div>
    <div class="section">
      <h3>Cumulative discounted cash flow</h3><div class="sub">P10–P90 range across simulated futures</div>
      <div id="fan"></div>
      <div class="key">${keyItem("", css("--series-1"), "Median")}${keyItem("band", css("--band"), "P10 to P90")}${keyItem("zero", "", "Break-even ($0)")}</div>
      <div class="readout" id="fan-readout"></div>
    </div>`;
  const loadPoints = d.load_curve.map((p, i) => ({ x: i, date: p.date, peak: p.peak_kw, mean: p.mean_kw }));
  const load = body.querySelector("#load");
  if (loadPoints.length) {
    load.append(chart({
      points: loadPoints,
      series: [
        { key: "peak", label: "peak", color: css("--series-2") },
        { key: "mean", label: "mean", color: css("--series-1") },
      ],
      label: "Daily peak and mean kW over 2018",
      xFormat: (p) => p.date, yFormat: (v) => `${Math.round(v)} kW`,
      readout: body.querySelector("#load-readout"),
    }));
  } else {
    load.innerHTML = `<p class="hint">Load data not cached; run ridgeline fetch-data.</p>`;
  }
  const fanPoints = d.fan.map((p) => ({ x: p.year, year: p.year, p10: p.p10, p50: p.p50, p90: p.p90 }));
  body.querySelector("#fan").append(chart({
    points: fanPoints,
    series: [{ key: "p50", label: "median", color: css("--series-1") }],
    band: ["p10", "p90"],
    label: "Cumulative discounted cash flow, median with P10 to P90 range", zeroLine: true,
    xFormat: (p) => `year ${p.year}`, yFormat: money,
    readout: body.querySelector("#fan-readout"),
  }));
}

function fillPicker(sites) {
  const select = document.getElementById("site-select");
  select.innerHTML = sites
    .map((s) => `<option value="${esc(s.site_id)}">${s.rank}. ${esc(s.site_id)} · ${esc(words(s.building_type))}</option>`)
    .join("");
  select.disabled = false;
  select.addEventListener("change", () => selectSite(select.value));
}

// --- page ----------------------------------------------------------------------------------

async function main() {
  try {
    const [rankings, sites] = await Promise.all([getJson("/api/rankings"), getJson("/api/sites")]);
    state.sites = sites;
    for (const s of sites) state.byId.set(s.site_id, s);
    document.getElementById("headline").textContent = rankings.explanations.headline;
    const draws = rankings.run.n_draws ? `${Number(rankings.run.n_draws).toLocaleString()} simulated futures · ` : "";
    document.getElementById("run-meta").textContent = `${sites.length} Massachusetts sites · ${draws}15-year horizon`;
    const labels = { other_revenue: "Other revenue", proxy_tariff: "If the proxy tariff is wrong",
      all_demand: "If demand charges change", tenant_churn: "Tenant churn",
      rank_stability: "How precise ranks are" };
    const list = document.getElementById("explanations");
    for (const [k, label] of Object.entries(labels)) {
      if (!rankings.explanations[k]) continue;
      const li = document.createElement("li");
      li.innerHTML = `<b></b><p></p>`;
      li.querySelector("b").textContent = label;
      li.querySelector("p").textContent = rankings.explanations[k];
      list.append(li);
    }
    drawLegend(sites.length);
    drawMap(sites);
    fillPicker(sites);
    selectSite(sites[0].site_id);
    // Colors come from CSS tokens; redraw when the system switches between light and dark.
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
      drawLegend(sites.length);
      restyleMarkers();
      if (state.selected) selectSite(state.selected);
    });
  } catch (err) {
    document.getElementById("headline").textContent = `Could not load results: ${err.message}`;
  }
}

main();
