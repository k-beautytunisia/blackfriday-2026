#!/usr/bin/env python3
"""Build a standalone, non-transactional Black Friday preview from a public catalog snapshot.

V2 — Offre spéciale −30 % (sélection fixe par ID, filtrée au stock à chaque build),
économies affichées en TND, packs masqués dès qu'un composant n'est plus en stock.
Aucune commande, aucun paiement, aucune remise réelle : simulation uniquement.
"""
from pathlib import Path
from datetime import datetime
import argparse
import hashlib
import io
from concurrent.futures import ThreadPoolExecutor
import html
import json
import re

ROOT = Path(__file__).parent
TEMPLATE = ROOT / "template.html"
PAGE_MAX_AGE_MINUTES = 30
# Images produit : copies allégées (WebP, 720 px max) servies avec la page, au lieu de 25 Mo tirés du serveur boutique.
IMG_MAX_SIDE = 720
IMG_QUALITY = 80
IMG_CACHE = ROOT / ".img-cache"
IMG_MAX_FAIL_RATIO = 0.2
SPECIAL_RATE = 30

# Sélection « Offre spéciale −30 % » transmise par le gérant le 18/11/2026 (55 captures de fiches),
# rattachée par identifiant public du catalogue. Seuls les IDs encore en stock au moment du build sont affichés.
SPECIAL_30_IDS = [
    50, 3, 249, 234, 28, 51, 5, 178, 4, 20, 49, 41, 19, 44, 185, 179, 56, 52, 187, 233,
    215, 196, 183, 184, 206, 65, 237, 251, 250, 40, 220, 54, 22, 53, 236, 39, 198, 192, 235, 9,
    252, 62, 63, 211, 218, 209, 15, 263, 165, 231, 213, 177, 219, 256, 262,
]
SPECIAL_EXPECTED_COUNT = 55

ROUTINE_SPECS = [
    {"title": "Peaux mixtes / normales", "for": "Mousse nettoyante · ampoule · crème", "ids": [2, 49, 53]},
    {"title": "Peaux sensibles / grasses", "for": "Huile nettoyante · mousse · crème hydratante", "ids": [3, 2, 236]},
    {"title": "Peaux sensibles acnéiques", "for": "Toner Heartleaf · Glow Serum · crème Centella", "ids": [4, 251, 53]},
    {"title": "Tous types de peau", "for": "Sérum Niacinamide · Capsule Cream · Matte Sun Stick", "ids": [1, 235, 9]},
    {"title": "Peaux sensibles normales", "for": "Nettoyant Dokdo · toner Centella · crème PDRN", "ids": [212, 51, 236]},
]
BEST_PRIORITY = [1, 49, 7, 19, 22, 40, 233, 237, 41, 250, 5, 4, 51, 52, 236, 235, 251, 221, 13, 15]
UPSELL_PRIORITY = [15, 263, 209, 211, 218, 63, 13, 207, 60, 222]
EXAMPLE_PRIORITY = [49, 1, 7]
POPUP_FLOAT_IDS = [19, 49, 22]
HERO_FLOAT_IDS = [49, 41, 4]
MARQUEE_WITH_SPECIAL = ["BLACK FRIDAY", "JUSQU’À −30 %", "LIVRAISON OFFERTE DÈS 150 TND", "QUANTITÉS LIMITÉES",
                        "JUSQU’AU 30 NOVEMBRE", "K-BEAUTY AUTHENTIQUE"]
MARQUEE_WITHOUT_SPECIAL = ["BLACK FRIDAY", "JUSQU’À −20 % SUR LE PANIER", "JUSQU’AU 30 NOVEMBRE",
                           "QUANTITÉS LIMITÉES", "K-BEAUTY AUTHENTIQUE"]


def special_price(price_millimes: int) -> int:
    """70 % du prix boutique, arrondi au dinar inférieur (remise effective ≥ 30 %)."""
    return (int(price_millimes) * (100 - SPECIAL_RATE) // 100) // 1000 * 1000


def clean_name(name: str, brand: str) -> str:
    value = name
    for prefix in (brand + " – ", brand + " - ", brand.upper() + " ", brand + " "):
        if brand and value.lower().startswith(prefix.lower()):
            value = value[len(prefix):]
            break
    value = re.sub(r"\s+—\s+\d+[.,]?\d*\s*(ml|g)\s*$", "", value, flags=re.I)
    return value.strip(" –-")


def ordered_ids(ids, available):
    return [int(pid) for pid in ids if int(pid) in available]


def validate_selection() -> None:
    if len(SPECIAL_30_IDS) != len(set(SPECIAL_30_IDS)):
        raise SystemExit("STOP: la sélection −30 % contient des identifiants dupliqués; aucun build généré.")
    if len(SPECIAL_30_IDS) != SPECIAL_EXPECTED_COUNT:
        raise SystemExit("STOP: la sélection −30 % ne correspond pas au nombre de références validé; aucun build généré.")


def build_data(snap: dict):
    validate_selection()
    collected_at = str(snap.get("collectedAt", ""))
    parsed = datetime.fromisoformat(collected_at)
    if parsed.tzinfo is None:
        raise SystemExit("STOP: snapshot timestamp has no timezone.")
    special_requested = set(SPECIAL_30_IDS)
    products = []
    for source in snap.get("products", []):
        if not source.get("image") or not source.get("url") or int(source.get("availableQuantity", 0)) <= 0:
            continue
        current = int(source["priceMillimes"])
        compare_at = source.get("compareAtMillimes")
        compare_at = int(compare_at) if compare_at and int(compare_at) > current else None
        # Prix de référence affiché barré : prix boutique, ou prix barré production si une promo y est déjà active.
        price = compare_at if (compare_at and int(source["id"]) in special_requested) else current
        product = {
            "id": int(source["id"]),
            "name": clean_name(str(source.get("name") or ""), str(source.get("brand") or "")),
            "brand": str(source.get("brand") or ""),
            "volume": str(source.get("volume") or ""),
            "cat": str(source.get("categorySlug") or "autres"),
            "catName": str(source.get("category") or "Autres"),
            "price": price,
            "maxQty": int(source["availableQuantity"]),
            "low": int(source["availableQuantity"]) <= 3,
            "best": bool(source.get("bestSeller")),
            "rank": 9999,
            "url": str(source["url"]),
            "image": str(source["image"]),
        }
        if product["id"] in special_requested:
            if compare_at:
                # Promotion déjà appliquée en production : on reprend le prix réel, jamais de seconde remise.
                product["sp"] = current
                product["spSource"] = "production"
            else:
                sp = special_price(price)
                if 0 < sp and sp * 100 <= price * (100 - SPECIAL_RATE):
                    product["sp"] = sp
                    product["spSource"] = "simulation"
        products.append(product)
    if len(products) != int(snap.get("availableCount", -1)) or not products:
        raise SystemExit("STOP: snapshot stock count is inconsistent; no build generated.")

    available = {p["id"] for p in products}
    priority = {pid: i for i, pid in enumerate(BEST_PRIORITY)}
    products.sort(key=lambda p: (priority.get(p["id"], 1000), -p["best"], -min(p["maxQty"], 10), -p["price"]))
    for i, product in enumerate(products):
        product["rank"] = i
    by_id = {p["id"]: p for p in products}

    special = [p["id"] for p in products if "sp" in p]
    special_set = set(special)
    excluded = [pid for pid in SPECIAL_30_IDS if pid not in special_set]

    # Un pack n'est rendu que si TOUS ses produits sont en stock explicite dans ce snapshot.
    routines = [spec for spec in ROUTINE_SPECS if all(pid in available for pid in spec["ids"])]

    # Incontournables : références phares hors offre spéciale (elles profitent des paliers), sinon repli en stock.
    best_ids = [p["id"] for p in products if p["id"] not in special_set][:10]
    if len(best_ids) < 3:
        best_ids = [p["id"] for p in products[: min(8, len(products))]]

    upsell_ids = ordered_ids(UPSELL_PRIORITY, available)
    if len(upsell_ids) < 3:
        cheapest = sorted(products, key=lambda p: (p.get("sp", p["price"]), p["rank"]))
        upsell_ids += [p["id"] for p in cheapest if p["id"] not in upsell_ids][: 6 - len(upsell_ids)]

    example_ids = ordered_ids(EXAMPLE_PRIORITY, available)
    if len(example_ids) < 3:
        sp_first = [pid for pid in special][:1]
        std_first = [p["id"] for p in products if p["id"] not in special_set][: 3 - len(sp_first)]
        example_ids = sp_first + std_first
        if len(example_ids) < 3:
            example_ids = [p["id"] for p in products[:3]]

    data = {
        "collectedAt": collected_at,
        "source": snap["source"],
        "sourceTotal": int(snap["sourceTotal"]),
        "availableCount": len(products),
        "maxAgeMinutes": PAGE_MAX_AGE_MINUTES,
        "products": products,
        "special": special,
        "specialRequested": len(SPECIAL_30_IDS),
        "specialRate": SPECIAL_RATE,
        "routines": routines,
        "best": best_ids,
        "upsell": upsell_ids[:10],
        "example": example_ids,
    }
    return data, by_id, excluded


def _image_key(url: str, session) -> str:
    """Clé de cache : URL + version publique (ETag/Last-Modified/taille). Une image remplacée à la même URL est recopiée."""
    version = ""
    try:
        head = session.head(url, timeout=20, allow_redirects=True)
        if head.ok:
            version = "|".join(head.headers.get(h, "") for h in ("ETag", "Last-Modified", "Content-Length"))
    except Exception:
        version = ""
    return hashlib.sha1(f"{url}|{version}".encode()).hexdigest()[:20]


def _optimize_one(url: str, cache_dir: Path, out_dir: Path, session) -> str | None:
    from PIL import Image

    key = _image_key(url, session)
    name = f"{key}.webp"
    cached = cache_dir / name
    if not cached.exists() or cached.stat().st_size < 1000:
        try:
            resp = session.get(url, timeout=60)
            resp.raise_for_status()
            if not resp.headers.get("Content-Type", "").startswith("image/"):
                return None
            im = Image.open(io.BytesIO(resp.content))
            im.load()
        except Exception:
            return None
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA" if "transparency" in im.info or im.mode in ("LA", "P") else "RGB")
        im.thumbnail((IMG_MAX_SIDE, IMG_MAX_SIDE), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "WEBP", quality=IMG_QUALITY, method=6)
        if buf.tell() < 1000:
            return None
        tmp = cached.with_suffix(".tmp")
        tmp.write_bytes(buf.getvalue())
        tmp.replace(cached)
    (out_dir / name).write_bytes(cached.read_bytes())
    return f"img/{name}"


def localize_images(products: list, site_dir: Path, cache_dir: Path = IMG_CACHE) -> list:
    """Remplace chaque image produit par une copie allégée locale. Échec ponctuel : l'URL d'origine reste en secours."""
    import requests

    cache_dir.mkdir(parents=True, exist_ok=True)
    out_dir = site_dir / "img"
    if out_dir.exists():
        for old in out_dir.glob("*.webp"):
            old.unlink()
    out_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = "kbeauty-bf-preview/1.0 (+read-only image copy)"
    urls = sorted({p["image"] for p in products})
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = dict(zip(urls, pool.map(lambda u: _optimize_one(u, cache_dir, out_dir, session), urls)))
    failed = [u for u, local in results.items() if not local]
    if len(failed) > len(urls) * IMG_MAX_FAIL_RATIO:
        raise SystemExit(f"STOP: {len(failed)}/{len(urls)} images produit illisibles; aucun build généré.")
    for p in products:
        p["imageOrig"] = p["image"]
        p["image"] = results.get(p["image"]) or p["image"]
    return failed


def render(data: dict, by_id: dict) -> str:
    data_js = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    has_special = bool(data["special"])

    def floats(class_names, preferred):
        ids = [pid for pid in preferred if pid in by_id]
        for p in sorted(by_id.values(), key=lambda x: x["rank"]):
            if len(ids) >= len(class_names):
                break
            if p["id"] not in ids:
                ids.append(p["id"])
        return "".join(
            f'<img class="{c}" src="{html.escape(by_id[pid]["image"], quote=True)}" alt="">'
            for c, pid in zip(class_names, ids)
        )

    marquee = MARQUEE_WITH_SPECIAL if has_special else MARQUEE_WITHOUT_SPECIAL
    page = TEMPLATE.read_text(encoding="utf-8")
    page = page.replace("__DATA__", data_js)
    page = page.replace("__POPUP_FLOATS__", floats(["float f1", "float f2", "float f3"], POPUP_FLOAT_IDS))
    page = page.replace("__HERO_FLOATS__", floats(["h1", "h2", "h3"], HERO_FLOAT_IDS))
    page = page.replace("__MARQUEE__", "".join(f"<span>{html.escape(t)}</span>" for t in marquee * 4))

    if any(marker in page for marker in ("__DATA__", "__POPUP_FLOATS__", "__HERO_FLOATS__", "__MARQUEE__")):
        raise SystemExit("STOP: unresolved build marker.")
    if not page.rstrip().endswith("</html>"):
        raise SystemExit("STOP: generated HTML is incomplete.")
    if "createOrder" in page or "fetch(" in page or "XMLHttpRequest" in page or "sendBeacon" in page:
        raise SystemExit("STOP: preview must not submit orders or call any endpoint.")
    for required in ("Préproduction · remises simulées", "sync-error", 'id="offre-speciale"', "maxAgeMinutes"):
        if required not in page:
            raise SystemExit(f"STOP: required preview safeguard missing ({required}).")
    return page


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", default=str(ROOT / "catalogue.json"))
    parser.add_argument("--out", default=str(ROOT / "site"))
    args = parser.parse_args(argv)
    snap = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    data, by_id, excluded = build_data(snap)
    site = Path(args.out)
    site.mkdir(parents=True, exist_ok=True)
    img_failed = localize_images(data["products"], site)
    page = render(data, by_id)
    assets = site / "assets"
    site.mkdir(parents=True, exist_ok=True)
    assets.mkdir(parents=True, exist_ok=True)
    for asset in (ROOT / "assets").glob("*"):
        (assets / asset.name).write_bytes(asset.read_bytes())
    (site / ".nojekyll").write_text("", encoding="utf-8")
    (site / "index.html").write_text(page, encoding="utf-8")
    print(
        f"Built index.html | stock products={len(data['products'])} | special −30 % affichées="
        f"{len(data['special'])}/{data['specialRequested']} | non affichées (hors stock/hors snapshot)={excluded} | "
        f"packs={len(data['routines'])}/{len(ROUTINE_SPECS)} | images locales={len(data['products'])-len(img_failed)}/{len(data['products'])} | snapshot={data['collectedAt']}"
    )


if __name__ == "__main__":
    main()
