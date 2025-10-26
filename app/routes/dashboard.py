# app/routes/dashboard.py
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


# ---------- Helpers HTML commun ----------
def _base_head(title: str) -> str:
    return f"""
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{title}</title>
<link rel="icon" href="data:,">
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --bg:  #f8fafc;   /* slate-50 */
    --fg:  #0f172a;   /* slate-900 */
    --card:#ffffff;   /* white */
    --muted:#64748b;  /* slate-500 */
    --ring:#e2e8f0;   /* slate-200 */
  }}
  .dark :root, .dark {{
    --bg:  #0b1220;   /* très sombre */
    --fg:  #e5e7eb;   /* gris clair */
    --card:#0f172a;   /* slate-900 */
    --muted:#94a3b8;  /* slate-400 */
    --ring:#1f2937;   /* gris foncé */
  }}
  html, body {{ background: var(--bg); color: var(--fg); }}
  .card {{ background: var(--card); border: 1px solid var(--ring); border-radius: 1rem; box-shadow: 0 1px 2px rgba(0,0,0,.04); }}
  .btn {{ display:inline-flex; align-items:center; gap:.5rem; border:1px solid var(--ring); padding:.5rem .75rem; border-radius:.75rem; font-weight:500; }}
  .btn-primary {{ background:#4f46e5; color:white; border-color:#4f46e5; }}
  .btn-ghost {{ background:var(--card); color:var(--fg); }}
  .chip {{ font-size:.75rem; padding:.125rem .5rem; border-radius:999px; font-weight:600; }}
  .chip-new {{ background:#fde68a33; color:#b45309; border:1px solid #fde68a; }}
  .chip-confirmed {{ background:#bfdbfe33; color:#1e40af; border:1px solid #bfdbfe; }}
  .chip-resolved {{ background:#a7f3d033; color:#065f46; border:1px solid #a7f3d0; }}
  .thumb {{ width: 120px; height: 68px; object-fit: cover; border-radius: .75rem; background:#e2e8f0; }}
  .row {{ display:grid; grid-template-columns: auto 1fr auto; gap:1rem; align-items:center; }}
  .sticky-top {{ position: sticky; top: 0; z-index: 20; background: var(--bg); }}
  /* icônes inline (fallback) */
  .icon {{
    width:120px; height:68px; border-radius:.75rem; display:flex; align-items:center; justify-content:center;
    background:linear-gradient(135deg,#f1f5f9,#e2e8f0);
    color:#0f172a; font-weight:700; font-family:ui-sans-serif,system-ui; letter-spacing:.5px;
  }}
</style>
<script>
  // dark mode auto + toggle
  (function(){{
    const key = 'ayii_theme';
    const saved = localStorage.getItem(key);
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const isDark = saved ? saved === 'dark' : prefersDark;
    if (isDark) document.documentElement.classList.add('dark');
    window.__toggleTheme = function(){{
      const nowDark = document.documentElement.classList.toggle('dark');
      localStorage.setItem(key, nowDark ? 'dark':'light');
    }}
  }})();
  const $=(s,el=document)=>el.querySelector(s);
</script>
"""


# ---------- Page 1 : Tableau d’actions ----------
@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    return f"""
<!DOCTYPE html>
<html lang="fr">
<head>
  {_base_head("AYii — Dashboard CTA")}
</head>
<body>
  <div class="sticky-top border-b" style="border-color:var(--ring);">
    <div class="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
      <h1 class="text-xl md:text-2xl font-bold">Dashboard CTA</h1>
      <div class="flex items-center gap-2">
        <button id="btn-refresh" class="btn btn-ghost">Rafraîchir</button>
        <a id="btn-export-reports" href="#" class="btn btn-ghost">Export Reports CSV</a>
        <a id="btn-export-events" href="#" class="btn btn-ghost">Export Événements CSV</a>
        <button class="btn btn-ghost" onclick="__toggleTheme()">Thème</button>
        <button id="btn-clear-token" class="btn btn-ghost">Déconnexion</button>
      </div>
    </div>
  </div>

  <div class="max-w-7xl mx-auto px-4 py-6 space-y-6">
    <!-- Accès + filtres -->
    <div class="grid md:grid-cols-5 gap-4">
      <div class="md:col-span-2 card p-4 space-y-3">
        <div class="flex items-center justify-between">
          <h2 class="font-semibold">Accès</h2>
          <span class="text-xs" style="color:var(--muted)">x-admin-token</span>
        </div>
        <input id="token" type="password" class="w-full rounded-xl border px-3 py-2" style="border-color:var(--ring); background:var(--card); color:var(--fg);" placeholder="Colle ici ton x-admin-token" />
        <button id="btn-save-token" class="btn btn-primary w-full">Valider le token</button>
        <p id="auth-status" class="text-xs" style="color:var(--muted)"></p>
      </div>

      <div class="md:col-span-3 card p-4 space-y-3">
        <h2 class="font-semibold">Filtres</h2>
        <div class="grid md:grid-cols-4 gap-3">
          <div>
            <label class="text-xs" style="color:var(--muted)">Statut</label>
            <select id="f-status" class="w-full rounded-xl border px-3 py-2" style="border-color:var(--ring); background:var(--card); color:var(--fg);">
              <option value="">(Tous)</option>
              <option value="new">Nouveau</option>
              <option value="confirmed">Confirmé</option>
              <option value="resolved">Traité</option>
            </select>
          </div>
          <div>
            <label class="text-xs" style="color:var(--muted)">Type</label>
            <select id="f-kind" class="w-full rounded-xl border px-3 py-2" style="border-color:var(--ring); background:var(--card); color:var(--fg);">
              <option value="">(Tous)</option>
              <option value="fire">Feu</option>
              <option value="accident">Accident</option>
              <option value="flood">Inondation</option>
              <option value="traffic">Trafic</option>
              <option value="power">Électricité</option>
              <option value="water">Eau</option>
            </select>
          </div>
          <div>
            <label class="text-xs" style="color:var(--muted)">Limite</label>
            <select id="f-limit" class="w-full rounded-xl border px-3 py-2" style="border-color:var(--ring); background:var(--card); color:var(--fg);">
              <option>50</option>
              <option selected>100</option>
              <option>200</option>
              <option>500</option>
            </select>
          </div>
          <div>
            <label class="text-xs" style="color:var(--muted)">Recherche</label>
            <input id="f-search" class="w-full rounded-xl border px-3 py-2" style="border-color:var(--ring); background:var(--card); color:var(--fg);" placeholder="note, id…" />
          </div>
        </div>
      </div>
    </div>

    <!-- Liste -->
    <div class="card">
      <div class="p-4 flex items-center justify-between border-b" style="border-color:var(--ring);">
        <div class="font-semibold">Signalements</div>
        <div id="summary" class="text-sm" style="color:var(--muted)"></div>
      </div>
      <div id="list"></div>
    </div>
  </div>

  <template id="tpl-row">
    <div class="row p-4">
      <div class="thumb"></div>
      <div class="space-y-1">
        <div class="flex items-center gap-2">
          <span data-kind class="text-[11px] font-semibold px-2 py-0.5 rounded-md" style="background:#e2e8f0; color:#334155;"></span>
          <span class="chip"></span>
          <span class="text-xs" data-age style="color:var(--muted)"></span>
        </div>
        <div class="text-sm">
          <span data-id class="font-mono" style="color:#475569"></span>
          <span style="color:#94a3b8">•</span>
          <span data-geo style="color:#475569"></span>
          <span style="color:#94a3b8">•</span>
          <span data-when style="color:#475569"></span>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <button data-act="confirm" class="btn btn-ghost">Confirmer</button>
        <button data-act="resolve" class="btn btn-ghost">Traiter</button>
      </div>
    </div>
  </template>

  <script>
    const $$=(s,el=document)=>Array.from(el.querySelectorAll(s));
    const api = {{
      incidents: (token, {{status, limit}}) => {{
        const u = new URL('/cta/incidents', window.location.origin);
        if (status) u.searchParams.set('status', status);
        u.searchParams.set('limit', limit || 100);
        return fetch(u, {{ headers: {{'x-admin-token': token}} }}).then(r => r.json());
      }},
      mark: (token, id, newStatus) => {{
        return fetch('/cta/mark_status', {{
          method: 'POST',
          headers: {{'Content-Type':'application/json','x-admin-token': token}},
          body: JSON.stringify({{ id, status: newStatus }})
        }}).then(r => r.json());
      }}
    }};

    const ICONS = {{
      fire:'🔥', accident:'🚗', flood:'🌊', traffic:'🚧', power:'⚡', water:'💧'
    }};

    const state = {{
      items: [],
      token: localStorage.getItem('ayii_admin_token') || '',
      filters: {{ status: '', kind: '', limit: 100, q: '' }}
    }};

    $('#token').value = state.token;
    function updateExportLinks(){{
      const t = encodeURIComponent(state.token || '');
      $('#btn-export-reports').href = '/admin/export_reports.csv?date_from=2025-01-01&token='+t;
      $('#btn-export-events').href  = '/admin/export_events.csv?table=both&token='+t;
    }}
    updateExportLinks();

    $('#btn-save-token').onclick = () => {{
      state.token = $('#token').value.trim();
      localStorage.setItem('ayii_admin_token', state.token);
      $('#auth-status').textContent = state.token ? 'Token enregistré' : 'Aucun token';
      updateExportLinks();
      load();
    }};
    $('#btn-clear-token').onclick = () => {{
      localStorage.removeItem('ayii_admin_token');
      state.token = '';
      $('#token').value = '';
      updateExportLinks();
      render();
    }};

    $('#f-status').onchange = e => {{ state.filters.status = e.target.value; load(); }};
    $('#f-kind').onchange   = e => {{ state.filters.kind   = e.target.value; render(); }};
    $('#f-limit').onchange  = e => {{ state.filters.limit  = +e.target.value; load(); }};
    $('#f-search').oninput  = e => {{ state.filters.q      = e.target.value.toLowerCase(); render(); }};
    $('#btn-refresh').onclick = () => load();

    function thumbHTML(x){{
      const url = x.photo_url;
      if (url) return `<img class="thumb" src="${{url}}" alt="${{x.kind||''}}" onerror="this.replaceWith(document.createRange().createContextualFragment('<div class=icon>${{ICONS[x.kind]||'—'}}</div>'));" />`;
      return `<div class="icon">${{ICONS[x.kind]||'—'}}</div>`;
    }}

    function render(){{
      const list = $('#list');
      list.innerHTML = '';
      let data = state.items.slice();
      if (state.filters.kind) data = data.filter(x => (x.kind||'').toLowerCase() === state.filters.kind);
      const q = (state.filters.q || '').trim();
      if (q) data = data.filter(x => (x.id||'').toLowerCase().includes(q) || (x.note||'').toLowerCase().includes(q));
      $('#summary').textContent = `${{data.length}} élément(s)`;
      const tpl = $('#tpl-row');

      data.forEach(x => {{
        const frag = tpl.content.cloneNode(true);
        // vignette
        $('.thumb', frag).outerHTML = thumbHTML(x);

        $('[data-kind]', frag).textContent = ({{fire:'Feu',accident:'Accident',flood:'Inondation',traffic:'Trafic',power:'Élec.',water:'Eau'}}[x.kind] || x.kind);
        const chip = $('.chip', frag);
        const st = (x.status||'new');
        chip.textContent = st;
        chip.classList.add('chip-'+st);

        $('[data-id]', frag).textContent = (x.id||'').slice(0,8);
        $('[data-geo]', frag).textContent = `${{(+x.lat).toFixed(5)}}, ${{(+x.lng).toFixed(5)}}`;
        $('[data-when]', frag).textContent = (x.created_at||'').replace('T',' ').replace('Z','');
        $('[data-age]', frag).textContent = x.age_min != null ? `il y a ${{x.age_min}} min` : '';

        $$('[data-act]', frag).forEach(btn => {{
          btn.onclick = async () => {{
            if (!state.token) {{ alert('Token requis'); return; }}
            const act = btn.getAttribute('data-act');
            const next = act === 'confirm' ? 'confirmed' : 'resolved';
            btn.disabled = true; btn.textContent = '…';
            try {{
              const res = await api.mark(state.token, x.id, next);
              if (!res.ok) throw new Error(res.detail || 'Erreur');
              x.status = next; render();
            }} catch(e) {{
              alert('Action impossible: '+e.message);
            }} finally {{ btn.disabled = false; }}
          }};
        }});

        list.appendChild(frag);
      }});
    }}

    async function load(){{
      if (!state.token) {{ $('#auth-status').textContent = 'Token manquant'; state.items = []; render(); return; }}
      $('#auth-status').textContent = 'Chargement…';
      try {{
        const data = await api.incidents(state.token, {{status: state.filters.status, limit: state.filters.limit}});
        state.items = data.items || [];
        $('#auth-status').textContent = 'OK';
      }} catch(e){{
        state.items = [];
        $('#auth-status').textContent = 'Erreur d’accès (token ?)';
      }}
      render();
    }}

    load();
    setInterval(() => {{ if (state.token) load(); }}, 60000);
  </script>
</body>
</html>
"""