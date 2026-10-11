# Diagnostic — modèle BTTS (modèle 7) et surconfiance des probabilités > 80 %

**Date** : 2026-10-11. **Branche** : `claude/analyse-matchs-football-796va6`. **Point de
départ vérifié** : commit `a8e5089` (confirmé par `git log` avant toute modification, working
tree propre, 649/649 tests passés). **Commit portant ce diagnostic** : `040f70f`.

Script : `scripts/audit_historique/diagnostic_btts_calibration.py` (lecture seule, réutilise
`moteur.backtest.generer_lignes` et `moteur.calibration` sans les modifier). Données : les 7 097
matchs réels des 20 combinaisons championnat×saison déjà backfillées (`docs/audit_moteur_20_
combinaisons.md`), 426 424 lignes brutes générées pour cette analyse.

## 1. Définitions vérifiées (lues dans le code, jamais déduites du nom)

- **Modèle 7 (BTTS)** (`moteur/modeles/registre.py`/`marches.py`) : `gagne` si
  `(home_buts>0 ET away_buts>0) == (selection=='oui')`, sinon `perdu`. Label et vérification
  utilisent EXACTEMENT la même fonction (`issue_buts`) — pas de double implémentation possible.
- **Modèle 3 (Handicap/DNB)**, pris comme référence : `dnb` = remboursé sur match nul ;
  `handicap` = marge + ligne, avec la correction de signe du 09/10/2026 déjà en place pour la
  sélection "2". **Les deux modèles partagent la MÊME estimation de buts attendus**
  (`buts_attendus` → une seule matrice de scores Poisson/Dixon-Coles par match) — toute
  différence de performance vient de la façon dont chacun LIT cette même matrice, pas d'une
  estimation différente des forces des équipes.

## 2. Diagnostic BTTS — au-delà du seul Brier Score global

| Mesure | Modèle 7 (BTTS) | Modèle 3 (Handicap/DNB, référence) |
|---|---|---|
| n (prédictions binaires, mêmes matchs) | 12 226 | 48 904 |
| Taux réel de BTTS "oui" (équilibre des labels) | 54,59 % | — |
| Brier | 0.2517 | 0.1748 |
| Log loss | 0.6973 | 0.5247 |
| **Brier Skill Score vs. constante 0,5** | **-0,0068** | **+0,3010** |
| **Corrélation (proba brute, issue réelle)** | **+0,0725** | **+0,5487** |

**Lecture, sans décider sur le seul Brier global** :
- L'équilibre des labels est normal (54,6 % de BTTS réel, pas d'artefact de déséquilibre de
  classe qui fausserait le Brier).
- Le **Brier Skill Score négatif** signifie que le modèle BTTS fait **littéralement moins bien
  qu'annoncer 50 % pour tous les matchs** — un signal invisible sur le seul Brier global
  (0.2517, proche de 0.25 mais pas évidemment "mauvais" sans ce calcul).
- La **corrélation quasi nulle (+0,07)** entre la probabilité annoncée et le résultat réel est
  la preuve la plus directe : contrairement au modèle 3 (+0,55, fort pouvoir discriminant), le
  modèle BTTS ne distingue presque pas les matchs où les deux équipes marquent de ceux où ce
  n'est pas le cas — alors même qu'il dispose de la même estimation de buts attendus par équipe.
- **Confirmation croisée avec la production réelle** : `bet_agent/analyser_et_envoyer.py`
  documente déjà (03/10/2026) BTTS comme "mal calibré dans TOUTES les tranches, ROI -21%" sur
  35 paris réels. Ce diagnostic, sur un échantillon ~340× plus grand (12 226 prédictions) et un
  moteur entièrement différent (`moteur/`, pas `bet_agent/`), confirme indépendamment la même
  conclusion par une méthode différente (corrélation/skill score, pas un ROI observé).

### Par championnat/saison (modèle 7 seul)

Brier entre 0.2328 (Premier League 2023/2024) et 0.2642 (Serie A 2024/2025) — **stable et
systématiquement mauvais partout**, pas un problème localisé à une ligue ou une saison.

## 3. Hypothèse `rho_dixon_coles` — testée, puis RÉFUTÉE par les données

**Hypothèse initiale, raisonnable mais non vérifiée au départ** : `rho_dixon_coles` vaut `0.0`
par défaut dans tout le dépôt (jamais estimé, voir `moteur/config.py`, commentaire "à estimer
par backtest" jamais suivi), et la correction Dixon-Coles qu'il contrôle ajuste précisément les
4 cellules de score faible (0-0, 1-0, 0-1, 1-1) qui déterminent BTTS plus que tout autre marché
— une cause mécanique plausible.

**Test réel effectué** (jamais supposé vrai sans preuve) : grille `rho ∈ {0, -0,05, -0,10,
-0,15, -0,20}`, recalcul complet des 426 424 lignes à chaque valeur :

| rho | BTTS Brier | BTTS Log loss | Handicap Brier |
|---|---|---|---|
| 0.00 (défaut actuel) | 0.2517 | 0.6973 | 0.1748 |
| -0.05 | 0.2513 | 0.6965 | 0.1748 |
| -0.10 | 0.2510 | 0.6959 | 0.1748 |
| -0.15 | 0.2508 | 0.6954 | 0.1748 |
| -0.20 | 0.2506 | 0.6950 | 0.1749 |

**Conclusion : l'hypothèse est RÉFUTÉE.** Même à rho=-0,20 (au-delà des valeurs typiques
-0,05 à -0,13 de la littérature Dixon-Coles), le Brier de BTTS s'améliore de seulement 0,0011 —
négligeable face à l'écart de 0,077 avec le modèle de référence. **Le problème n'est pas un
paramètre non calibré, c'est l'absence de pouvoir discriminant du signal lui-même** (voir la
corrélation ci-dessus). Aucun changement de `rho_dixon_coles` n'est proposé.

## 4. Calibration aux tranches > 80 % — protocole chronologique strict

**Découpage** (jamais de fuite : train = 60 % le plus ancien, validation = 20 % suivant, test =
20 % le plus récent, **jamais utilisé pour ajuster quoi que ce soit**) :

| Ensemble | n | Période |
|---|---|---|
| Train | 248 518 | jusqu'au 2024-12-30 |
| Validation | 82 840 | 2024-12-30 → 2025-11-09 |
| Test | 82 840 | 2025-11-09 → 2026-05-24 |

Calibrateur isotone (déjà en production, `moteur.calibration.Calibrateur`, non modifié) et un
nouveau calibrateur Platt (régression logistique sur `logit(proba_brute)`, même granularité
modèle/marché) **ajustés UNE SEULE FOIS sur train**, jamais réajustés sur validation/test.

### Résultat sur TEST (jamais touché pendant l'ajustement)

| Méthode | Global Brier | Global Log loss | n (brut ≥80%) | Proba annoncée moy. | Fréquence réelle | Brier (≥80%) |
|---|---|---|---|---|---|---|
| RAW (sans calibration) | 0.2198 | 0.6290 | 3 963 | 86,45 % | 84,08 % | 0.1318 |
| **ISOTONE (déjà en production)** | 0.2185 | 0.6260 | 4 241 | 85,51 % | 85,45 % | 0.1220 |
| PLATT (nouveau, comparatif) | 0.2184 | 0.6254 | 3 771 | 86,20 % | 85,79 % | 0.1194 |

**Détail par sous-tranche (test, calibration isotone)** :

| Sous-tranche (proba brute) | n | RAW proba/réel | ISOTONE proba/réel |
|---|---|---|---|
| 80-90 % | 2 986 | 84,23 % / 81,68 % | 82,36 % / 81,68 % |
| 90-100 % | 977 | 93,21 % / 91,40 % | 91,55 % / 91,40 % |

**Lecture honnête, pas une conclusion forcée** :
- La surconfiance brute (RAW) à ≥80 % existe réellement mais est **plus modeste** sur ce
  découpage propre (train large, test le plus mûr chronologiquement) que sur l'agrégat du
  rapport précédent (`docs/audit_moteur_20_combinaisons.md`, -5 à -10 points) — explication
  probable : cet agrégat précédent mélangeait les tout premiers mois du walk-forward (où
  `calibrer_walk_forward` n'a encore aucun historique pour calibrer, donc la probabilité brute
  reste non corrigée) avec des mois plus tardifs mieux calibrés. Ce découpage-ci isole la
  performance en RÉGIME ÉTABLI (le calibrateur dispose déjà de 60 % d'historique).
- **L'isotone déjà en production RÉDUIT bien la surconfiance** (85,51 % annoncé vs 85,45 %
  réel sur le test — quasi parfait) — la calibration existante fonctionne comme prévu une fois
  qu'elle dispose de suffisamment d'historique.
- **Platt fait légèrement mieux qu'isotone** sur ce test précis (Brier 0.1194 vs 0.1220, soit
  -2,1 % relatif) et aussi en validation (0.1231 vs 0.1307). C'est une amélioration **réelle et
  mesurée deux fois** (validation ET test), mais **modeste et sur un seul découpage** —
  **jamais cross-validée sur plusieurs découpages/périodes**, donc non qualifiable de
  "robuste" au sens strict demandé par la mission.

## 5. Décision — conformément à l'instruction de la mission

> "Si aucune amélioration robuste n'est démontrée, conserve le modèle actuel et explique
> pourquoi."

**Décision : le modèle de calibration actuel (isotone, walk-forward) est conservé sans
changement.** Justification :
- L'amélioration mesurée de Platt (-2 à -6 % de Brier relatif selon l'ensemble) est réelle mais
  **petite et mesurée sur un seul découpage temporel** — un second découpage, une autre saison
  de test, ou un sous-ensemble différent de marchés pourrait inverser ce petit écart.
- L'isotone déjà en place **atteint déjà une calibration quasi parfaite** sur le test
  (85,51 % vs 85,45 %) — il n'y a pas de problème résiduel urgent à corriger par un changement
  de méthode.
- Remplacer une méthode déjà fonctionnelle par un gain marginal et non confirmé serait un risque
  disproportionné par rapport au bénéfice.

**BTTS (modèle 7)** : **n'est PAS supprimé ni remplacé** (conforme à l'instruction de ne jamais
décider sur le seul Brier). Le diagnostic montre que son défaut n'est pas un bug de calcul (code
vérifié correct), ni un paramètre non calibré (rho testé et réfuté), mais une limite de **pouvoir
prédictif intrinsèque** de l'approche Poisson/Dixon-Coles pour ce marché précis. C'est cohérent
avec le fait que la production (`bet_agent`) exclut déjà BTTS par défaut
(`CATEGORIES_EXCLUES`) depuis le 03/10/2026 — **aucun changement de code n'est nécessaire ici**,
la limite est déjà correctement contournée en production. Recommandation pour un travail futur
(non fait ici) : un modèle dédié à BTTS (ex. régression logistique directe sur les forces
d'attaque/défense, plutôt que dérivé de la matrice de buts) pourrait apporter un vrai pouvoir
discriminant — hors périmètre de cette mission de diagnostic.

## 6. Tests ajoutés

`tests/test_diagnostic_btts_calibration.py` (10 tests, données synthétiques) :
- `correlation`/`brier_skill_score` : comportement sur cas limites (corrélation parfaite,
  variance nulle, liste vide ; skill score négatif détecté, prédiction parfaite = 1.0).
- **Anti-fuite temporelle** (explicitement demandé) : `decouper_chronologique` ne laisse jamais
  une date de `train` dépasser la plus ancienne date de `validation` (vérifié même quand les
  lignes d'entrée sont mélangées avant tri — la fonction retrie elle-même, ne fait jamais
  confiance à l'ordre reçu).
- **Non-régression** : `ajuster_isotone`/`appliquer_isotone` corrigent bien une surconfiance
  synthétique connue (reproduit le test déjà existant `moteur/tests/test_moteur.py::
  test_isotone_monotone_et_corrige_une_surconfiance`, à cette nouvelle couche) ; un échantillon
  insuffisant renvoie la probabilité brute inchangée (jamais une calibration inventée) ; falsifier
  les labels de la cible APRÈS l'ajustement du calibrateur ne change jamais le résultat déjà
  calculé (preuve que l'ajustement ne relit jamais la cible).

**Suite complète : 659/659 tests passés** (649 avant cette mission + 10 nouveaux), 0 régression.

## 7. Limites assumées

- Le découpage 60/20/20 est un seul découpage chronologique, pas une validation croisée
  multi-période — la petite avance de Platt sur isotone n'est donc pas qualifiée de "robuste".
- Aucune cote historique n'existe encore (voir `docs/plan_importation.md`) : ce diagnostic porte
  uniquement sur la qualité probabiliste (Brier/log loss/calibration/corrélation), jamais sur un
  ROI, conformément à l'instruction de la mission.
- `POIDS_MARCHE` reste à 0,65 par défaut, non touché par ce diagnostic (il concerne
  `bet_agent/analyser_et_envoyer.py`, pas `moteur/`, les deux systèmes restant non fusionnés).
