# ADR 004 : Garder les lignes anormales et les marquer

**Statut :** accepté
**Date :** 7 novembre 2026

## Contexte

L'exploration (`ingestion/01_exploration_olist.ipynb`) a trouvé des incohérences de dates dans `orders` (99 441 commandes) :

| Règle | Anomalie | Lignes |
|---|---|---|
| R01 | `delivered` sans date de livraison client | 8 |
| R02 | `delivered` sans date d'approbation | 14 |
| R03 | `delivered` sans date de remise au transporteur | 2 |
| R04 | `canceled` avec une date de livraison | 6 |
| R05 | Remise au transporteur avant l'achat | 166 |
| R06 | Remise au transporteur avant l'approbation | 1 359 |
| R08 | Livraison client avant l'approbation | 61 |
| R09 | Livraison client avant la remise au transporteur | 23 |

Parmi les 1 359 cas de R06, 679 ont un écart de 0 jour et 485 de 1 jour, avec une médiane de 17 heures : ce sont surtout de petits décalages d'horodatage. Un cas extrême atteint 171 jours.

Ce sont de vraies commandes, avec des articles et un chiffre d'affaires (1 350 des 1 359 cas de R06 sont livrées). Rien ne permet de savoir quelle date est la bonne.

D'autres anomalies existent dans les autres tables : 789 `review_id` en double (814 lignes en trop), 610 produits sans catégorie, 2 catégories sans traduction (13 produits), 1 commande sans paiement et 380 écarts entre le total des articles et le total payé.

## Décision

Aucune ligne n'est supprimée ni corrigée dans Silver. Chaque anomalie reçoit un **indicateur booléen** :
- `silver_orders` porte 8 indicateurs `flag_r01_…` à `flag_r09_…` (R07 n'existe pas encore : le seuil de durée extrême reste à fixer) ;
- `silver_products` porte `flag_category_missing` et ses indicateurs voisins ;
- `fact_orders` (Gold) résume les 8 indicateurs de dates dans `has_date_anomaly`.

Pour chaque table, le nombre de lignes de Silver est comparé à celui de Bronze.

**Alternatives écartées :**
- **Supprimer les lignes anormales** : cela retirerait de vraies ventes et fausserait le chiffre d'affaires.
- **Corriger les dates** : aucune règle ne permet de choisir la date juste, toute correction serait une invention.

## Conséquences

- Le chiffre d'affaires et le nombre de commandes restent justes, et chaque anomalie est mesurable.
- La traçabilité est conservée : on peut toujours remonter à la ligne d'origine.
- Chaque analyse doit décider si elle filtre les lignes marquées. Ce choix est explicite, il n'est plus caché dans le pipeline.
- Les indicateurs ne doivent pas faire échouer le pipeline : ils sont contrôlés en avertissement, pas en erreur.
