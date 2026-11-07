# Correction des 250 heures — résumé du CSV (aucune écriture en base)

Fichier détaillé : `rapports/phase3/corrections_heures_250.csv` (match, ancienne valeur NULL, nouvelle valeur UTC, match source, run source, niveau de confiance). Ordres SQL préparés, tous en transaction annulée par défaut : `05_..._250_...sql` (les 250) et `05b_..._180_confiance_forte.sql` (les 180 les plus sûrs).

## Principe

Un match sans heure reçoit l'heure d'un match identique (mêmes équipes, même sens domicile/extérieur) d'un autre run, ayant une heure connue, située entre 1 jour avant et 4 jours après le lancement du run à corriger. Un match n'est proposé que si **toutes** les sources candidates donnent exactement la même heure.

## Chiffres

| | |
|---|---|
| Matchs sans heure | 778 |
| Corrections proposées | **250** (dans 33 runs) |
| Ambiguïtés (plusieurs heures candidates) | **0** (ces cas sont exclus, aucun n'est proposé) |
| Sans solution, **non touchés** | **528** |
| Matchs corrigés ayant des jambes | 143 (aucune jambe en attente : tous déjà jugés) |
| Cas où plusieurs matchs sources donnent la même heure | 172 (consensus, pas une ambiguïté) |

## Sources utilisées (run d'origine de l'heure)

Run 2 : 158 corrections · run 29 : 51 · run 34 : 23 · run 54 : 8 · run 63 : 6 · run 255 : 4.
Tous les matchs sources ont un identifiant de fixture (oddspapi ou API-Football).

## Niveau de confiance de la correspondance

| Niveau | Nombre | Critère |
|---|---|---|
| **forte** | **180** | même fixture oddspapi (155) ou même fixture API-Football (25 de plus, malgré un identifiant oddspapi différent) |
| **moyenne** | **45** | mêmes équipes, mais identifiant oddspapi différent entre les deux runs et aucune fixture API-Football commune |
| **faible** | **25** | le match à corriger n'a aucun identifiant de fixture : correspondance sur les noms d'équipes seulement (runs 17 : 9 matchs, 22 : 9, 32 : 3, et 247, 250, 251, 254 : 1 chacun) |

Aucune correspondance n'entre en contradiction (aucune fixture API-Football différente entre la cible et sa source).

## Points d'attention

1. **41 corrections donnent une heure antérieure au lancement du run** (jusqu'à 5 h avant) : le run a donc été lancé après le coup d'envoi. C'est cohérent (les runs prennent aussi des matchs du jour déjà commencés), mais à garder en tête. L'écart heure − lancement est de −5 h à +36 h, médiane +5 h.
2. **Aucun impact sur les résultats déjà jugés** : les matchs corrigés n'ont plus de jambe en attente. L'heure ne sert ici qu'à rendre l'historique cohérent (plans de vérification et analyses d'heures de coup d'envoi).
3. **Recommandation** : appliquer d'abord les **180 de confiance forte** (`05b`), puis décider des 45 « moyenne » et 25 « faible » après relecture. Les 528 autres matchs ne sont pas concernés.
