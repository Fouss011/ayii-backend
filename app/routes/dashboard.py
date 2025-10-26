# app/routes/dashboard.py
from fastapi import APIRouter, Response
from fastapi.responses import HTMLResponse

router = APIRouter()

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page():
    # HTML full, Tailwind CDN, UI élégante, JS vanilla.
    return """
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AYii — Dashboard CTA</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="icon" href="data:,">
  <style>
    .chip { @apply inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium; }
    .chip-new { @apply bg-amber-100 text-amber-800; }
    .chip-confirmed { @apply bg-blue-100 text-blue-800; }
    .chip-resolved { @apply bg-emerald-100 text-emerald-800; }
    .btn { @apply inline-flex items-center gap-2 rounded-xl border px-3 py-2 text-sm font-medium shadow-sm transition active:scale-[.98]; }
    .btn-primary { @apply bg-indigo-600 text-white border-indigo-600 hover:bg-indigo-700; }
    .btn-ghost { @apply border-slate-200 bg-white text-slate-700 hover:bg-slate-50; }
    .card { @apply bg-white rounded-2xl shadow-sm border border-slate-200; }
    .input { @apply rounded-xl border border-slate-300 px-3 py-2 text-sm w-full; }
    .select { @apply rounded-xl border border-slate-300 px-3 py-2 text-sm bg-white; }
    .badge-kind { @apply text-[11px] font-semibold px-2 py-0.5 rounded-md bg-slate-100 text-slate-700; }
    .thumb { width: 120px; height: 68px; object-fit: cover; border-radius: .75rem; }
    .row { @apply grid grid-cols-[auto,1fr,auto] gap-4 items-center; }
  </style>
</head>
<body class="bg-slate-50 text-slate-900">
  <div class="max-w-7xl mx-auto p-4 md:p-6 space-y-6">
    <!-- Header -->
    <div class="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
      <div class="space-y-1">
        <h1 class="text-2xl md:text-3xl font-bold tracking-tight">Dashboard CTA</h1>
        <p class="text-slate-600 text-sm">Vue des signalements, filtres et actions rapides.</p>
      </div>
      <div class="flex items-center gap-2">
        <button id="btn-refresh" class="btn btn-ghost">Rafraîchir</button>
        <a id="btn-export-reports" href="#" class="btn btn-ghost">Export Reports CSV</a>
        <a id="btn-export-events" href="#" class="btn btn-ghost">Export Événements CSV</a>
        <button id="btn-clear-token" class="btn btn-ghost">Déconnexion</button>
      </div>
    </div>

    <!-- Barre d’auth (token) + filtres -->
    <div class="grid md:grid-cols-5 gap-4">
      <div class="md:col-span-2 card p-4 space-y-3">
        <div class="flex items-center justify-between">
          <h2 class="font-semibold">Accès</h2>
          <span class="text-xs text-slate-500">x-admin-token</span>
        </div>
        <input id="token" type="password" class="input" placeholder="Colle ici ton x-admin-token" />
        <button id="btn-save-token" class="btn btn-primary w-full">Valider le token</button>
        <p id="auth-status" class="text-xs text-slate-500"></p>
      </div>

      <div class="md:col-span-3 card p-4 space-y-3">
        <h2 class="font-semibold">Filtres</h2>
        <div class="grid md:grid-cols-4 gap-3">
          <div>
            <label class="text-xs text-slate-600">Statut</label>
            <select id="f-status" class="select w-full">
              <option value="">(Tous)</option>
              <option value="new">Nouveau</option>
              <option value="confirmed">Confirmé</option>
              <option value="resolved">Traité</option>
            </select>
          </div>
          <div>
            <label class="text-xs text-slate-600">Type</label>
            <select id="f-kind" class="select w-full">
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
            <label class="text-xs text-slate-600">Limite</label>
            <select id="f-limit" class="select w-full">
              <option>50</option>
              <option selected>100</option>
              <option>200</option>
              <option>500</option>
            </select>
          </div>
          <div>
            <label class="text-xs text-slate-600">Recherche</label>
            <input id="f-search" class="input" placeholder="note, id…" />
          </div>
        </div>
      </div>
    </div>

    <!-- Liste -->
    <div class="card">
      <div class="p-4 border-b border-slate-200 flex items-center justify-between">
        <div class="font-semibold">Signalements</div>
        <div id="summary" class="text-sm text-slate-500"></div>
      </div>
      <div id="list" class="divide-y divide-slate-100"></div>
    </div>
  </div>

  <template id="tpl-row">
    <div class="row p-4">
      <img class="thumb bg-slate-100" />
      <div class="space-y-1">
        <div class="flex items-center gap-2">
          <span class="badge-kind"></span>
          <span class="chip"></span>
          <span class="text-xs text-slate-500" data-age></span>
        </div>
        <div class="text-sm">
          <span data-id class="font-mono text-slate-600"></span>
          <span class="text-slate-400">•</span>
          <span data-geo class="text-slate-600"></span>
          <span class="text-slate-400">•</span>
          <span data-when class="text-slate-600"></span>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <button data-act="confirm" class="btn btn-ghost">Confirmer</button>
        <button data-act="resolve" class="btn btn-ghost">Traiter</button>
      </div>
    </div>
  </template>

  <script>
    const $ = (s, el=document) => el.querySelector(s);
    const $$ = (s, el=document) => Array.from(el.querySelectorAll(s));
    const api = {
      incidents: (token, {status, limit}) => {
        const u = new URL('/cta/incidents', window.location.origin);
        if (status) u.searchParams.set('status', status);
        u.searchParams.set('limit', limit || 100);
        return fetch(u, { headers: {'x-admin-token': token} }).then(r => r.json());
      },
      mark: (token, id, newStatus) => {
        return fetch('/cta/mark_status', {
          method: 'POST',
          headers: {'Content-Type':'application/json','x-admin-token': token},
          body: JSON.stringify({ id, status: newStatus })
        }).then(r => r.json());
      }
    };

    const state = {
      items: [],
      token: localStorage.getItem('ayii_admin_token') || '',
      filters: { status: '', kind: '', limit: 100, q: '' }
    };

    // UI init
    $('#token').value = state.token;
    function updateExportLinks(){
      const t = encodeURIComponent(state.token || '');
      $('#btn-export-reports').href = '/admin/export_reports.csv?date_from=2025-01-01&token='+t;
      $('#btn-export-events').href  = '/admin/export_events.csv?table=both&token='+t;
    }
    updateExportLinks();

    $('#btn-save-token').onclick = () => {
      state.token = $('#token').value.trim();
      localStorage.setItem('ayii_admin_token', state.token);
      $('#auth-status').textContent = state.token ? 'Token enregistré' : 'Aucun token';
      updateExportLinks();
      load();
    };
    $('#btn-clear-token').onclick = () => {
      localStorage.removeItem('ayii_admin_token');
      state.token = '';
      $('#token').value = '';
      updateExportLinks();
      render();
    };

    $('#f-status').onchange = e => { state.filters.status = e.target.value; load(); };
    $('#f-kind').onchange   = e => { state.filters.kind   = e.target.value; render(); };
    $('#f-limit').onchange  = e => { state.filters.limit  = +e.target.value; load(); };
    $('#f-search').oninput  = e => { state.filters.q      = e.target.value.toLowerCase(); render(); };
    $('#btn-refresh').onclick = () => load();

    function render(){
      const list = $('#list');
      list.innerHTML = '';
      let data = state.items.slice();

      // filtre kind (client)
      if (state.filters.kind) data = data.filter(x => (x.kind||'').toLowerCase() === state.filters.kind);

      // recherche simple
      const q = (state.filters.q || '').trim();
      if (q) data = data.filter(x =>
        (x.id||'').toLowerCase().includes(q) ||
        (x.note||'').toLowerCase().includes(q)
      );

      // UI
      $('#summary').textContent = `${data.length} élément(s)`;

      const tpl = $('#tpl-row');
      data.forEach(x => {
        const row = tpl.content.cloneNode(true);
        const img = $('.thumb', row);
        img.src = x.photo_url || 'https://via.placeholder.com/120x68?text=—';
        img.alt = x.kind || '—';

        const klabel = {fire:'Feu',accident:'Accident',flood:'Inondation',traffic:'Trafic',power:'Élec.',water:'Eau'}[x.kind] || x.kind;
        $('.badge-kind', row).textContent = klabel;

        const chip = $('.chip', row);
        chip.textContent = (x.status||'new');
        chip.classList.add('chip-' + (x.status||'new'));

        $('[data-id]', row).textContent = (x.id||'').slice(0,8);
        $('[data-geo]', row).textContent = `${(+x.lat).toFixed(5)}, ${(+x.lng).toFixed(5)}`;
        $('[data-when]', row).textContent = (x.created_at||'').replace('T',' ').replace('Z','');
        $('[data-age]', row).textContent = x.age_min != null ? `il y a ${x.age_min} min` : '';

        // actions
        $$('[data-act]', row).forEach(btn => {
          btn.onclick = async () => {
            if (!state.token) { alert('Token requis'); return; }
            const act = btn.getAttribute('data-act');
            const next = act === 'confirm' ? 'confirmed' : 'resolved';
            btn.disabled = true;
            btn.textContent = '…';
            try {
              const res = await api.mark(state.token, x.id, next);
              if (!res.ok) throw new Error(res.detail || 'Erreur');
              // MAJ local
              x.status = next;
              render();
            } catch(e){
              alert('Action impossible: ' + e.message);
            } finally {
              btn.disabled = false;
            }
          };
        });

        list.appendChild(row);
      });
    }

    async function load(){
      if (!state.token) { $('#auth-status').textContent = 'Token manquant'; state.items = []; render(); return; }
      $('#auth-status').textContent = 'Chargement…';
      try {
        const data = await api.incidents(state.token, {status: state.filters.status, limit: state.filters.limit});
        state.items = data.items || [];
        $('#auth-status').textContent = 'OK';
      } catch(e){
        state.items = [];
        $('#auth-status').textContent = 'Erreur d’accès (token ?)';
      }
      render();
    }

    // auto-load
    load();
    // refresh doux toutes les 60s
    setInterval(() => { if (state.token) load(); }, 60000);
  </script>
</body>
</html>
    """
