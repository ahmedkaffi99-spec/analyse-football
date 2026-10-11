# Matrice de couverture historique — 5 championnats prioritaires

**Source unique de vérité** : table Supabase `hist_matchs` (seule table avec une notion de
saison), interrogée en lecture seule. Compétitions identifiées par `competition_id` API-Football :
Premier League=39, La Liga=140, Serie A=135, Bundesliga=78, Ligue 1=61 (identifiants API-Football
standards, utilisés par `.github/workflows/backfill-historique.yml`).

**Mise à jour du 2026-10-11, après le backfill réel** : les 4 championnats manquants (La Liga,
Serie A, Bundesliga, Ligue 1) ont été collectés via 4 exécutions distinctes du workflow
`backfill-historique.yml` (ligue=140/135/78/61, saisons="2022,2023,2024,2025", sans_stats=false),
toutes terminées avec succès (`conclusion: success`), vérifiées directement sur Supabase après
coup.

**Mise à jour complémentaire du 2026-10-11 (mission "compléter l'historique Premier League")** :
3 exécutions supplémentaires (ligue=39, saisons="2022" puis "2023,2024" puis "2025", toutes
sans_stats=false et sans `limite_appels_stats`) ont complété Premier League sur les 4 saisons
prioritaires. Les runs #6/#7/#8 ont tous réussi (`conclusion: success`, ~2-3 min chacun) et ont
aussi corrigé une couverture statistique partielle héritée du run #1 initial (07/10/2026), qui
avait vraisemblablement été borné par un `--limite-appels-stats` — les lignes 2023/2024
existaient déjà (upsert par `match_id`, aucun doublon créé) mais avec seulement ≈39,5% de
statistiques détaillées ; elles sont maintenant à 100%. Les chiffres ci-dessous viennent de
requêtes `hist_matchs` réelles exécutées après ces runs.

**Règle appliquée** : si une ligne de ce tableau n'a pas pu être vérifiée par une requête réelle,
elle est marquée `NON COLLECTÉ` — aucune valeur n'est estimée ou inventée.

## Tableau par championnat × saison

| Championnat | Saison | Matchs importés | Terminés avec score | Avec bloc stats détaillées | xG | Cotes pré-match horodatées |
|---|---|---|---|---|---|---|
| Premier League | 2025/2026 | 380 | 380 (100%) | 380 (100%, cartons 366/380=96,3%) | 0 (0%) | 0 (aucune) |
| Premier League | 2024/2025 | 380 | 380 (100%) | 380 (100%, cartons 363/380=95,5%) | 0 (0%) | 0 (aucune) |
| Premier League | 2023/2024 | 380 | 380 (100%) | 380 (100%, cartons 373/380=98,2%) | 0 (0%) | 0 (aucune) |
| Premier League | 2022/2023 | 380 | 380 (100%) | 380 (100%, cartons 364/380=95,8%) | 0 (0%) | 0 (aucune) |
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
- **Cartons jaunes, toutes ligues confondues** : seul champ statistique qui n'atteint jamais
  100% (95,5-99,7% selon la saison/la ligue) — API-Football ne renvoie pas toujours ce champ
  précis dans le bloc `statistics`, même quand tout le reste (tirs, corners, possession) est
  présent. Donnée manquante réelle, jamais complétée artificiellement.

## Détail des champs demandés — Premier League, les 4 saisons (2022/2023 à 2025/2026)

| Champ demandé | Disponible ? | Taux de couverture | Source |
|---|---|---|---|
| Dates des matchs | Oui | 1520/1520 (100%) | `hist_matchs.date` |
| Équipes domicile/extérieur (identifiants stables) | Oui | 1520/1520 (100%) | `home_id`/`away_id` = ID API-Football |
| Scores finaux | Oui | 1520/1520 (100%) | `home_score`/`away_score` |
| Résultat 1X2 | Dérivable | 100% (calcul direct depuis les scores, pas une colonne dédiée) | dérivé |
| Buts par équipe / total | Oui | 1520/1520 (100%) | dérivé des scores |
| Tirs / tirs cadrés | Oui | 1520/1520 (100%) — **complété le 2026-10-11** (était ≈39,5%) | `stats.home/away.shots*` |
| Corners | Oui | 1520/1520 (100%) — **complété le 2026-10-11** | `stats.home/away.corners` |
| Cartons (jaunes) | Quasi complet | 1466/1520 (≈96,4%) — **complété le 2026-10-11** (était ≈38,7%) | `stats.home/away.yellow_cards` |
| Possession | Oui | 1520/1520 (100%) — **complété le 2026-10-11** | `stats.home/away.possession` |
| xG | **Non** | 0/1520 (0%) | champ prévu dans le schéma, jamais rempli par la source réelle (API-Football ne le renvoie pas sur ce plan/ces fixtures) |
| Identifiant stable + correspondance API | Oui | 100% | `match_id` = fixture_id API-Football, PK |
| Cotes pré-match horodatées (bookmaker, marché) | **Non** | 0% | aucune table ne relie `hist_matchs` à une cote historique horodatée ; `hist_cotes` ne couvre que le 10/10/2026 en temps réel, jamais de cote rétroactive |
| Matchs reportés/incomplets | Vérifié : aucun | 0 détecté | tous les matchs `FT/AET/PEN` ont un score, aucune incohérence statut/score |
| Doublons | Vérifié : aucun | 0 détecté sur `(home_id, away_id, date)`, les 4 saisons confondues | requête directe |

## Statut final par saison — Premier League (mission "compléter l'historique Premier League", 2026-10-11)

| Saison | Matchs attendus/présents | Scores | Stats détaillées | Matchs sans stats | Doublons/erreurs | **Statut** |
|---|---|---|---|---|---|---|
| 2022/2023 | 380/380 | 100% | tirs/corners/possession 100%, cartons 364/380 (95,8%) | 0 | 0 / 0 | **COMPLET** |
| 2023/2024 | 380/380 | 100% | tirs/corners/possession 100%, cartons 373/380 (98,2%) | 0 | 0 / 0 | **COMPLET** |
| 2024/2025 | 380/380 | 100% | tirs/corners/possession 100%, cartons 363/380 (95,5%) | 0 | 0 / 0 | **COMPLET** |
| 2025/2026 | 380/380 | 100% | tirs/corners/possession 100%, cartons 366/380 (96,3%) | 0 | 0 / 0 | **COMPLET** |

Les 4 saisons sont classées **COMPLET** au sens de cette mission (tous les matchs présents,
scores à 100%, tirs/corners/possession à 100%) — la seule réserve est le champ cartons jaunes
(95,5-98,2%, jamais 100%), une limite réelle et documentée de la source (API-Football ne fournit
pas toujours ce champ précis), pas un défaut de collecte.

## Statut global de la matrice (mise à jour finale du 2026-10-11)

Sur les 5 championnats × 4 saisons (2022/2023 à 2025/2026), **20 combinaisons sur 20 ont
maintenant des données réelles**, Premier League étant désormais complète sur ses 4 saisons.
Couverture scores 100% partout (à l'exception du match `AWD` Ligue 1 déjà noté, par nature sans
score) ; couverture tirs/corners/possession à 100% pour les 5 championnats ; cartons jaunes
quasi complets (95,5-99,7% selon ligue/saison, jamais inventés). **xG et cotes historiques
horodatées restent à 0% partout** — ces deux blocages ne sont pas résolus par ce type de
backfill (scores/statistiques uniquement) et nécessitent une source distincte, voir
`docs/plan_importation.md`.
