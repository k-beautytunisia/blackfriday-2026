# Black Friday 2026 — préproduction K-Beauty Tunisia

Projet distinct du dépôt du site de production. URL GitHub Pages : `https://k-beautytunisia.github.io/blackfriday-2026/` (avec le tiret de `k-beautytunisia`).

## Ce que fait la préproduction (V2)

- Lit en lecture seule le catalogue public de `https://kbeauty-tunisia.com/api/trpc/shop.getProducts`.
- Reconstruit les produits, images, prix et disponibilités explicitement en stock toutes les 15 minutes via GitHub Actions ; l’horodatage est visible sur la page.
- N’affiche que les fiches actives avec un statut public `in_stock` et une quantité publique strictement positive.
- Rayon « Offre spéciale −30 % » : 55 références sélectionnées (`SPECIAL_30_IDS` dans `build_site.py`). À chaque build, seules les références de cette liste encore en stock sont affichées ; une référence épuisée disparaît de l’offre. Prix spécial simulé = 70 % du prix boutique, arrondi au dinar inférieur.
- Paliers panier simulés −10 % / −15 % / −20 % pour 1 / 2 / 3+ articles, appliqués uniquement aux produits hors offre spéciale. Les articles −30 % comptent dans le nombre d’articles mais ne reçoivent pas de seconde remise (non cumulable).
- Les cartes produit affichent le montant économisé en TND, pas un pourcentage.
- Routines (packs) : un pack n’est affiché que si toutes ses références sont en stock ; sinon il est entièrement masqué.
- Désactive toute l’expérience si le snapshot a plus de 30 minutes ou s’il est incohérent. Une erreur de source ne republie pas de valeurs anciennes comme si elles étaient fraîches.

## Limites de sécurité

- Aucun appel de mutation au site, aucune commande, aucun paiement, aucun formulaire client, aucun email/SMS/WhatsApp.
- Les prix et stocks sont un instantané public horodaté, pas une réservation ni une promesse de disponibilité au moment d’un achat.
- Le pop-up présenté sur une capture de la page d’accueil est une maquette ; il n’est pas injecté dans la boutique réelle.
- Les prix promotionnels sont des calculs de démonstration ; la préproduction ne rend aucune remise active sur la boutique.
- Pas de coûts d’achat, marges, données de vente ni PII dans ce dépôt.

## Tests

`python3 collect_catalogue.py && python3 build_site.py`, servir `site/` sur `127.0.0.1:8091`, puis `python3 test_preview.py` (Chromium) : sélection ∩ stock, prix spécial, non-cumul, masquage des packs en rupture, fail-closed, absence d’appel API, responsive 360/375/390/768 px.

## Publication

Toute modification sur `main` est publiée automatiquement par le workflow (auto-relance toutes les 10 min, cron 15 min en secours) tant que la variable `BF_PAGES_LIVE` vaut `true`. Les évolutions passent donc par une branche de revue et ne sont fusionnées sur `main` qu’après approbation du SHA exact.
