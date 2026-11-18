# Black Friday 2026 — préproduction K-Beauty Tunisia

Projet distinct du dépôt du site de production. URL GitHub Pages : `https://k-beautytunisia.github.io/blackfriday-2026/` (avec le tiret de `k-beautytunisia`).

## Ce que fait la préproduction

- Lit en lecture seule le catalogue public de `https://kbeauty-tunisia.com/api/trpc/shop.getProducts`.
- Reconstruit les produits, images, prix et disponibilités explicitement en stock toutes les 15 minutes via GitHub Actions; l’horodatage est visible sur la page.
- N’affiche que les fiches actives avec un statut public `in_stock` et une quantité publique strictement positive.
- Désactive toute l’expérience si le snapshot a plus de 30 minutes ou s’il est incomplet. Une erreur de source ne republie pas de valeurs anciennes comme si elles étaient fraîches.
- Simule le parcours d’accueil, le pop-up puis l’univers Black Friday, ainsi que les paliers proposés −10 % / −15 % / −20 %.

## Limites de sécurité

- Aucun appel de mutation au site, aucune commande, aucun paiement, aucun formulaire client, aucun email/SMS/WhatsApp.
- Les prix et stocks sont un instantané public horodaté, pas une réservation ni une promesse de disponibilité au moment d’un achat.
- Le popup présenté sur une capture de la page d’accueil est une maquette; il n’est pas injecté dans la boutique réelle.
- Les prix promotionnels sont des calculs de démonstration; la préproduction ne rend aucune remise active.
- Pas de coûts d’achat, marges, données de vente ni PII dans ce dépôt.

## Publication

Le dépôt doit être séparé du dépôt privé de production, rendu public uniquement après approbation de son contenu exact, puis GitHub Pages doit utiliser le workflow Actions. Le déploiement publie seulement `site/`.
