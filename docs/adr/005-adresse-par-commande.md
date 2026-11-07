# ADR 005 : Garder l'adresse de livraison au niveau de la commande

**Statut :** accepté
**Date :** 7 novembre 2026

## Contexte

Dans `customers`, `customer_id` est unique et change à chaque commande : 99 441 lignes pour 99 441 commandes. L'identifiant d'une personne réelle est `customer_unique_id`, avec 96 096 valeurs distinctes.

- 93 099 personnes n'ont passé qu'une commande, 2 997 en ont passé plusieurs (jusqu'à 17).
- 252 personnes ont plus d'une localisation : 130 changent seulement de code postal, 83 de ville (dans le même État) et 39 d'État.

D'après la documentation de la source, `customers` donne le lieu de **livraison** de la commande. L'hypothèse selon laquelle une personne change de lieu de livraison d'une commande à l'autre n'est pas démontrée.

## Décision

- **`fact_orders`** (une ligne par commande) garde la localisation de livraison de **chaque commande** (par exemple `delivery_state`).
- **`dim_customers`** a une ligne par `customer_unique_id` (96 096). Elle donne la **dernière localisation de livraison connue** : celle de la commande la plus récente, départagée par `order_id` décroissant pour que le résultat soit toujours le même. Les colonnes se nomment `last_delivery_zip_prefix`, `last_delivery_city` et `last_delivery_state`, et non « adresse », pour qu'on ne la prenne pas pour un domicile.
- `fact_orders` utilise `customer_unique_id` comme clé vers `dim_customers`.

**Alternatives écartées :**
- **Une dimension au grain `customer_id`** (99 441 lignes) : elle confondrait commandes et personnes et fausserait tout comptage de clients.
- **La première adresse connue** : elle ne reflète pas la situation la plus récente.

## Conséquences

- Aucune commande n'est perdue : la somme de `order_count` dans `dim_customers` est égale à 99 441.
- Les analyses par région utilisent `fact_orders`, pas `dim_customers`.
- Pour les 39 personnes qui changent d'État, `dim_customers` ne garde que la dernière localisation. Le pourquoi de ces changements reste une question ouverte, signalée par un indicateur possible `has_multiple_states`.
