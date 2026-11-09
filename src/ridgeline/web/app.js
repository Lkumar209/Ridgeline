// Ridgeline map page: plain JavaScript, no build step. Reads /api/rankings, /api/sites and
// /api/sites/{id}. Charts are small hand-written SVGs with a hover readout.
"use strict";

const RANK_GROUPS = 5; // ranks within ~4 places are ties, so color by group, not by exact rank
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const money = (v) => `${v < 0 ? "-" : ""}$${Math.abs(Math.round(v)).toLocaleString()}`;

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

function drawLegend(total) {
  const size = Math.ceil(total / RANK_GROUPS);
  const items = [];
  for (let g = 1; g <= RANK_GROUPS; g++) {
    const lo = (g - 1) * size + 1;
    const hi = Math.min(g * size, total);
    items.push(`<span><i style="background:${css(`--rank-${g}`)}"></i>Rank ${lo}–${hi}</span>`);
  }
  document.getElementById("legend").innerHTML =
    `<strong>Robustness rank (P10 NPV)</strong> ${items.join("")}`;
}

function drawMap(sites, onSelect) {
  const map = L.map("map", { scrollWheelZoom: false });
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 14,
    attribution: "&copy; OpenStreetMap contributors",
  }).addTo(map);
  const markers = [];
  // Draw worst first so the best-ranked pins sit on top.
  for (const site of [...sites].sort((a, b) => b.rank - a.rank)) {
    const group = rankGroup(site.rank, sites.length);
    const marker = L.circleMarker([site.location.lat, site.location.lon], {
      radius: 8,
      color: css("--surface"),
      weight: 2,
      fillColor: css(`--rank-${group}`),
      fillOpacity: 1,
    }).addTo(map);
    marker.bindTooltip(
      `<b>${site.site_id}</b> · ${site.building_type}<br>Rank ${site.rank} of ${sites.length}` +
        ` · breakeven: ${site.breakeven_label}`,
    );
    marker.on("click", () => onSelect(site.site_id));
    markers.push(marker);
  }
  map.fitBounds(L.featureGroup(markers).getBounds().pad(0.15));
}

// --- charts ------------------------------------------------------------------------------

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

function chart({ points, series, band, yLabel, xLabel, xFormat, yFormat, zeroLine, readout }) {
  const W = 460, H = 200, m = { l: 64, r: 12, t: 10, b: 28 };
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": yLabel });
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
    const t = svgEl("text", { x: m.l - 6, y: y(v) + 4, "text-anchor": "end" });
    t.textContent = yFormat(v);
    svg.append(t);
  }
  const anchors = ["start", "middle", "end"]; // keep edge labels inside the chart
  for (const [k, i] of [0, Math.floor(points.length / 2), points.length - 1].entries()) {
    const t = svgEl("text", { x: x(xs[i]), y: H - 8, "text-anchor": anchors[k] });
    t.textContent = xFormat(points[i]);
    svg.append(t);
  }
  if (zeroLine) svg.append(svgEl("line", { x1: m.l, x2: W - m.r, y1: y(0), y2: y(0), class: "zero" }));
  if (band) {
    const top = points.map((p) => `${x(p.x)},${y(p[band[1]])}`);
    const bottom = points.map((p) => `${x(p.x)},${y(p[band[0]])}`).reverse();
    svg.append(svgEl("polygon", { points: [...top, ...bottom].join(" "), fill: css("--band") }));
  }
  for (const s of series) {
    const d = points.map((p, i) => `${i ? "L" : "M"}${x(p.x)},${y(p[s.key])}`).join("");
    svg.append(svgEl("path", { d, fill: "none", stroke: s.color, "stroke-width": 2 }));
  }
  const cross = svgEl("line", { y1: m.t, y2: H - m.b, stroke: css("--muted"), visibility: "hidden" });
  svg.append(cross);
  const hit = svgEl("rect", { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: "transparent" });
  hit.addEventListener("mousemove", (event) => {
    const box = svg.getBoundingClientRect();
    const px = ((event.clientX - box.left) / box.width) * W;
    let best = points[0];
    for (const p of points) if (Math.abs(x(p.x) - px) < Math.abs(x(best.x) - px)) best = p;
    cross.setAttribute("x1", x(best.x));
    cross.setAttribute("x2", x(best.x));
    cross.setAttribute("visibility", "visible");
    readout.textContent = `${xFormat(best)}: ` + series.map((s) => `${s.label} ${yFormat(best[s.key])}`).join(" · ") +
      (band ? ` · range ${yFormat(best[band[0]])} to ${yFormat(best[band[1]])}` : "");
  });
  hit.addEventListener("mouseleave", () => { cross.setAttribute("visibility", "hidden"); readout.textContent = ""; });
  svg.append(hit);
  const caption = document.createElement("div");
  caption.className = "note";
  caption.textContent = xLabel;
  return [svg, caption];
}

// --- detail panel ------------------------------------------------------------------------

async function showSite(siteId) {
  const panel = document.getElementById("detail");
  panel.innerHTML = `<p class="hint">Loading ${siteId}&hellip;</p>`;
  let d;
  try {
    d = await getJson(`/api/sites/${encodeURIComponent(siteId)}`);
  } catch (err) {
    panel.innerHTML = `<p class="hint">${err.message}</p>`;
    return;
  }
  const r = d.ranking;
  const stat = (k, v) => `<div class="stat"><div class="k">${k}</div><div class="v">${v}</div></div>`;
  panel.innerHTML = `
    <h2>${d.site.site_id} · ${d.site.building_type}</h2>
    <div class="note">${d.site.county_name} · peak ${Math.round(d.site.peak_kw)} kW ·
      tariff: ${d.site.tariff}</div>
    <div class="stats">
      ${stat("Robustness rank", `${r.rank} (by median: ${r.rank_by_p50})`)}
      ${stat("Breakeven battery cost", r.breakeven_label)}
      ${stat("NPV P10 / P50 / P90", `${money(r.npv_p10)} / ${money(r.npv_p50)} / ${money(r.npv_p90)}`)}
      ${stat("Other revenue to break even", `${money(r.required_other_revenue_usd_per_kw_year)}/kW-yr`)}
    </div>
    <h3>Daily load, 2018 (ComStock modeled building)</h3><div id="load"></div><div class="readout" id="load-readout"></div>
    <h3>Cumulative discounted cash flow, P10–P90 range</h3><div id="fan"></div><div class="readout" id="fan-readout"></div>`;
  const loadPoints = d.load_curve.map((p, i) => ({ x: i, date: p.date, peak: p.peak_kw, mean: p.mean_kw }));
  if (loadPoints.length) {
    document.getElementById("load").append(...chart({
      points: loadPoints,
      series: [
        { key: "peak", label: "peak", color: css("--series-2") },
        { key: "mean", label: "mean", color: css("--series-1") },
      ],
      yLabel: "Daily peak and mean kW", xLabel: "Orange: daily peak kW. Blue: daily mean kW.",
      xFormat: (p) => p.date, yFormat: (v) => `${Math.round(v)} kW`,
      readout: document.getElementById("load-readout"),
    }));
  } else {
    document.getElementById("load").innerHTML = `<p class="hint">Load data not cached; run ridgeline fetch-data.</p>`;
  }
  const fanPoints = d.fan.map((p) => ({ x: p.year, year: p.year, p10: p.p10, p50: p.p50, p90: p.p90 }));
  document.getElementById("fan").append(...chart({
    points: fanPoints,
    series: [{ key: "p50", label: "median", color: css("--series-1") }],
    band: ["p10", "p90"],
    yLabel: "Cumulative discounted cash flow", zeroLine: true,
    xLabel: "Line: median. Band: P10 to P90 across simulated futures. Black line: break-even.",
    xFormat: (p) => `year ${p.year}`, yFormat: money,
    readout: document.getElementById("fan-readout"),
  }));
}

async function main() {
  try {
    const [rankings, sites] = await Promise.all([getJson("/api/rankings"), getJson("/api/sites")]);
    document.getElementById("headline").textContent = rankings.explanations.headline;
    const labels = { other_revenue: "Other revenue", proxy_tariff: "If the proxy tariff is wrong",
      all_demand: "If demand charges change", tenant_churn: "Tenant churn",
      rank_stability: "How precise ranks are" };
    document.getElementById("explanations").innerHTML = Object.entries(labels)
      .filter(([k]) => rankings.explanations[k])
      .map(([k, label]) => `<li><b>${label}.</b> ${rankings.explanations[k]}</li>`).join("");
    drawLegend(sites.length);
    drawMap(sites, showSite);
    showSite(sites[0].site_id);
  } catch (err) {
    document.getElementById("headline").textContent = `Could not load results: ${err.message}`;
  }
}

main();
