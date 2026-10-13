# Audit B — `hist_cotes` : schéma, couverture, doublons, horodatages, provenance

**Date** : 2026-10-11. **Méthode** : requêtes `SELECT` en lecture seule sur Supabase (projet
`fpwsitpdkruoknwmgjzr`). **Aucune cote inventée, aucune écriture en production.**

## 1. Schéma réel (vérifié via `information_schema`, migrations déjà documentées ailleurs)

Table de capture PROSPECTIVE (pas un historique rétroactif) : à chaque run réel,
`capture_historique.capturer_predictions` enregistre chaque candidat (match, marché, ligne,
sélection, cote, probabilité) vu par `bet_agent` au moment exact de la prédiction.
Clé unique réelle : `(jour, fixture_id_oddspapi, marche, ligne, selection)` — premier vu,
jamais écrasé (`ON CONFLICT DO NOTHING`). Deux colonnes mortes confirmées (`match_id`,
`bookmaker`, jamais écrites par le code actuel, déjà documenté dans `models_historique.py`).

## 2. Couverture temporelle réelle

| Mesure | Valeur réelle |
|---|---|
| Lignes totales | 14 427 |
| Lignes jugées (`resultat` rempli) | **0** |
| Nombre de runs ayant capturé | 3 |
| Première capture | 2026-10-10 11:30:09 UTC |
| Dernière capture | 2026-10-10 11:46:49 UTC |
| **Étendue réelle** | **un seul jour, une fenêtre de 16 minutes** |
| Compétitions distinctes capturées | 11 |

**La capture ne couvre qu'une seule journée pour l'instant** — c'est un mécanisme PROSPECTIF
démarré le 10/10/2026, pas un historique rétroactif. Il ne pourra jamais couvrir les saisons
2022-2025 déjà backfillées dans `hist_matchs` (aucune cote n'existait pour ces matchs au moment
de leur coup d'envoi, et aucune ne peut être reconstituée après coup sans l'inventer).

## 3. Doublons — vérifiés, aucun trouvé

```sql
select jour, fixture_id_oddspapi, marche, ligne, selection, count(*)
from hist_cotes group by 1,2,3,4,5 having count(*) > 1;
-- 0 ligne
```
0 doublon sur la clé unique réelle. Cohérence `jour = date(horodatage)` vérifiée sur les
14 427 lignes (0 écart). Aucune cote nulle ou ≤ 1.0 (0 valeur invalide).

## 4. Horodatages — la propriété la plus importante pour un futur backtest ROI

| Mesure | Valeur réelle |
|---|---|
| Lignes où le coup d'envoi est AVANT l'horodatage de capture (fuite potentielle) | **0** |
| Écart minimum capture → coup d'envoi | 13 min 14 s |
| Écart maximum capture → coup d'envoi | 7 h 13 min |
| Écart moyen | ≈ 2 h 56 min |
| Lignes capturées à moins d'1 h du coup d'envoi | 385 |
| Lignes capturées à plus de 24 h du coup d'envoi | 0 |

**Résultat rassurant et vérifié** : sur les 14 427 lignes, **aucune n'a de coup d'envoi
antérieur à sa capture** — chaque cote enregistrée est bien une cote PRÉ-match au sens strict,
jamais une cote relevée après coup. C'est la propriété indispensable pour qu'un futur backtest
ROI sur ces données ne souffre d'aucune fuite temporelle — **déjà garantie par construction**,
pas seulement supposée.

## 5. Provenance

Une seule source, un seul bookmaker : **OddsPapi → 1xBet** (`collecte_donnees.py`,
`params_odds = {..., "bookmakers": "1xbet", ...}`), exactement le même flux que celui utilisé
pour construire le coupon réel envoyé sur Telegram — pas une source indépendante. Conséquences :
- **Un seul relevé par candidat et par jour** (contrainte d'unicité "premier vu") : pas de série
  temporelle de l'évolution de la cote avant le coup d'envoi, seulement un instantané.
- **Biais mono-bookmaker** : toute analyse de marge/edge reflète la tarification de 1xBet
  spécifiquement, jamais une moyenne de marché ni une comparaison inter-bookmakers.
- Champs manquants réels : `fixture_id_api_football`/`competition_id` absents sur 2 022/14 427
  lignes (≈14 %) — matchs dont l'identité API-Football n'a pas pu être résolue à la capture
  (cohérent avec les limites déjà documentées dans `plan_importation.md`).

## 6. Un backtest de ROI fiable est-il possible aujourd'hui ?

**Non, pas encore — pour deux raisons indépendantes, toutes deux vérifiées, aucune supposée :**

1. **Aucune ligne n'est jugée** (`resultat` à `NULL` partout) : la fonction qui ferait ce travail
   (`capture_historique.juger_cotes_en_attente`) existe dans le code mais **n'est câblée à
   aucune commande `app.taches` ni à aucun workflow GitHub Actions** (vérifié par recherche
   exhaustive) — déjà signalé dans `docs/plan_final_bilan_pret_production.md` comme tâche
   ouverte, confirmé ici avec le détail des données.
2. **Un seul jour de capture** : même une fois jugées, 14 427 lignes d'un seul jour ne
   permettent qu'une mesure extrêmement bruitée (un seul tirage de la météo sportive du jour),
   pas une estimation de ROI statistiquement significative. Il faudrait des semaines
   d'accumulation continue avant qu'une telle mesure ait un sens.

**Ce qui EST déjà garanti, et ne nécessite aucune correction** : la qualité structurelle des
données (0 doublon, 0 fuite temporelle, horodatages cohérents) — le mécanisme de capture
lui-même fonctionne correctement, il manque seulement (a) le jugement différé et (b) le temps
d'accumulation.

## 7. Portée de cet audit

Lecture seule exclusivement (`SELECT`), aucune ligne de `hist_cotes` modifiée, aucune cote
inventée pour compléter un vide, aucun fichier de production modifié.
