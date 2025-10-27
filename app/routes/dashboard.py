# app/routes/dashboard.py
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page():
    return """
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AYii — Dashboard CTA</title>
  <link rel="icon" href="data:,">
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    :root {
      --bg:#f8fafc; --fg:#0f172a; --card:#ffffff; --muted:#64748b; --ring:#e2e8f0;
    }
    .dark :root, .dark {
      --bg:#0b1220; --fg:#e5e7eb; --card:#0f172a; --muted:#94a3b8; --ring:#1f2937;
    }
    html,body { background:var(--bg); color:var(--fg); }
    .card { background:var(--card); border:1px solid var(--ring); border-radius:1rem; box-shadow:0 1px 2px rgba(0,0,0,.04); }
    .btn { display:inline-flex; align-items:center; gap:.5rem; border:1px solid var(--ring); padding:.5rem .75rem; border-radius:.75rem; font-weight:500; }
    .btn-primary { background:#4f46e5; color:#fff; border-color:#4f46e5; }
    .btn-ghost { background:var(--card); color:var(--fg); }
    .chip { font-size:.75rem; padding:.125rem .5rem; border-radius:999px; font-weight:600; }
    .chip-new { background:#fde68a33; color:#b45309; border:1px solid #fde68a; }
    .chip-confirmed { background:#bfdbfe33; color:#1e40af; border:1px solid #bfdbfe; }
    .chip-resolved { background:#a7f3d033; color:#065f46; border:1px solid #a7f3d0; }
    .row { display:grid; grid-template-columns:auto 1fr auto; gap:1rem; align-items:center; }
    .sticky-top { position:sticky; top:0; z-index:20; background:var(--bg); }
    .thumbbox { width:120px; height:68px; position:relative; }
    .thumb    { width:120px; height:68px; object-fit:cover; border-radius:.75rem; display:block; }
    .icon {
      width:120px; height:68px; border-radius:.75rem; display:flex; align-items:center; justify-content:center;
      background:linear-gradient(135deg,#f1f5f9,#e2e8f0); color:#0f172a; font-weight:700; font-family:ui-sans-serif,system-ui;
      position:absolute; inset:0;
    }
  </style>
  <script>
    // Thème sombre auto + bouton
    (function(){
      const key='ayii_theme';
      const saved=localStorage.getItem(key);
      const prefers=window.matchMedia('(prefers-color-scheme: dark)').matches;
      const isDark=saved ? saved==='dark' : prefers;
      if(isDark) document.documentElement.classList.add('dark');
      window.__toggleTheme=function(){
        const now=document.documentElement.classList.toggle('dark');
        localStorage.setItem(key, now?'dark':'light');
      }
    })();

    const $  = (s,el=document)=>el.querySelector(s);
    const $$ = (s,el=document)=>Array.from(el.querySelectorAll(s));

    // Libellés + icônes
    function labelKind(k){
      return k==='traffic'?'embouteillage':
             k==='accident'?'accident':
             k==='fire'?'incendie':
             k==='flood'?'inondation':
             k==='power'?'électricité':
             k==='water'?'eau':(k||'—');
    }
    function iconKind(k){
      return k==='traffic'?'🚗':
             k==='accident'?'💥':
             k==='fire'?'🔥':
             k==='flood'?'🌊':
             k==='power'?'⚡':
             k==='water'?'💧':'•';
    }

    // Gravité (front-only)
    function severityScore(x){
      const kind=String(x.kind||'').toLowerCase();
      const ageMin=Number.isFinite(+x.age_min)?+x.age_min:9999;
      const hasPhoto=!!x.photo_url;
      const reports=Number(x.reports_count||0);
      const attach=Number(x.attachments_count||0);
      const W={fire:30, accident:25, flood:18, power:12, water:10, traffic:8};
      let s=W[kind]||6;
      if(ageMin<=5) s+=25; else if(ageMin<=15) s+=18; else if(ageMin<=60) s+=8; else if(ageMin<=180) s+=3;
      if(hasPhoto) s+=10;
      s+=Math.min(20, reports*4);
      s+=Math.min(12, attach*3);
      return Math.max(0,Math.min(100,Math.round(s)));
    }
    function severityChip(score){
      const lv = score>=60?'high':score>=30?'med':'low';
      const label = lv==='high'?'Élevée':lv==='med'?'Moyenne':'Faible';
      const bg = lv==='high'?'#fee2e2':lv==='med'?'#ffedd5':'#dcfce7';
      const fg = lv==='high'?'#991b1b':lv==='med'?'#9a3412':'#065f46';
      return `<span class="chip" style="background:${bg};color:${fg};border:1px solid rgba(0,0,0,.06)">Gravité ${label} (${score})</span>`;
    }

    const api = {
      incidents:(token,{status,limit})=>{
        const u=new URL('/cta/incidents', location.origin);
        if(status) u.searchParams.set('status',status);
        u.searchParams.set('limit', limit||100);
        return fetch(u, {headers:{'x-admin-token':token}}).then(r=>r.json());
      },
      mark:(token,id,newStatus)=>{
        return fetch('/cta/mark_status',{
          method:'POST',
          headers:{'Content-Type':'application/json','x-admin-token':token},
          body:JSON.stringify({id, status:newStatus})
        }).then(r=>r.json());
      }
    };

    const state = {
      items: [],
      token: localStorage.getItem('ayii_admin_token') || '',
      filters: { status:'', kind:'', limit:100, q:'' }
    };

    function updateExportLinks(){
      const t=encodeURIComponent(state.token||'');
      $('#btn-export-reports').href='/admin/export_reports.csv?date_from=2025-01-01&token='+t;
      $('#btn-export-events').href ='/admin/export_events.csv?table=both&token='+t;
    }

    function buildThumbHTML(item){
      const icon=iconKind(item.kind);
      const url=item.photo_url||'';
      return `
        <div class="thumbbox">
          <div class="icon">${icon}</div>
          ${url ? `<img class="thumb" src="${url}" alt="${item.kind||''}"
                    onload="this.previousElementSibling.style.display='none'"
                    onerror="this.style.display='none'; this.previousElementSibling.style.display='flex'">` : ``}
        </div>`;
    }

    function render(){
      const list=$('#list'); list.innerHTML='';
      let data=state.items.slice();

      if(state.filters.kind) data=data.filter(x => (x.kind||'').toLowerCase()===state.filters.kind);
      const q=(state.filters.q||'').trim().toLowerCase();
      if(q) data=data.filter(x => (x.id||'').toLowerCase().includes(q) || (x.note||'').toLowerCase().includes(q));

      // tri par gravité
      // tri par date : plus récent → plus vieux
      const ts = d => Date.parse(d?.created_at || 0) || 0;
      data.sort((a,b)=> ts(b) - ts(a));


      $('#summary').textContent = data.length+' élément(s)';
      const tpl=$('#tpl-row');

      data.forEach(x=>{
        const frag=tpl.content.cloneNode(true);

        // vignette
        $('.thumbhost', frag).innerHTML = buildThumbHTML(x);

        // libellé + statut + gravité
        $('[data-kind]', frag).textContent = iconKind(x.kind)+' '+labelKind(x.kind);
        const st=(x.status||'new');
        const chip=$('.chip', frag);
        chip.textContent=st; chip.classList.add('chip-'+st);
        chip.insertAdjacentHTML('afterend',' '+severityChip(severityScore(x)));

        // infos
        $('[data-id]',  frag).textContent=(x.id||'').slice(0,8);
        $('[data-geo]', frag).textContent=(+x.lat).toFixed(5)+', '+(+x.lng).toFixed(5);
        $('[data-when]',frag).textContent=(x.created_at||'').replace('T',' ').replace('Z','');
        $('[data-age]', frag).textContent=(x.age_min!=null)?('il y a '+x.age_min+' min'):'';

        // actions
        $$('[data-act]', frag).forEach(btn=>{
          btn.onclick=async ()=>{
            if(!state.token){ alert('Token requis'); return; }
            const act=btn.getAttribute('data-act');
            const next=(act==='confirm')?'confirmed':'resolved';
            const old=btn.textContent; btn.disabled=true; btn.textContent='…';
            try{
              const res=await api.mark(state.token, x.id, next);
              if(!res.ok) throw new Error(res.detail || 'Erreur');
              x.status=next; render();
            }catch(e){ alert('Action impossible: '+(e?.message||e)); }
            finally{ btn.disabled=false; btn.textContent=old; }
          };
        });

        list.appendChild(frag);
      });
    }

    async function load(){
      if(!state.token){ $('#auth-status').textContent='Token manquant'; state.items=[]; render(); return; }
      $('#auth-status').textContent='Chargement…';
      try{
        const data=await api.incidents(state.token, {status:state.filters.status, limit:state.filters.limit});
        state.items=data.items||[];
        $('#auth-status').textContent='OK';
      }catch(e){
        state.items=[]; $('#auth-status').textContent='Erreur d’accès (token ?)';
      }
      render();
    }

    // INIT
    window.addEventListener('DOMContentLoaded', ()=>{
      $('#token').value=state.token; updateExportLinks();
      $('#btn-save-token').onclick=()=>{ state.token=$('#token').value.trim(); localStorage.setItem('ayii_admin_token',state.token); $('#auth-status').textContent=state.token?'Token enregistré':'Aucun token'; updateExportLinks(); load(); };
      $('#btn-clear-token').onclick=()=>{ localStorage.removeItem('ayii_admin_token'); state.token=''; $('#token').value=''; updateExportLinks(); render(); };
      $('#f-status').onchange=e=>{ state.filters.status=e.target.value; load(); };
      $('#f-kind').onchange  =e=>{ state.filters.kind  =e.target.value; render(); };
      $('#f-limit').onchange =e=>{ state.filters.limit =+e.target.value; load(); };
      $('#f-search').oninput =e=>{ state.filters.q     =e.target.value; render(); };
      $('#btn-refresh').onclick=()=>load();
      load();
      setInterval(()=>{ if(state.token) load(); }, 60000);
    });
  </script>
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
              <option value="">(Tous)</option><option value="new">Nouveau</option><option value="confirmed">Confirmé</option><option value="resolved">Traité</option>
            </select>
          </div>
          <div>
            <label class="text-xs" style="color:var(--muted)">Type</label>
            <select id="f-kind" class="w-full rounded-xl border px-3 py-2" style="border-color:var(--ring); background:var(--card); color:var(--fg);">
              <option value="">(Tous)</option><option value="fire">Feu</option><option value="accident">Accident</option><option value="flood">Inondation</option><option value="traffic">Trafic</option><option value="power">Électricité</option><option value="water">Eau</option>
            </select>
          </div>
          <div>
            <label class="text-xs" style="color:var(--muted)">Limite</label>
            <select id="f-limit" class="w-full rounded-xl border px-3 py-2" style="border-color:var(--ring); background:var(--card); color:var(--fg);">
              <option>50</option><option selected>100</option><option>200</option><option>500</option>
            </select>
          </div>
          <div>
            <label class="text-xs" style="color:var(--muted)">Recherche</label>
            <input id="f-search" class="w-full rounded-xl border px-3 py-2" style="border-color:var(--ring); background:var(--card); color:var(--fg);" placeholder="note, id…" />
          </div>
        </div>
      </div>
    </div>

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
      <div class="thumbhost"></div>
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
</body>
</html>
"""
