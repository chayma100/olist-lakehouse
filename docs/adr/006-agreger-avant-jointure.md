# ADR 006 : Agréger avant de joindre

**Statut :** accepté
**Date :** 7 novembre 2026

## Contexte

Plusieurs tables ont une relation un-à-plusieurs avec les commandes :

| Table | Lignes | Commandes concernées | Maximum par commande |
|---|---|---|---|
| `order_items` | 112 650 | 98 666 | 21 articles |
| `order_payments` | 103 886 | 99 440 | 29 paiements |
| `order_reviews` | 99 224 | 98 673 | 3 avis (547 commandes ont plusieurs avis) |

Joindre directement `order_items` et `order_payments` multiplie les lignes : l'exploration a mesuré un chiffre d'affaires **gonflé de 617 471,64**.

## Décision

Toute table du côté « plusieurs » est **agrégée au grain de la commande avant** d'être jointe à une table au grain de la commande.
- `fact_orders` joint des sous-requêtes agrégées : nombre d'articles, somme des prix, somme des frais de port et total pour les articles, et **un seul avis par commande** (le plus récent, avec le nombre d'avis).
- `fact_order_items` (une ligne par article) ne se joint qu'à des tables **uniques sur leur clé** : `fact_orders` (par `order_id`) et `dim_products` (par `product_id`).
- Les paiements ne sont jamais joints au niveau de l'article.

## Conséquences

- Plus de duplication de lignes : `fact_orders` a 99 441 lignes pour 99 441 commandes distinctes, et `fact_order_items` a 112 650 lignes pour 112 650 clés `(order_id, order_item_id)` distinctes.
- Un test de réconciliation le prouve : la somme des prix est identique en Gold et en Silver (13 591 643,70).
- Les analyses qui croisent paiements et articles doivent raisonner au niveau de la commande.
- Retenir un seul avis par commande est une règle métier : elle est documentée ici et peut être revue.
