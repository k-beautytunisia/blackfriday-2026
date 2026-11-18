#!/usr/bin/env python3
"""Read-only collector for the public K-Beauty catalog; writes a minimized snapshot."""
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo
import json
import math
import requests

BASE = "https://kbeauty-tunisia.com"
ENDPOINT = BASE + "/api/trpc/shop.getProducts"
OUT = Path(__file__).parent / "catalogue.json"
PAGE_SIZE = 100


def fetch_page(page: int) -> dict:
    params = {
        "batch": "1",
        "input": json.dumps({"0": {"json": {"page": page, "limit": PAGE_SIZE}}}, separators=(",", ":")),
    }
    response = requests.get(ENDPOINT, params=params, timeout=30)
    response.raise_for_status()
    payload = response.json()
    data = payload[0]["result"]["data"]
    return data.get("json", data)


def image_url(raw) -> str | None:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            raw = [raw]
    if not isinstance(raw, list) or not raw:
        return None
    first = raw[0]
    if isinstance(first, dict):
        first = first.get("url") or first.get("src")
    return urljoin(BASE, str(first)) if first else None


def main() -> None:
    first = fetch_page(1)
    total = int(first.get("total", 0))
    if total <= 0:
        raise SystemExit("STOP: le catalogue public a retourné un total nul.")
    page_count = math.ceil(total / PAGE_SIZE)
    raw_products = list(first.get("products", []))
    for page in range(2, page_count + 1):
        data = fetch_page(page)
        if int(data.get("total", -1)) != total:
            raise SystemExit("STOP: le total a changé pendant la collecte; aucune publication du snapshot.")
        raw_products.extend(data.get("products", []))
    if len(raw_products) != total:
        raise SystemExit(f"STOP: collecte incomplète ({len(raw_products)}/{total}); aucune publication du snapshot.")

    products = []
    seen = set()
    for raw in raw_products:
        pid = int(raw["id"])
        if pid in seen:
            raise SystemExit("STOP: identifiant produit dupliqué dans le résultat paginé.")
        seen.add(pid)
        try:
            stock = int(raw.get("stock")) if raw.get("stock") is not None else None
            price_millimes = round(float(raw["price"]) * 1000)
            compare_raw = raw.get("compareAtPrice")
            compare_millimes = round(float(compare_raw) * 1000) if compare_raw not in (None, "") else None
        except (TypeError, ValueError, KeyError):
            raise SystemExit(f"STOP: prix/stock non interprétable pour le produit public {pid}.")
        stock_status = raw.get("stockStatus")
        available = bool(raw.get("isActive")) and stock_status == "in_stock" and stock is not None and stock > 0
        if not available:
            continue
        slug = str(raw.get("slug") or "")
        image = image_url(raw.get("images"))
        if not slug or not image or price_millimes <= 0:
            raise SystemExit(f"STOP: données publiques obligatoires absentes pour le produit {pid}.")
        products.append({
            "id": pid,
            "name": str(raw.get("nameFr") or raw.get("nameEn") or "Produit K-Beauty"),
            "brand": str(raw.get("brandName") or ""),
            "category": str(raw.get("categoryName") or "Autres"),
            "categorySlug": str(raw.get("categorySlug") or "autres"),
            "volume": str(raw.get("volume") or ""),
            "priceMillimes": price_millimes,
            # Prix barré public (si une promotion production est active) ; None sinon.
            "compareAtMillimes": compare_millimes if compare_millimes and compare_millimes > price_millimes else None,
            "availableQuantity": stock,
            "bestSeller": bool(raw.get("isBestSeller")),
            "image": image,
            "url": BASE + "/produits/" + slug,
        })
    if not products:
        raise SystemExit("STOP: aucun produit en stock explicite; aucune publication du snapshot.")

    collected = datetime.now(ZoneInfo("Africa/Tunis")).isoformat(timespec="seconds")
    snapshot = {
        "version": "blackfriday-2026-preview-v1",
        "collectedAt": collected,
        "timezone": "Africa/Tunis",
        "currency": "TND",
        "source": ENDPOINT,
        "sourceTotal": total,
        "availableCount": len(products),
        "products": products,
        "limits": "Instantané minimisé des données publiques; collecte en lecture seule. Les prix et quantités peuvent changer après l’horodatage.",
    }
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    tmp.replace(OUT)
    print(f"OK | catalogue public {total} | en stock explicite {len(products)} | collecté {collected} Africa/Tunis")


if __name__ == "__main__":
    main()
