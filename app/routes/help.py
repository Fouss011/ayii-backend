# app/routes/help.py
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["Help"])

@router.get("/aide", response_class=HTMLResponse)
async def aide():
    return """
<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8" />
  <title>AYii – Aide au signalement</title>
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-50 text-slate-900">
  <div class="max-w-3xl mx-auto p-6 space-y-4">
    <header class="mb-4">
      <h1 class="text-2xl font-bold">Comment bien signaler un incident sur AYii ?</h1>
      <p class="text-sm text-slate-600">
        Quelques conseils pour que vos signalements soient utiles et traités rapidement.
      </p>
    </header>

    <section class="space-y-3 bg-white rounded-xl border border-slate-200 p-4 shadow-sm">
      <h2 class="font-semibold">1. Choisissez le bon type d’incident</h2>
      <ul class="list-disc list-inside text-sm space-y-1">
        <li>🚗 <b>traffic</b> : embouteillage important</li>
        <li>💥 <b>accident</b> : collision, choc véhicule / piéton...</li>
        <li>🔥 <b>fire</b> : départ de feu, incendie</li>
        <li>🌊 <b>flood</b> : inondation</li>
        <li>⚡ <b>power</b> : coupure d’électricité</li>
        <li>💧 <b>water</b> : coupure d’eau</li>
      </ul>
    </section>

    <section class="space-y-3 bg-white rounded-xl border border-slate-200 p-4 shadow-sm">
      <h2 class="font-semibold">2. Placez le point au bon endroit sur la carte</h2>
      <p class="text-sm">
        Zoomez si nécessaire et cliquez au plus près de l’endroit réel de l’incident. Une bonne
        position géographique aide les équipes à intervenir plus vite.
      </p>
    </section>

    <section class="space-y-3 bg-white rounded-xl border border-slate-200 p-4 shadow-sm">
      <h2 class="font-semibold">3. Ajoutez une photo ou une vidéo (fortement recommandé)</h2>
      <p class="text-sm">
        Une image ou une courte vidéo rend la situation beaucoup plus claire.
      </p>
      <ul class="list-disc list-inside text-sm space-y-1">
        <li>📸 Une photo nette suffit souvent.</li>
        <li>📹 Privilégiez des vidéos très courtes : <b>5 secondes maximum</b>.</li>
        <li>Des vidéos trop longues peuvent être rejetées ou trop lentes à envoyer.</li>
      </ul>
    </section>

    <section class="space-y-3 bg-white rounded-xl border border-slate-200 p-4 shadow-sm">
      <h2 class="font-semibold">4. Laissez un numéro de téléphone joignable</h2>
      <p class="text-sm">
        Le numéro de téléphone est <b>optionnel</b>, mais très important : il permet aux secours
        ou aux services techniques de vous rappeler si besoin.
      </p>
      <p class="text-sm text-red-600 font-semibold">
        Les signalements avec média (photo/vidéo) <u>et</u> numéro de téléphone sont traités en
        priorité.
      </p>
    </section>

    <section class="space-y-3 bg-white rounded-xl border border-slate-200 p-4 shadow-sm">
      <h2 class="font-semibold">5. Vérifiez et confirmez</h2>
      <p class="text-sm">
        Avant de valider, vérifiez :
      </p>
      <ul class="list-disc list-inside text-sm space-y-1">
        <li>Le type d’incident</li>
        <li>La position sur la carte</li>
        <li>La présence d’une photo ou vidéo si possible</li>
        <li>Votre numéro de téléphone si vous acceptez d’être rappelé</li>
      </ul>
    </section>

    <section class="bg-amber-50 border border-amber-200 text-amber-900 text-sm rounded-xl p-4 shadow-sm">
      <p class="font-semibold">
        ⚠️ Signalements sans média et sans téléphone
      </p>
      <p>
        Les signalements sans photo/vidéo ni téléphone sont parfois difficiles à exploiter.
        Quand c’est possible, merci de privilégier les preuves visuelles et de laisser un numéro.
      </p>
    </section>

    <footer class="pt-4 text-xs text-center text-slate-500">
      © AYii – Plateforme de signalement citoyen
    </footer>
  </div>
</body>
</html>
"""
