# Dictionnaire de données — `olist_orders_dataset.csv`
**Fichier source :** olist_orders_dataset.csv
**Une ligne =** une commande
**Clé :** `order_id` (99 441 lignes, aucun doublon)
**Liée à :**
- `customers`, par `customer_id`
- `order_items`, `order_payments` et `order_reviews`, par `order_id`

**Rôle :** table centrale du modèle : elle porte le statut et les dates du parcours de chaque commande.

## Périmètre observé

- **Nombre de lignes :** 99 441.
- **Nombre de colonnes :** 8.
- `order_id` a 99 441 valeurs distinctes et aucune valeur vide dans le profil affiché.
- Le profil affiche 99 441 valeurs distinctes pour `customer_id`, qui n'a pas non plus de valeur vide.
- Les dates sont lues comme `TIMESTAMP` par DuckDB dans le profil.

## Colonnes

| Colonne | Type observé | Valeurs vides | Valeurs distinctes | Observation |
|---|---|---:|---:|---|
| `order_id` | `VARCHAR` | 0 | 99 441 | Identifiant présent sur chaque ligne du résultat. |
| `customer_id` | `VARCHAR` | 0 | 99 441 | Identifiant présent sur chaque ligne du résultat. |
| `order_status` | `VARCHAR` | 0 | 8 | Huit statuts observés, détaillés ci-dessous. |
| `order_purchase_timestamp` | `TIMESTAMP` | 0 | 98 875 | Date d'achat. |
| `order_approved_at` | `TIMESTAMP` | 160 | 90 733 | Date d'approbation. |
| `order_delivered_carrier_date` | `TIMESTAMP` | 1 783 | 81 018 | Date de remise au transporteur. |
| `order_delivered_customer_date` | `TIMESTAMP` | 2 965 | 95 664 | Date de livraison au client. |
| `order_estimated_delivery_date` | `TIMESTAMP` | 0 | 459 | Date de livraison estimée. |

## Répartition des statuts affichée

| `order_status` | Lignes | Pourcentage affiché |
|---|---:|---:|
| `delivered` | 96 478 | 97,02 % |
| `shipped` | 1 107 | 1,11 % |
| `canceled` | 625 | 0,63 % |
| `unavailable` | 609 | 0,61 % |
| `invoiced` | 314 | 0,32 % |
| `processing` | 301 | 0,30 % |
| `created` | 5 | 0,01 % |
| `approved` | 2 | 0,00 % |

## Contrôles de qualité exécutés

Les nombres ci-dessous sont les résultats des contrôles du notebook. Des contrôles différents peuvent concerner les mêmes lignes : ne pas additionner leurs comptes.

### Valeurs manquantes selon le statut

| Contrôle | Lignes |
|---|---:|
| `delivered` sans `order_approved_at` | 14 |
| `delivered` sans `order_delivered_carrier_date` | 2 |
| `delivered` sans `order_delivered_customer_date` | 8 |
| `canceled` avec `order_delivered_customer_date` renseignée | 6 |

Le résultat affiche les 8 commandes `delivered` sans date de livraison. Leur date estimée est renseignée dans les 8 lignes affichées. **Cause de l'absence de date réelle : à vérifier.**

### Ordre chronologique des dates

| Règle testée | Lignes |
|---|---:|
| `order_approved_at` avant `order_purchase_timestamp` | 0 |
| `order_delivered_carrier_date` avant `order_purchase_timestamp` | 166 |
| `order_delivered_carrier_date` avant `order_approved_at` | 1 359 |
| `order_delivered_customer_date` avant `order_purchase_timestamp` | 0 |
| `order_delivered_customer_date` avant `order_approved_at` | 61 |
| `order_delivered_customer_date` avant `order_delivered_carrier_date` | 23 |
| `order_estimated_delivery_date` avant `order_purchase_timestamp` | 0 |

Pour les 1 359 cas où la date transporteur précède l'approbation, l'écart affiché est en moyenne de 1 484,8 minutes, avec une médiane de 1 030 minutes et un maximum de 246 555 minutes. L'exemple le plus grand affiche 171 jours d'écart. **La cause de ces écarts : à vérifier.**

Le contrôle des dates d'approbation entre le 10 et le 16 septembre 2017 affiche 213 approbations le 13 septembre et 12 cas où la date transporteur précède l'approbation ce jour-là. Cela ne démontre pas à lui seul la cause des écarts.

### Règles regroupées dans le contrôle des violations

| Règle testée | Lignes |
|---|---:|
| Date d'achat absente | 0 |
| Approbation absente pour un statut `approved`, `invoiced`, `processing`, `shipped` ou `delivered` | 14 |
| Date transporteur absente pour un statut `shipped` ou `delivered` | 2 |
| Date de livraison absente pour un statut `delivered` | 8 |
| Date d'approbation présente avec le statut `created` | 0 |
| Date transporteur présente avec le statut `created`, `approved`, `invoiced` ou `processing` | 0 |
| Date de livraison présente avec un statut différent de `delivered` | 6 |

**Causes des valeurs manquantes, des dates dans le désordre et des associations statut/date : à vérifier.** Les résultats affichés ne démontrent pas pourquoi ces cas existent.