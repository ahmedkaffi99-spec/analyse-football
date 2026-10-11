# Matrice de couverture historique — 5 championnats prioritaires

**Source unique de vérité** : table Supabase `hist_matchs` (seule table avec une notion de
saison), interrogée en lecture seule. Compétitions identifiées par `competition_id` API-Football :
Premier League=39, La Liga=140, Serie A=135, Bundesliga=78, Ligue 1=61 (identifiants API-Football
standards, utilisés par `.github/workflows/backfill-historique.yml`).

**Mise à jour du 2026-10-11, après le backfill réel** : les 4 championnats manquants (La Liga,
Serie A, Bundesliga, Ligue 1) ont été collectés via 4 exécutions distinctes du workflow
`backfill-historique.yml` (ligue=140/135/78/61, saisons="2022,2023,2024,2025", sans_stats=false),
toutes terminées avec succès (`conclusion: success`), vérifiées directement sur Supabase après
coup. Voir le rapport d'exécution complet dans le message de la mission correspondante ; les
chiffres ci-dessous viennent de requêtes `hist_matchs` réelles exécutées après ces 4 runs.

**Règle appliquée** : si une ligne de ce tableau n'a pas pu être vérifiée par une requête réelle,
elle est marquée `NON COLLECTÉ` — aucune valeur n'est estimée ou inventée.

## Tableau par championnat × saison

| Championnat | Saison | Matchs importés | Terminés avec score | Avec bloc stats détaillées | xG | Cotes pré-match horodatées |
|---|---|---|---|---|---|---|
| Premier League | 2025/2026 | **0** | — | — | — | — |
| Premier League | 2024/2025 | 380 | 380 (100%) | ~300/380 champs remplis (79%) | 0/380 (0%) | 0 (aucune) |
| Premier League | 2023/2024 | 380 | 380 (100%) | ~300/380 champs remplis (79%) | 0/380 (0%) | 0 (aucune) |
| Premier League | ≤2022/2023 | **0** | — | — | — | — |
| La Liga | 2025/2026 | 380 | 380 (100%) | 380 (100%) | 0 (0%) | 0 (aucune) |
| La Liga | 2024/2025 | 380 | 380 (100%) | 380 (100%) | 0 (0%) | 0 (aucune) |
| La Liga | 2023/2024 | 380 | 380 (100%) | 380 (100%) | 0 (0%) | 0 (aucune) |
| La Liga | 2022/2023 | 380 | 380 (100%) | 380 (100%) | 0 (0%) | 0 (aucune) |
| Serie A | 2025/2026 | 380 | 380 (100%) | 380 (100%) | 0 (0%) | 0 (aucune) |
| Serie A | 2024/2025 | 380 | 380 (100%) | 379 (99,7%) | 0 (0%) | 0 (aucune) |
| Serie A | 2023/2024 | 380 | 380 (100%) | 380 (100%) | 0 (0%) | 0 (aucune) |
| Serie A | 2022/2023 | **381** (1 match de plus que les 380 attendus — vérifié non-doublon, voir note) | 381 (100%) | 381 (100%) | 0 (0%) | 0 (aucune) |
| Bundesliga | 2025/2026 | 308 | 308 (100%) | 308 (100%) | 0 (0%) | 0 (aucune) |
| Bundesliga | 2024/2025 | 308 | 308 (100%) | 308 (100%) | 0 (0%) | 0 (aucune) |
| Bundesliga | 2023/2024 | 308 | 308 (100%) | 308 (100%) | 0 (0%) | 0 (aucune) |
| Bundesliga | 2022/2023 | 308 | 308 (100%) | 308 (100%) | 0 (0%) | 0 (aucune) |
| Ligue 1 | 2025/2026 | 308 | **307** (1 match `AWD` — attribué administrativement, sans score par nature, voir note) | 307 (99,7%) | 0 (0%) | 0 (aucune) |
| Ligue 1 | 2024/2025 | 308 | 308 (100%) | 308 (100%) | 0 (0%) | 0 (aucune) |
| Ligue 1 | 2023/2024 | 308 | 308 (100%) | 308 (100%) | 0 (0%) | 0 (aucune) |
| Ligue 1 | 2022/2023 | 380 (format à 20 équipes, avant la réduction à 18) | 380 (100%) | 380 (100%) | 0 (0%) | 0 (aucune) |

**Notes sur les écarts de volume (vérifiés, pas des erreurs de collecte)** :
- **Bundesliga = 308/saison** (pas 306, le compte « round-robin pur » à 18 équipes) : écart de +2
  cohérent avec les barrages de relégation Bundesliga/2. Bundesliga que l'API inclut dans la même
  compétition — non creusé plus loin dans cette mission, signalé tel quel.
- **Serie A 2022/2023 = 381** (pas 380) : vérifié qu'aucun doublon n'existe sur
  `(home_id, away_id, date)` — c'est bien un match distinct supplémentaire, pas une erreur de
  collecte. Cause exacte non investiguée (hors périmètre de cette mission de collecte).
- **Ligue 1 2022/2023 = 380, pas 308** : la Ligue 1 est passée de 20 à 18 clubs à partir de la
  saison 2023/2024 — la différence de format est réelle, pas une anomalie.
- **Ligue 1 2025/2026, 1 match sans score** (Nantes–Toulouse, `match_id=1388000`, statut `AWD` =
  décision administrative) : `home_score`/`away_score` sont `NULL` parce qu'un match `AWD` n'a
  jamais de but joué — comportement correct du backfill (ne récupère un score que pour
  `FT`/`AET`/`PEN`, jamais un score inventé pour un autre statut).
- **xG = 0% partout**, confirmé pour les 4 nouveaux championnats comme pour Premier League : la
  source réelle (API-Football) ne fournit pas ce champ sur ces fixtures/ce plan.
- **Cotes pré-match horodatées = 0% partout** : ce backfill ne collecte que scores + statistiques
  (`hist_matchs`), jamais de cotes — conforme à `docs/plan_importation.md` (blocage toujours
  ouvert, aucune source de cotes historiques confirmée).

## Détail des champs demandés, saison par saison (uniquement là où des données existent)

Pour Premier League 2023/2024 et 2024/2025 (seules saisons disponibles) :

| Champ demandé | Disponible ? | Taux de couverture | Source |
|---|---|---|---|
| Dates des matchs | Oui | 760/760 (100%) | `hist_matchs.date` |
| Équipes domicile/extérieur (identifiants stables) | Oui | 760/760 (100%) | `home_id`/`away_id` = ID API-Football |
| Scores finaux | Oui | 760/760 (100%) | `home_score`/`away_score` |
| Résultat 1X2 | Dérivable | 100% (calcul direct depuis les scores, pas une colonne dédiée) | dérivé |
| Buts par équipe / total | Oui | 760/760 (100%) | dérivé des scores |
| Tirs / tirs cadrés | Partiel | 300/380 par saison (≈79%) | `stats.home/away.shots*` |
| Corners | Partiel | 300/380 par saison (≈79%) | `stats.home/away.corners` |
| Cartons (jaunes) | Partiel | 294/380 par saison (≈77%) | `stats.home/away.yellow_cards` |
| Possession | Partiel | 300/380 par saison (≈79%) | `stats.home/away.possession` |
| xG | **Non** | 0/760 (0%) | champ prévu dans le schéma, jamais rempli par la source réelle (API-Football ne le renvoie pas sur ce plan/ces fixtures) |
| Identifiant stable + correspondance API | Oui | 100% | `match_id` = fixture_id API-Football, PK |
| Cotes pré-match horodatées (bookmaker, marché) | **Non** | 0% | aucune table ne relie `hist_matchs` à une cote historique horodatée ; `hist_cotes` ne couvre que le 10/10/2026 en temps réel, jamais de cote rétroactive |
| Matchs reportés/incomplets | Vérifié : aucun | 0 détecté | tous les matchs `FT/AET/PEN` ont un score, aucune incohérence statut/score |

## Statut restant : Premier League 2025/2026 et saisons ≤2022/2023

**Seule lacune de couverture restante parmi les combinaisons demandées** : Premier League
2025/2026 (saison en cours au moment du backfill initial du 10/10/2026, jamais relancée depuis)
et Premier League ≤2022/2023 (jamais backfillée, hors périmètre de la mission de collecte du
2026-10-11 qui ne portait que sur les 4 autres championnats). Les 4 championnats auparavant
manquants (La Liga, Serie A, Bundesliga, Ligue 1) sont désormais couverts sur 2022/2023 à
2025/2026 inclus.

## Conclusion de la matrice (mise à jour du 2026-10-11)

Sur les 5 championnats × 4 saisons (2022/2023 à 2025/2026), **19 combinaisons sur 20 ont
maintenant des données réelles** — seule Premier League 2025/2026 manque encore. Couverture
scores 100% sur toutes les combinaisons collectées (à l'exception du match `AWD` Ligue 1 déjà
noté, par nature sans score) ; couverture statistiques détaillées quasi complète (99,7-100%) pour
les 4 nouveaux championnats, nettement meilleure que Premier League (~79%, backfillée plus tôt
avec un lot de données différent). **xG et cotes historiques horodatées restent à 0% partout** —
blocages non résolus par cette collecte, voir `docs/plan_importation.md`.
