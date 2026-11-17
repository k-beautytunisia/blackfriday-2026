#!/usr/bin/env python3
"""Build a standalone, non-transactional Black Friday preview from a public catalog snapshot."""
from pathlib import Path
from datetime import datetime
import html
import json
import re

ROOT = Path(__file__).parent
TEMPLATE = ROOT / "template.html"
SNAPSHOT = ROOT / "catalogue.json"
SITE = ROOT / "site"
ASSETS = SITE / "assets"
PAGE_MAX_AGE_MINUTES = 30

ROUTINE_SPECS = [
    {"title": "Peaux mixtes / normales", "for": "Mousse nettoyante · ampoule · crème", "ids": [2, 49, 53]},
    {"title": "Peaux sensibles / grasses", "for": "Huile nettoyante · mousse · crème hydratante", "ids": [3, 2, 236]},
    {"title": "Peaux sensibles acnéiques", "for": "Toner Heartleaf · Glow Serum · crème Centella", "ids": [4, 251, 53]},
    {"title": "Tous types de peau", "for": "Sérum Niacinamide · Capsule Cream · Matte Sun Stick", "ids": [1, 235, 9]},
    {"title": "Peaux sensibles normales", "for": "Nettoyant Dokdo · toner Centella · crème PDRN", "ids": [212, 51, 236]},
]
BEST_PRIORITY = [1, 49, 7, 19, 22, 40, 233, 237, 41, 250, 5, 4, 51, 52, 236, 235, 251, 221, 13, 15]
BEST_FALLBACK = [1, 49, 7, 19, 22, 40, 233, 237, 250, 4, 5, 166]
UPSELL_PRIORITY = [15, 13, 263, 209, 211, 63, 218, 248, 60, 207]
EXAMPLE_PRIORITY = [1, 7, 22]


def clean_name(name: str, brand: str) -> str:
    value = name
    for prefix in (brand + " – ", brand + " - ", brand.upper() + " ", brand + " "):
        if value.lower().startswith(prefix.lower()):
            value = value[len(prefix):]
            break
    value = re.sub(r"\s+—\s+\d+[.,]?\d*\s*(ml|g)\s*$", "", value, flags=re.I)
    return value.strip(" –-")


def ordered_ids(ids, available):
    return [int(pid) for pid in ids if int(pid) in available]


def main() -> None:
    snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    collected_at = str(snap.get("collectedAt", ""))
    parsed = datetime.fromisoformat(collected_at)
    if parsed.tzinfo is None:
        raise SystemExit("STOP: snapshot timestamp has no timezone.")
    products = []
    for source in snap.get("products", []):
        if not source.get("image") or not source.get("url") or int(source.get("availableQuantity", 0)) <= 0:
            continue
        products.append({
            "id": int(source["id"]),
            "name": clean_name(str(source.get("name") or ""), str(source.get("brand") or "")),
            "brand": str(source.get("brand") or ""),
            "volume": str(source.get("volume") or ""),
            "cat": str(source.get("categorySlug") or "autres"),
            "catName": str(source.get("category") or "Autres"),
            "price": int(source["priceMillimes"]),
            "maxQty": int(source["availableQuantity"]),
            "low": int(source["availableQuantity"]) <= 3,
            "best": bool(source.get("bestSeller")),
            "rank": 9999,
            "url": str(source["url"]),
            "image": str(source["image"]),
        })
    if len(products) != int(snap.get("availableCount", -1)) or not products:
        raise SystemExit("STOP: snapshot stock count is inconsistent; no build generated.")

    available = {p["id"] for p in products}
    priority = {pid: i for i, pid in enumerate(BEST_PRIORITY)}
    products.sort(key=lambda p: (priority.get(p["id"], 1000), -p["best"], -min(p["maxQty"], 10), -p["price"]))
    for i, product in enumerate(products):
        product["rank"] = i
    by_id = {p["id"]: p for p in products}

    routines = []
    for spec in ROUTINE_SPECS:
        if all(pid in available for pid in spec["ids"]):
            routines.append(spec)
    best_ids = ordered_ids(BEST_FALLBACK, available)
    # Guarantee a populated featured strip using only products confirmed in stock.
    if len(best_ids) < 3:
        best_ids = [p["id"] for p in products[:min(8, len(products))]]
    upsell_ids = ordered_ids(UPSELL_PRIORITY, available)
    if len(upsell_ids) < 3:
        upsell_ids = [p["id"] for p in products if p["id"] not in upsell_ids][:5] + upsell_ids
    example_ids = ordered_ids(EXAMPLE_PRIORITY, available)
    if len(example_ids) < 3:
        example_ids = [p["id"] for p in products[:3]]
    data = {
        "collectedAt": collected_at,
        "source": snap["source"],
        "sourceTotal": int(snap["sourceTotal"]),
        "availableCount": len(products),
        "maxAgeMinutes": PAGE_MAX_AGE_MINUTES,
        "products": products,
        "routines": routines,
        "best": best_ids,
        "upsell": upsell_ids[:10],
        "example": example_ids,
    }
    data_js = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

    def floats(class_names, ids):
        out = []
        for class_name, pid in zip(class_names, ids):
            p = by_id.get(pid)
            if p:
                out.append(f'<img class="{class_name}" src="{html.escape(p["image"], quote=True)}" alt="">')
        return "".join(out)

    routine_html = []
    for r in routines:
        routine_html.append(r)
    if not routines:
        # The section remains hidden instead of suggesting any unavailable product.
        pass

    page = TEMPLATE.read_text(encoding="utf-8")
    page = page.replace("__DATA__", data_js)
    page = page.replace("__POPUP_FLOATS__", floats(["float f1", "float f2", "float f3"], [7, 1, 22]))
    page = page.replace("__HERO_FLOATS__", floats(["h1", "h2", "h3"], [49, 1, 4]))
    page = page.replace("__MARQUEE__", "".join(f"<span>{html.escape(t)}</span>" for t in ["BLACK FRIDAY", "JUSQU’À −20 %", "21 — 27 NOVEMBRE", "TOUTE LA BOUTIQUE", "STOCKS LIMITÉS", "K-BEAUTY AUTHENTIQUE"] * 4))
    # No repository-local product images: render the exact image URLs exposed publicly by the product records.
    page = page.replace('const imgOf=p=>`img/${p.id}.webp`;', 'const imgOf=p=>p.image;')
    page = page.replace('Aperçu · Black Friday 21–27 nov.', 'PRÉPROD · OFFRE SIMULÉE')
    page = page.replace('<meta name="robots" content="noindex,nofollow">', '<meta name="robots" content="noindex,nofollow">\n<meta name="referrer" content="strict-origin-when-cross-origin">')
    # Add clear pre-production status and fail-closed error state.
    page = page.replace('</style>', '''
body{visibility:hidden}
body.sync-ok{visibility:visible}
body.sync-error{visibility:visible}
#syncError{display:none;position:fixed;inset:0;z-index:9999;place-items:center;padding:24px;background:var(--ivory);text-align:center}
body.sync-error #syncError{display:grid!important}
body.sync-error > :not(#syncError){display:none!important}
.sync-strip{display:flex;align-items:center;justify-content:center;gap:10px;padding:5px 16px 8px;border-top:1px solid rgba(234,223,214,.7);color:var(--rose-d);font-size:10px;letter-spacing:.06em;text-transform:uppercase}
.sync-strip small{font-size:10px;letter-spacing:0;text-transform:none;color:var(--ink2)}
#syncError h1{font-size:clamp(34px,6vw,60px);margin:0 0 12px}
#syncError p{max-width:620px;color:var(--ink2);margin:8px auto}
#syncError a{display:inline-block;margin-top:18px;color:var(--rose-d);text-decoration:underline}
@media(max-width:700px){.sync-strip{align-items:flex-start;flex-direction:column;gap:1px;padding:4px 12px 6px}.sync-strip small{font-size:9px}}
</style>''')
    page = page.replace('<body>', '''<body>
<div id="syncError" role="alert"><div><div class="kicker">K‑Beauty Tunisia · Préproduction</div><h1>Disponibilités en cours de vérification</h1><p>Le catalogue n’a pas été synchronisé récemment. Pour éviter de montrer un ancien prix ou un stock périmé, cette prévisualisation est momentanément désactivée.</p><p>Aucune commande ou remise réelle n’est possible ici.</p><a href="https://kbeauty-tunisia.com/">Consulter la boutique officielle</a></div></div>''')
    # Explicitly label the screenshot as a mock homepage preview; it does not inject a popup into the live store.
    page = page.replace('aria-label="Page d’accueil K-Beauty Tunisia">', 'aria-label="Maquette d’accueil du site K-Beauty Tunisia — aperçu, non intégrée à la boutique">')
    # Do not claim or imply this page is connected to live checkout.
    page = page.replace('<div class="kicker">Black Friday · 21 — 27 novembre</div>', '<div class="kicker">Préproduction · offre simulée · 21 — 27 novembre</div>')
    page = page.replace('Le panier et les remises sont simulés; aucune commande, paiement ou remise réelle.', 'Le panier et les remises sont simulés; aucune commande, paiement ou remise réelle.')
    opening = f"const DATA={data_js};\n(function(){{"
    guarded_opening = f'''const DATA={data_js};
const collectedMs=Date.parse(DATA.collectedAt);
const ageMs=Date.now()-collectedMs;
const fresh=Number.isFinite(collectedMs)&&ageMs>=-60000&&ageMs<=DATA.maxAgeMinutes*60*1000;
const stamp=document.getElementById('syncStamp');
if(stamp&&Number.isFinite(collectedMs))stamp.textContent=`Catalogue public actualisé ${{new Date(collectedMs).toLocaleString('fr-TN',{{timeZone:'Africa/Tunis'}})}} · prix/stock observés`;
if(!fresh){{document.body.classList.add('sync-error');}}
else {{document.body.classList.add('sync-ok');
(function(){{'''
    page = page.replace(opening, guarded_opening, 1)
    page = page.replace('const SIM_START=Date.UTC(2026,10,21,9,0,0), END=Date.UTC(2026,10,27,22,59,59), t0=performance.now();\nfunction remaining(){const now=SIM_START+(performance.now()-t0);let s=Math.max(0,Math.floor((END-now)/1000));const d=Math.floor(s/86400);s%=86400;const h=Math.floor(s/3600);s%=3600;return{d,h,m:Math.floor(s/60),s:s%60};}', '''const SIM_START=Date.UTC(2026,10,21,9,0,0), END=Date.UTC(2026,10,27,22,59,59);
function remaining(){const now=Date.now();const until=now<SIM_START?SIM_START:END;let s=Math.max(0,Math.floor((until-now)/1000));const d=Math.floor(s/86400);s%=86400;const h=Math.floor(s/3600);s%=3600;return{d,h,m:Math.floor(s/60),s:s%60,started:now>=SIM_START,ended:now>END};}''')
    page = page.replace("function tick(){const r=remaining();$$('[data-k]').forEach(b=>{b.textContent=pad(r[b.dataset.k])});const hc=$('#headCount');if(hc)hc.textContent=`${r.d} j ${pad(r.h)} h ${pad(r.m)} min ${pad(r.s)} s`;}", "function tick(){const r=remaining();$$('[data-k]').forEach(b=>{b.textContent=pad(r[b.dataset.k])});const hc=$('#headCount');if(hc)hc.textContent=r.ended?'Terminée':`${r.d} j ${pad(r.h)} h ${pad(r.m)} min ${pad(r.s)} s`;$$('.count .lbl').forEach(x=>x.textContent=r.ended?'Simulation terminée':r.started?'Fin proposée dans':'Début proposé dans');}")
    # Clearly identify all checkout simulation and never send order data.
    page = page.replace('Simulation : aucune commande ni paiement n’est enregistré.', 'Préproduction : panier simulé uniquement. Aucune commande, donnée client, remise ou paiement n’est envoyé au site.')
    # Remove the old simulated homepage footer/FAQ if a future template adds one.
    page = page.replace('</main>', '</main>')
    # Close the freshness guard around the existing Black Friday app.
    page = page.replace('})();\n</script>', '})();\n}\n</script>')

    if "__DATA__" in page or "__POPUP_FLOATS__" in page or "__HERO_FLOATS__" in page or "__MARQUEE__" in page:
        raise SystemExit("STOP: unresolved build marker.")
    if not page.rstrip().endswith("</html>"):
        raise SystemExit("STOP: generated HTML is incomplete.")
    if "createOrder" in page or "fetch(\"https://kbeauty-tunisia.com/api" in page:
        raise SystemExit("STOP: preview must not submit orders or call mutation endpoints.")
    SITE.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    for asset in (ROOT / "assets").glob("*"):
        (ASSETS / asset.name).write_bytes(asset.read_bytes())
    (SITE / ".nojekyll").write_text("", encoding="utf-8")
    (SITE / "index.html").write_text(page, encoding="utf-8")
    print(f"Built index.html | stock products={len(products)} | routines={len(routines)} | snapshot={collected_at}")


if __name__ == "__main__":
    main()
