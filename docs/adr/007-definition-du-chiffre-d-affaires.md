# ADR 007 : Définition du chiffre d'affaires et des ventes

**Statut :** provisoire (à figer avant la publication finale)
**Date :** 7 novembre 2026

## Contexte

« Chiffre d'affaires » peut vouloir dire plusieurs choses. Trois questions se posent : compte-t-on le prix seul ou le prix et les frais de port, quels statuts de commande inclut-on, et à quelle date rattache-t-on le chiffre ?

Les données donnent deux totaux :

| Définition | Montant |
|---|---|
| Tous les articles (prix) | 13 591 643,70 |
| Ventes seules (hors `canceled` et `unavailable`) | 13 494 400,74 |
| Écart | 97 242,96 |

Le port dépasse le prix sur 4 124 lignes (environ 3,7 %) et vaut 0 sur 383 lignes. Les 380 écarts entre le total des articles et le total payé ne sont pas expliqués.

## Décision

- **Chiffre d'affaires = somme de `price`** (hors frais de port), colonne `product_revenue`. Le port est suivi à part (`freight_total`), et `order_total` vaut prix plus port.
- **Une vente est une commande dont le statut n'est ni `canceled` ni `unavailable`** (`is_sale`). Les indicateurs utilisent les ventes ; `kpi_monthly_revenue` ajoute la condition `item_count > 0`.
- **Date de rattachement : la date d'achat** (`order_purchase_timestamp`), exposée en `order_date` et `order_month`.
- **Source : `order_items`**, pas `order_payments`. Les écarts de paiement n'affectent donc pas le chiffre d'affaires.

**Alternatives écartées :**
- **Prix plus port** : le port n'est pas un revenu de produit et fausserait le chiffre par catégorie.
- **Date de livraison** : elle exclurait les commandes non encore livrées et décalerait les mois.
- **Total payé** : il contient des bons d'achat, des écarts et 9 paiements à 0.

## Conséquences

- Deux chiffres coexistent : il faut toujours préciser « tous articles » (13 591 643,70) ou « ventes » (13 494 400,74). Les indicateurs par mois et par catégorie sont égaux à 13 494 400,74.
- Les commandes dans un statut intermédiaire (par exemple `shipped` ou `invoiced`) comptent comme des ventes. Si on veut se limiter aux commandes `delivered`, la définition devra changer.
- Cette définition est **provisoire** : l'ADR passera à « accepté » quand elle sera validée.
