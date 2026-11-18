"""Tests bloquants de la préproduction Black Friday V2 (aucune requête vers la boutique, aucune commande)."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent
PORT = 8091
URL = f"http://127.0.0.1:{PORT}/"
sys.path.insert(0, str(ROOT))
import build_site  # noqa: E402

# ---------- 1. Tests du générateur (sans navigateur) ----------
assert len(build_site.SPECIAL_30_IDS) == 55 == len(set(build_site.SPECIAL_30_IDS)), "sélection −30 % invalide"
assert build_site.special_price(129000) == 90000
assert build_site.special_price(89000) == 62000
assert build_site.special_price(11000) == 7000
assert build_site.special_price(19000) == 13000
for price in range(1000, 400000, 1000):
    sp = build_site.special_price(price)
    assert sp % 1000 == 0 and sp * 100 <= price * 70 and (sp + 1000) * 100 > price * 70, (price, sp)

snap = json.loads((ROOT / "catalogue.json").read_text(encoding="utf-8"))
data, by_id, excluded = build_site.build_data(snap)
in_stock = {p["id"] for p in snap["products"] if int(p["availableQuantity"]) > 0}
assert set(data["special"]) == set(build_site.SPECIAL_30_IDS) & in_stock, "offre spéciale ≠ sélection ∩ stock"
assert all(by_id[i]["maxQty"] > 0 for i in data["special"])
assert all(by_id[i]["sp"] == build_site.special_price(by_id[i]["price"]) for i in data["special"] if by_id[i]["spSource"] == "simulation")

# Promotion déjà appliquée en production (prix barré public) : aucune seconde remise.
promo = json.loads(json.dumps(snap))
sp_target = next(p for p in promo["products"] if p["id"] in build_site.SPECIAL_30_IDS)
std_target = next(p for p in promo["products"] if p["id"] not in build_site.SPECIAL_30_IDS)
original = sp_target["priceMillimes"]
sp_target["compareAtMillimes"] = original
sp_target["priceMillimes"] = build_site.special_price(original)
std_target["compareAtMillimes"] = std_target["priceMillimes"] + 10000
p_data, p_by_id, _ = build_site.build_data(promo)
assert p_by_id[sp_target["id"]]["price"] == original, "prix de référence production non repris"
assert p_by_id[sp_target["id"]]["sp"] == build_site.special_price(original), "double remise sur promo production"
assert p_by_id[sp_target["id"]]["spSource"] == "production"
assert p_by_id[std_target["id"]]["price"] == std_target["priceMillimes"], "produit standard : base = prix réel"
assert all(all(pid in by_id for pid in r["ids"]) for r in data["routines"]), "pack affiché avec un produit indisponible"

# Snapshot synthétique : un produit de pack + deux références spéciales passent en rupture.
synthetic = json.loads(json.dumps(snap))
pack_victim = build_site.ROUTINE_SPECS[0]["ids"][0]
special_victims = [i for i in build_site.SPECIAL_30_IDS if i in in_stock][:2]
removed = {pack_victim, *special_victims}
synthetic["products"] = [p for p in synthetic["products"] if p["id"] not in removed]
synthetic["availableCount"] = len(synthetic["products"])
s_data, s_by_id, s_excluded = build_site.build_data(synthetic)
assert all(pack_victim not in r["ids"] for r in s_data["routines"]), "pack non masqué après rupture"
assert not any(r["title"] == build_site.ROUTINE_SPECS[0]["title"] for r in s_data["routines"])
assert not set(special_victims) & set(s_data["special"]), "référence −30 % en rupture encore affichée"
assert set(special_victims) <= set(s_excluded)
with tempfile.TemporaryDirectory() as tmp:
    snap_path = Path(tmp) / "snap.json"
    snap_path.write_text(json.dumps(synthetic), encoding="utf-8")
    out = Path(tmp) / "site"
    subprocess.run([sys.executable, str(ROOT / "build_site.py"), "--snapshot", str(snap_path), "--out", str(out)], check=True, capture_output=True)
    page = (out / "index.html").read_text(encoding="utf-8")
    assert build_site.ROUTINE_SPECS[0]["title"] not in page
    # Incohérence de comptage → arrêt sans build.
    bad = dict(synthetic, availableCount=synthetic["availableCount"] + 1)
    snap_path.write_text(json.dumps(bad), encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "build_site.py"), "--snapshot", str(snap_path), "--out", str(Path(tmp) / "bad")], capture_output=True, text=True)
    assert r.returncode != 0 and not (Path(tmp) / "bad" / "index.html").exists(), "build non fail-closed"

# ---------- 2. Tests navigateur ----------
def expected(pg, cart):
    """Recalcul indépendant en Python de la règle simulée."""
    prods = {p["id"]: p for p in pg.evaluate("window.KBBF.products()")}
    sp = set(pg.evaluate("window.KBBF.special()"))
    refs = len(cart)  # produits différents : les quantités ne changent pas le palier
    rate = 20 if refs >= 3 else 15 if refs == 2 else 10 if refs == 1 else 0
    sub = disc_sp = disc_tier = 0
    for pid, q in cart.items():
        price = prods[pid]["price"] * q
        sub += price
        if pid in sp:
            disc_sp += price - prods[pid]["sp"] * q
        else:
            disc_tier += price - round(price * (100 - rate) / 100)
    return {"rate": rate, "subtotal": sub, "specialDiscount": disc_sp, "tierDiscount": disc_tier, "total": sub - disc_sp - disc_tier}

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path="/usr/bin/chromium", args=["--no-sandbox"])
    desktop = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
    calls, errors = [], []
    desktop.on("request", lambda req: calls.append(req.url))
    desktop.on("pageerror", lambda e: errors.append(str(e)))
    desktop.goto(URL, wait_until="networkidle", timeout=30000)
    assert desktop.locator("body").evaluate("e => e.classList.contains('sync-ok')")
    assert "Préproduction" in desktop.locator("#previewRibbon").inner_text()
    assert desktop.locator("#popup").is_visible(timeout=5000)
    bar = desktop.locator("#homeBar").inner_text()
    assert "−30 %" in bar and "−20" not in bar, bar
    desktop.locator("#popCta").click()
    desktop.wait_for_timeout(1300)
    assert desktop.locator("#bfView").is_visible()

    # Ordre : principe des réductions → routines → prix choc −30 % → Skin Match → boutique.
    order = desktop.evaluate("[...document.querySelectorAll('#bfView > section[id], #bfView > div[id]')].map(e=>e.id)")
    assert order.index("paliers") < order.index("routines") < order.index("offre-speciale") < order.index("skin-match") < order.index("boutique"), order
    how = desktop.locator("#paliers").inner_text()
    assert all(k in how for k in ("−30 %", "−10 %", "−15 %", "−20 %", "150 TND")), how
    sp = desktop.evaluate("window.KBBF.special()")
    assert len(sp) == len(data["special"]) > 0
    assert desktop.locator("#offre-speciale").is_visible()
    assert "dans la limite du stock disponible" in desktop.locator("#offre-speciale").inner_text().lower()
    # Compte à rebours : fin de l'offre le 30/11/2026 23:59:59 heure de Tunis.
    import datetime as _dt
    assert desktop.evaluate("window.KBBF.endsAt") == int(_dt.datetime(2026, 11, 30, 22, 59, 59, tzinfo=_dt.timezone.utc).timestamp() * 1000)
    assert "Fin de l’offre dans" in desktop.locator(".head-count").inner_text()
    assert "Prix choc" in desktop.locator(".tierbar").inner_text() and "−30 %" in desktop.locator(".tierbar").inner_text()
    desktop.locator("#spMore").click()
    assert desktop.locator("#spGrid .card.is-sp").count() == len(sp)
    # Cartes : montant économisé en TND, aucun pourcentage sur les cartes produit.
    card_text = " ".join(desktop.locator(".card .price, .card .save, .card .hint, .card .badges").all_inner_texts())
    assert "%" not in card_text, "pourcentage affiché sur une carte produit"
    assert desktop.locator(".card .save").count() >= len(sp)
    assert all("TND" in t for t in desktop.locator(".card .save").all_inner_texts())
    assert desktop.locator(".routine").count() == len(data["routines"])
    # Routines : pastille en %, économie en TND mise en avant et reprise dans le bouton.
    import re
    for k in range(desktop.locator(".routine").count()):
        card = desktop.locator(".routine").nth(k)
        assert card.locator(".rsave").inner_text().strip() == "−20 %", card.locator(".rsave").inner_text()
        gain = card.locator(".rgain b").inner_text().strip()
        assert gain.endswith("TND") and gain in card.locator("[data-routine]").inner_text()
        assert "%" not in card.locator("[data-routine]").inner_text(), "bouton routine en pourcentage"
        assert card.evaluate("c => [...c.querySelectorAll('.rgain, .rgain span, [data-routine]')].every(e => e.scrollWidth <= e.clientWidth + 1)"), "routine tronquée"
    # Le mot « stock » ne doit apparaître qu’une fois dans la page (mention de l’offre −30 %).
    visible = desktop.evaluate("document.body.innerText")
    assert len(re.findall("stock", visible, re.I)) <= 1, re.findall(r".{0,40}stock.{0,20}", visible, re.I)
    # Jamais de nombre de produits à −30 % affiché, ni bloc de statistiques.
    desktop.locator("#spMore").evaluate("e => e.click()") if desktop.locator("#spMore").is_visible() else None
    shown_text = desktop.evaluate("document.body.innerText")
    n_sp = len(sp)
    assert not re.search(rf"(?<![\d,.]){n_sp}(?![\d,.])\s*(produits?|prix choc|références|soins)", shown_text, re.I), "nombre de produits −30 % affiché"
    assert desktop.locator(".sp-stats, #spStatCount, #spStatMax, #spStatMin, [data-sp-count]").count() == 0
    assert desktop.locator("#spChips small, [data-cat='__sp'] small").count() == 0, "compteur sur les filtres prix choc"
    # Aucun vocabulaire qui laisse penser à une liste d'invendus ni ancienne période.
    banned = re.findall(r"offre sp[ée]ciale|s[ée]lection|invendu|21\s*(?:—|au)\s*27|27 nov|z[ée]ro code|sans code|code promo|palier|skin match|hors prix choc|catalogue public", visible, re.I)
    assert not banned, banned

    std = [x["id"] for x in desktop.evaluate("window.KBBF.products()") if x["id"] not in sp]
    cases = [
        {sp[0]: 1},                      # spécial seul : prix spécial, aucune remise palier
        {sp[0]: 1, std[0]: 1},           # mixte 2 unités → −15 % sur le standard seulement
        {sp[0]: 1, sp[1]: 1, std[0]: 1}, # 3 unités dont 2 spéciales → −20 % sur le standard
        {std[0]: 1, std[1]: 1, std[2]: 1},
        {sp[0]: 1, sp[1]: 1, sp[2]: 1},
        {std[0]: 3},                     # 3 unités d'un même produit = 1 produit différent → −10 %
        {std[0]: 2, std[1]: 2},          # 4 unités, 2 produits différents → −15 %
        {sp[0]: 2, std[0]: 1, std[1]: 1, std[2]: 1},  # 4 produits différents → −20 % hors prix choc
    ]
    for cart in cases:
        desktop.evaluate("window.KBBF.clear()")
        for pid, q in cart.items():
            desktop.evaluate("([i,n]) => window.KBBF.add(i,n)", [pid, q])
        got = desktop.evaluate("window.KBBF.calculate()")
        exp = expected(desktop, cart)
        for k, v in exp.items():
            assert got[k] == v, (cart, k, got[k], v)
        assert got["total"] == got["subtotal"] - got["discount"] and got["discount"] == got["specialDiscount"] + got["tierDiscount"]
        for line in got["lines"]:
            if line["kind"] == "special":
                assert line["total"] == by_id[line["id"]]["sp"] * line["qty"], "double remise sur un produit spécial"
    # Palier : changer une quantité ne change pas le palier ; ajouter/retirer un produit différent oui.
    desktop.evaluate("window.KBBF.clear()")
    desktop.evaluate("([a,b]) => {window.KBBF.add(a,1);window.KBBF.add(b,1)}", [std[0], std[1]])
    assert desktop.evaluate("window.KBBF.calculate()")["rate"] == 15
    desktop.evaluate("([a]) => window.KBBF.setQty(a, 1)", [std[0]])
    assert desktop.evaluate("window.KBBF.calculate()")["rate"] == 15
    desktop.evaluate("([a]) => window.KBBF.setQty(a, -2)", [std[0]])
    assert desktop.evaluate("window.KBBF.calculate()")["rate"] == 10
    # Routines : offre autonome à prix fixe, aucune seconde remise, produits internes hors palier.
    desktop.evaluate("window.KBBF.clear()")
    if data["routines"]:
        for ri, r in enumerate(data["routines"]):
            rc = desktop.evaluate("i => window.KBBF.routineCalc(i)", ri)
            lst = sum(by_id[i]["price"] for i in r["ids"])
            assert rc["list"] == lst and rc["now"] == round(lst * 80 / 100) and rc["pct"] == 20, ("pack hors −20 %", r["title"], rc)
        r0 = desktop.evaluate("window.KBBF.routineCalc(0)")
        assert r0["save"] == r0["list"] - r0["now"] > 0
        desktop.evaluate("window.KBBF.addRoutine(0)")
        c = desktop.evaluate("window.KBBF.calculate()")
        assert c["refs"] == 0 and c["rate"] == 0 and c["total"] == r0["now"] and c["routineDiscount"] == r0["save"]
        desktop.evaluate("([a]) => window.KBBF.add(a,1)", [std[5]])
        c = desktop.evaluate("window.KBBF.calculate()")
        exp_line = by_id[std[5]]["price"] - round(by_id[std[5]]["price"] * 90 / 100)
        assert c["refs"] == 1 and c["rate"] == 10 and c["tierDiscount"] == exp_line, "routine comptée dans le palier"
        assert c["total"] == r0["now"] + round(by_id[std[5]]["price"] * 90 / 100), "prix de routine modifié"
        desktop.evaluate("window.KBBF.clear()")
    # Skin Match : 3 questions → routine disponible, catégories distinctes, prix recalculé, ajout au panier.
    prods = {x["id"]: x for x in desktop.evaluate("window.KBBF.products()")}
    for skin in ("grasse", "seche", "sensible", "normale"):
        for goal in ("pores", "eclat", "hydra", "apaise", "age"):
            for size in ("3", "4"):
                ids = desktop.evaluate("a => window.KBBF.skinMatch(a)", {"skin": skin, "goal": goal, "size": size})
                assert 2 <= len(ids) <= int(size) and len(set(ids)) == len(ids), (skin, goal, size, ids)
                assert all(i in prods and prods[i]["maxQty"] > 0 for i in ids)
                assert len({prods[i]["cat"] for i in ids}) == len(ids), "Skin Match : deux produits de même étape"
                c = desktop.evaluate("ids => window.KBBF.smCalc(ids)", ids)
                rate = 20 if len(ids) >= 3 else 15
                exp_now = sum(by_id[i]["sp"] if i in sp else round(by_id[i]["price"] * (100 - rate) / 100) for i in ids)
                assert c["now"] == exp_now and c["save"] == c["list"] - c["now"] > 0, (ids, c, exp_now)
    desktop.evaluate("window.KBBF.clear()")
    desktop.evaluate("document.querySelector('#skin-match').scrollIntoView()")
    for k in range(3):
        desktop.locator("#smBox .sm-opt").first.click()
    assert desktop.locator("#smBox .sm-list li").count() >= 2
    shown_ids = [int(x) for x in desktop.locator("#smBox").get_attribute("data-ids").split(",")]
    gain = desktop.locator("#smBox .sm-gain b").inner_text()
    assert gain in desktop.locator("[data-smadd]").inner_text() and "%" not in desktop.locator("[data-smadd]").inner_text()
    desktop.locator("[data-smadd]").click()
    desktop.wait_for_timeout(900)
    assert set(map(int, desktop.evaluate("Object.keys(window.KBBF.cart())"))) == set(shown_ids)
    after = desktop.evaluate("window.KBBF.calculate()")
    assert after["total"] == desktop.evaluate("ids => window.KBBF.smCalc(ids)", shown_ids)["now"], "Skin Match ≠ panier"
    desktop.keyboard.press("Escape")
    desktop.evaluate("window.KBBF.clear()")
    # Stock : impossible de dépasser la quantité publique.
    desktop.evaluate("window.KBBF.clear()")
    target = by_id[sp[0]]
    desktop.evaluate("([i,n]) => window.KBBF.add(i,n)", [target["id"], target["maxQty"] + 5])
    assert desktop.evaluate("window.KBBF.cart()")[str(target["id"])] == target["maxQty"]

    desktop.evaluate("([a,b]) => {window.KBBF.clear();window.KBBF.add(a,1);window.KBBF.add(b,1)}", [sp[0], std[0]])
    desktop.locator("#cartBtn").click()
    foot = desktop.locator("#drFoot").inner_text().lower()
    assert "prix choc" in foot and "black friday −" in foot and "préproduction" in foot
    desktop.locator("#checkout").click()
    assert desktop.locator("#modal").is_visible()
    assert "aucune commande" in desktop.locator("#modal").inner_text().lower()
    assert desktop.locator("footer").count() == 0
    assert not any("/api/" in u or "kbeauty-tunisia.com/api" in u for u in calls), [u for u in calls if "/api/" in u]
    assert not errors, errors

    # ---------- 3. Responsive ----------
    for width, height in [(390, 844), (375, 667), (360, 780), (768, 1024)]:
        m = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
        m_err = []
        m.on("pageerror", lambda e: m_err.append(str(e)))
        m.goto(URL, wait_until="networkidle", timeout=30000)
        assert m.locator("#popup").is_visible(timeout=5000)
        m.locator("#popCta").click()
        m.wait_for_timeout(2300)
        assert m.locator("#bfView").is_visible()
        m.evaluate("document.querySelectorAll('.reveal').forEach(e=>e.classList.add('vis'))")
        for sel in ["#offre-speciale", "#paliers", "#routines", "#skin-match", "#boutique"]:
            m.evaluate(f"document.querySelector('{sel}').scrollIntoView()")
            m.wait_for_timeout(150)
            assert m.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), f"débordement horizontal {width}px {sel}"
        clipped = m.evaluate("""() => [...document.querySelectorAll('#spGrid .card')].slice(0,6).filter(c => {
            const r=c.getBoundingClientRect(); const s=c.querySelector('.save');
            return r.right > innerWidth + 1 || r.left < -1 || (s && s.scrollWidth > s.clientWidth + 1);
        }).length""")
        assert clipped == 0, f"carte tronquée à {width}px"
        if width < 760:
            assert m.locator("#mbar").is_visible()
        m.evaluate("document.querySelector('#skin-match').scrollIntoView()")
        for k in range(3):
            m.locator("#smBox .sm-opt").nth(k % 2).click()
        assert m.evaluate("[...document.querySelectorAll('#smBox, #smBox .sm-list li, #smBox .sm-gain, #smBox .sm-cta')].every(e => e.getBoundingClientRect().right <= innerWidth + 1 && e.scrollWidth <= e.clientWidth + 1)"), f"Skin Match tronqué à {width}px"
        m.evaluate("window.KBBF.clear()")
        m.evaluate("([a,b]) => {window.KBBF.add(a,1);window.KBBF.add(b,1)}", [sp[0], std[0]])
        m.locator("#mCart" if width < 760 else "#cartBtn").click()
        m.wait_for_timeout(600)
        assert m.locator("#drawer").evaluate("e => e.getBoundingClientRect().width <= innerWidth + 1")
        assert not m_err, m_err
        m.close()

    # ---------- 4. Garde de fraîcheur ----------
    stale = browser.new_page(viewport={"width": 1000, "height": 800})
    stale.add_init_script("const real=Date.now; Date.now=()=>real()+46*60*1000;")
    stale.goto(URL, wait_until="networkidle", timeout=30000)
    assert stale.locator("body").evaluate("e => e.classList.contains('sync-error')")
    assert stale.locator("#syncError").is_visible()
    assert stale.locator("#bfView").is_hidden()
    browser.close()

print(
    f"PASS V2.5 | stock={len(data['products'])} | −30 % affichées={len(data['special'])}/55 | packs={len(data['routines'])}/5 | "
    "prix spécial floor 70 % | non-cumul paliers | rupture pack/spécial masquée | fail-closed build+fraîcheur | "
    "aucun % sur cartes | paliers par produits différents | routines −20 % hors palier | fin 30/11 | "
    "textes humains sans code ni palier | aucun comptage −30 % | packs −20 % exact | bannière −30 % | ordre principe>routines>prix choc>Skin Match | Skin Match 40 profils | "
    "aucun appel API | responsive 360/375/390/768"
)
