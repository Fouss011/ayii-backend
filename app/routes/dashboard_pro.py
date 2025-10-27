# app/routes/dashboard_pro.py
from __future__ import annotations
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["DashboardPro"])

@router.get("/dashboard/pro", response_class=HTMLResponse)
async def dashboard_pro():
    return """
<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>AYii – Dashboard CTA (Pro)</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <style>
    .grid-cards { display:grid; grid-template-columns: repeat(12, minmax(0,1fr)); gap: 1rem; }
    .card { background:#fff; border:1px solid #e5e7eb; border-radius: 1rem; padding: 1.25rem; box-shadow: 0 1px 2px rgba(0,0,0,.04); }
    .label { color:#64748b; font-size:.875rem }
    .value { font-weight:600; font-size:1.5rem }
    .btn { padding:.5rem .75rem; border-radius:.75rem; background:#2563eb; color:#fff; font-weight:600 }
    .btn:hover { background:#1d4ed8 }
    .pill { padding:.125rem .5rem; border-radius:999px; background:#f1f5f9; color:#334155; font-size:.75rem; font-weight:600 }
  </style>
</head>
<body class="bg-slate-50 text-gray-900">
  <!-- largeur + grande -->
  <div class="mx-auto p-6 space-y-6" style="max-width: 1400px;">
    <header class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
      <div>
        <h1 class="text-2xl font-bold">AYii – Dashboard CTA (Pro)</h1>
        <p class="text-gray-600">Métriques + Incidents (lecture seule)</p>
      </div>
      <div class="flex items-center gap-2">
        <input id="admintok" type="password" placeholder="x-admin-token" class="border px-3 py-2 rounded-lg w-80" />
        <button id="saveTok" class="btn">Utiliser</button>
        <a href="/dashboard" class="ml-2 text-sm underline">Aller au tableau d’actions</a>
      </div>
    </header>

    <!-- rang 1 -->
    <section class="grid-cards">
      <div class="card col-span-12 lg:col-span-4">
        <div class="flex items-center justify-between mb-4">
          <h2 class="font-semibold">Résumé (24h)</h2>
          <div class="pill" id="serverNow">--</div>
        </div>
        <div class="space-y-3">
          <div class="flex items-center justify-between">
            <span class="label">Reports</span><span class="value" id="sum_total">--</span>
          </div>
          <div class="flex items-center justify-between">
            <span class="label">Nouveaux</span><span class="value" id="sum_new">--</span>
          </div>
          <div class="flex items-center justify-between">
            <span class="label">Confirmés</span><span class="value" id="sum_confirmed">--</span>
          </div>
          <div class="flex items-center justify-between">
            <span class="label">Résolus</span><span class="value" id="sum_resolved">--</span>
          </div>
        </div>
      </div>

      <div class="card col-span-12 lg:col-span-8">
        <div class="flex items-center justify-between mb-4">
          <h2 class="font-semibold">Série 30 jours (reports 'cut')</h2>
          <div class="flex items-center gap-2">
            <select id="kindFilter" class="border px-2 py-1 rounded-lg">
              <option value="">Tous types</option>
              <option>fire</option><option>accident</option><option>traffic</option>
              <option>flood</option><option>power</option><option>water</option>
            </select>
            <button id="reloadTS" class="btn">Rafraîchir</button>
          </div>
        </div>
        <!-- hauteur + grande et fixe -->
        <div class="h-[420px]"><canvas id="tsChart"></canvas></div>
      </div>
    </section>

    <!-- rang 2 -->
    <section class="grid-cards">
      <div class="card col-span-12 lg:col-span-4">
        <div class="flex items-center justify-between mb-4">
          <h2 class="font-semibold">Répartition par type (30j)</h2>
        </div>
        <div class="h-[360px]"><canvas id="pieKind"></canvas></div>
      </div>

      <div class="card col-span-12 lg:col-span-8">
        <div class="flex items-center justify-between mb-4">
          <h2 class="font-semibold">Incidents récents</h2>
          <div class="flex gap-2">
            <select id="status" class="border px-2 py-1 rounded-lg">
              <option>new</option><option>confirmed</option><option>resolved</option>
            </select>
            <button id="reloadInc" class="btn">Actualiser</button>
          </div>
        </div>
        <div id="incTable" class="overflow-auto"></div>
      </div>
    </section>

    <footer class="text-center text-xs text-gray-500 pt-6">
      © AYii – CTA Dashboard
    </footer>
  </div>

<script>
(function(){
  const $ = (sel) => document.querySelector(sel);
  const tokenKey = "ayii_admin_token";
  const api = (path) => path.startsWith("http") ? path : (location.origin + path);

  // token
  const tokInput = $("#admintok");
  tokInput.value = localStorage.getItem(tokenKey) || "";
  $("#saveTok").onclick = () => { localStorage.setItem(tokenKey, tokInput.value.trim()); loadAll(); };

  // headers
  function hdr() {
    const t = (localStorage.getItem(tokenKey) || "").trim();
    return t ? { "x-admin-token": t } : {};
  }
  async function getJSON(url) {
    const res = await fetch(url, { headers: hdr() });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  }

  // Summary
  async function loadSummary() {
    try {
      const j = await getJSON(api("/metrics/summary"));
      $("#sum_total").textContent = j.total?.n_total ?? "--";
      $("#sum_new").textContent = j.total?.n_new ?? "--";
      $("#sum_confirmed").textContent = j.total?.n_confirmed ?? "--";
      $("#sum_resolved").textContent = j.total?.n_resolved ?? "--";
      $("#serverNow").textContent = (j.server_now || "").replace("T"," ").replace("Z","");
    } catch(e){ console.error(e); }
  }

  // Timeseries
  let tsChart;
  async function loadTimeseries() {
    try {
      const k = $("#kindFilter").value.trim();
      const url = k ? api(`/metrics/incidents_by_day?days=30&kind=${encodeURIComponent(k)}`)
                    : api(`/metrics/incidents_by_day?days=30`);
      const j = await getJSON(url);
      // tri chronologique + y à partir de 0
      const series = (j.series || []).slice().sort((a,b)=>a.day.localeCompare(b.day));
      const labels = series.map(r => r.day);
      const data = series.map(r => r.n);
      if (tsChart) tsChart.destroy();
      tsChart = new Chart($("#tsChart").getContext("2d"), {
        type: "line",
        data: { labels, datasets: [{ label: "Reports (cut) / jour", data, tension: 0.25, fill: true }] },
        options: {
          responsive: true, maintainAspectRatio: false,
          scales: { y: { beginAtZero: true, ticks: { precision: 0 } }, x: { ticks: { maxRotation: 0 } } },
          plugins: { legend: { display: true }, tooltip: { mode: "index", intersect: false } }
        }
      });
    } catch(e){ console.error(e); }
  }

  // Pie kind
  let pieKind;
  async function loadPieKind() {
    try {
      const j = await getJSON(api("/metrics/kind_breakdown?days=30"));
      const labels = j.items.map(r => r.kind);
      const data = j.items.map(r => r.n);
      if (pieKind) pieKind.destroy();
      pieKind = new Chart($("#pieKind").getContext("2d"), {
        type: "doughnut",
        data: { labels, datasets: [{ data }] },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { position: "bottom" } }
        }
      });
    } catch(e){ console.error(e); }
  }

  // Incidents table
  function fmtAgeMin(m){ return (m==null)? "-" : `${m} min`; }
  function renderIncidents(items){
    const rows = (items||[]).map(it => `
      <tr class="border-b last:border-none hover:bg-gray-50">
        <td class="p-2 text-xs text-gray-500">${it.id}</td>
        <td class="p-2 font-medium">${it.kind}</td>
        <td class="p-2">${it.signal}</td>
        <td class="p-2">${(it.lat?.toFixed?it.lat.toFixed(5):it.lat)}, ${(it.lng?.toFixed?it.lng.toFixed(5):it.lng)}</td>
        <td class="p-2">${(it.created_at||"").replace("T"," ").replace("Z","")}</td>
        <td class="p-2"><span class="pill">${it.status}</span></td>
        <td class="p-2">${fmtAgeMin(it.age_min)}</td>
        <td class="p-2">${it.photo_url ? `<a href="${it.photo_url}" target="_blank" class="text-blue-600 underline">Photo</a>` : `<span class="text-gray-400">—</span>`}</td>
      </tr>`).join("");
    $("#incTable").innerHTML = `
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-left text-gray-500 border-b">
              <th class="p-2">ID</th><th class="p-2">Type</th><th class="p-2">Signal</th>
              <th class="p-2">Coord.</th><th class="p-2">Créé</th><th class="p-2">Statut</th>
              <th class="p-2">Âge</th><th class="p-2">Pièce jointe</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  }
  async function loadIncidents(){
    try {
      const s = $("#status").value;
      const j = await getJSON(api(`/cta/incidents?status=${encodeURIComponent(s)}&limit=20`));
      renderIncidents(j.items || []);
    } catch(e){ console.error(e); }
  }

  $("#reloadTS").onclick = loadTimeseries;
  $("#reloadInc").onclick = loadIncidents;

  async function loadAll(){
    await Promise.all([loadSummary(), loadTimeseries(), loadPieKind(), loadIncidents()]);
  }
  if ((localStorage.getItem(tokenKey) || "").trim()) loadAll();
})();
</script>
</body>
</html>
    """
