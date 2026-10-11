# Matrice de couverture historique — 5 championnats prioritaires

**Source unique de vérité** : table Supabase `hist_matchs` (seule table avec une notion de
saison), interrogée en lecture seule le 2026-10-11. Compétitions identifiées par
`competition_id` API-Football : Premier League=39, La Liga=140, Serie A=135, Bundesliga=78,
Ligue 1=61 (identifiants API-Football standards, utilisés par `.github/workflows/backfill-
historique.yml`).

**Règle appliquée** : si une ligne de ce tableau n'a pas pu être vérifiée par une requête réelle,
elle est marquée `NON COLLECTÉ` — aucune valeur n'est estimée ou inventée.

## Tableau par championnat × saison

| Championnat | Saison | Matchs attendus | Matchs importés | Terminés avec score | Avec bloc stats | xG | Cotes pré-match horodatées |
|---|---|---|---|---|---|---|---|
| Premier League | 2025/2026 | ~380 (non vérifié) | **0** | — | — | — | — |
| Premier League | 2024/2025 | 380 | **380** | 380 (100%) | 380 non vide / ~300 champs remplis (79%) | **0/380 (0%)** | 0 (aucune) |
| Premier League | 2023/2024 | 380 | **380** | 380 (100%) | 380 non vide / ~300 champs remplis (79%) | **0/380 (0%)** | 0 (aucune) |
| Premier League | ≤2022/2023 | — | **0** | — | — | — | — |
| La Liga | toutes saisons | — | **0** | — | — | — | — |
| Serie A | toutes saisons | — | **0** | — | — | — | — |
| Bundesliga | toutes saisons | — | **0** | — | — | — | — |
| Ligue 1 | toutes saisons | — | **0** | — | — | — | — |

« Matchs attendus » = 380 pour une saison complète à 20 équipes (format Premier League/Bundesliga
2024+/Ligue 1/Serie A/La Liga), donné ici seulement pour les 2 saisons déjà backfillées, à titre
de référence de complétude (380/380 = aucun match manquant détecté pour ces 2 saisons-là). Pour
toute ligne où 0 match n'est importé, aucune hypothèse de volume n'est avancée.

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

## Les 4 championnats manquants (La Liga, Serie A, Bundesliga, Ligue 1) — toutes saisons

**Couverture actuelle : 0 match, 0 statistique, 0 cote, pour les 5 championnats × 2025/2026 et
pour les 4 championnats autres que Premier League sur toute période.** Aucune ligne de ce rapport
ne doit être lue comme une estimation — c'est un constat d'absence totale de données vérifiée
directement sur `hist_matchs` (`WHERE competition_id IN (140,135,78,61)` → 0 ligne).

Ce qui EXISTE en revanche pour ces championnats, mais n'est PAS un historique de saison :
quelques dizaines de matchs du JOUR dans la table `matchs` (production, fenêtre du
26/09 au 10/10/2026) : Bundesliga 24, Ligue 1 16, Serie A 6, La Liga 2 — voir
`docs/audit_bases_donnees.md` §2.2. Ce ne sont pas des matchs historiques exploitables pour un
backtest multi-saison (pas de notion de saison, cotes non horodatées, échantillon de 2 semaines).

## Conclusion de la matrice

Sur les 5 championnats × ≥4 saisons demandés (20 combinaisons minimum), **seules 2 combinaisons
sur 20 ont des données réelles** (Premier League 2023/2024 et 2024/2025), et même celles-ci sont
incomplètes sur les statistiques détaillées (~79%) et totalement absentes sur les cotes
historiques horodatées et le xG. La saison prioritaire 2025/2026 n'est couverte pour AUCUN des 5
championnats.
