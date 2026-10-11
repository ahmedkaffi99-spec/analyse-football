# Bascule du moteur par défaut : `moteur_central` remplace `deterministe` (11/10/2026)

**Date** : 2026-10-11. **Branche** : `claude/analyse-matchs-football-796va6`. **Aucune fusion
vers `main`, aucun déploiement, aucun envoi Telegram réel.**

## 1. Identité confirmée (pas devinée)

Le moteur le plus récemment construit dans ce dépôt est bien **`moteur_central/`** — commits du
10/10/2026 (`2f44f42`, `9074784`, `dc2b867`, `4a6a7ad`, `6edb8b1`, `a29a0ad`), postérieurs à
`moteur/` (03-09/10/2026).

**Ce que `moteur_central` EST réellement** (vérifié dans le code, pas supposé) : **pas** un
modèle de prédiction autonome. C'est une couche d'arbitrage qui :
1. Récupère le pool de candidats déjà calculé par `bet_agent` (`ae.agent3_calcul_pool_candidats`).
2. Récupère, pour les mêmes candidats, une probabilité concurrente de `moteur/` (via
   `comparaison_moteurs.comparer_candidats`, seulement quand `hist_matchs` a assez d'historique
   pour les deux équipes).
3. Arbitre PAR MARCHÉ quel moteur faire confiance (`moteur_central.choix_moteur`, sur le ROI
   réel mesuré dans `hist_cotes` **jugé**) — garde les deux candidats quand la décision est
   "indisponible"/"égalité" (jamais un choix arbitraire sans donnée).
4. Compose un coupon unique (2 à 5 jambes, probabilité maximale) à partir du pool résultant
   (`moteur_central.selection.selectionner`).

**Point d'entrée réel de production, désormais** : `backend/app/services/moteur_central_run.py:
executer_moteur_central()`, appelé depuis `runs.py:executer_run()` quand `moteur="central"`
(nouveau défaut de cette fonction, et de `--moteur` dans `app.taches`/`pipeline-quotidien.yml`).
L'ancien point d'entrée shadow (`decision_centrale.calculer_et_journaliser_shadow`, derrière
`MOTEUR_CENTRAL_SHADOW`) reste inchangé et continue de ne jamais piloter le coupon réel — les
deux chemins coexistent, jamais appelés en même temps pour le même run.

## 2. Ce qui a été changé

| Fichier | Changement |
|---|---|
| `backend/app/services/moteur_central_run.py` (nouveau) | Exécution RÉELLE de `moteur_central/` : pool bet_agent + comparaison moteur/ → arbitrage → sélection → rejointure vers le format bet_agent complet (voir §3) |
| `backend/app/services/runs.py` | `executer_run(..., moteur="central")` — nouveau défaut (était `"deterministe"`). Branche `moteur == "central"` : AUCUN repli vers un autre moteur ; une exception de `executer_moteur_central` remonte telle quelle jusqu'au bloc `except` existant (run → statut `"erreur"`, détail explicite) |
| `backend/app/taches.py` | `--moteur` : nouveau choix `"central"`, nouveau défaut `"central"` (était `"deterministe"`) |
| `.github/workflows/pipeline-quotidien.yml` | `workflow_dispatch.moteur` : nouvelle option/défaut `"central"` |
| `backend/app/routers/runs.py` | **Hors périmètre, explicitement préservé** : l'API HTTP (`POST /api/runs`) passe désormais `moteur="deterministe"` explicitement — cette route reste inchangée, la mission ne portait que sur le workflow quotidien (`pipeline-quotidien.yml`/`app.taches run`) |
| `backend/tests/test_runs.py` | 4 appels `executer_run(...)` fixent désormais `moteur="deterministe"` explicitement (ils testaient ce chemin précis, ne doivent pas suivre le nouveau défaut) |
| `backend/tests/test_runs_moteur_central.py` (nouveau) | 5 tests dédiés (voir §4) |

**Conservé sans changement** : `bet_agent/analyser_et_envoyer.py` (moteur "deterministe"),
`bet_agent/agent_pilote.py` (moteur "agent"), `moteur/` — tous les anciens moteurs restent dans
le dépôt et sélectionnables explicitement (`--moteur deterministe`, `--moteur agent`).

## 3. Compatibilité des entrées/sorties — vérifiée, pas supposée (instruction 5)

**Problème identifié avant de corriger** : la sortie native de `moteur_central`
(`CandidatCentral`) ne porte PAS les champs que `enregistrer_coupons`/`agent4_rediger_coupons`
exigent par jambe (`categorie`, `handicap`, `guide`, `onglet`, `home_nom`/`away_nom`,
`contexte`) — `contrat_adapter.py` (schéma d'audit du shadow) ne les porte pas non plus, il
n'est d'ailleurs jamais utilisé par ce nouveau chemin réel.

**Résolu sans inventer de donnée** : `decision_centrale.construire_candidats` ne crée un
`CandidatCentral` d'origine `"moteur"` que pour une clé (match, marché, sélection) qui existe
**déjà** dans le pool `bet_agent` (même pari réel, probabilité concurrente) — voir ce module.
`moteur_central_run._rejoindre_candidat_bet_agent` exploite cette garantie : pour CHAQUE jambe
retenue par le coupon central (origine `bet_agent` OU `moteur`), elle retrouve le candidat
complet dans le pool `bet_agent` d'origine par cette même clé, et ne remplace QUE la probabilité/
l'edge par ceux réellement retenus par le moteur central. `categorie`/`handicap`/`guide`/
`onglet`/`home_nom`/`away_nom`/`contexte` sont donc toujours ceux, réels, du pari bet_agent
correspondant — jamais inventés, jamais une valeur par défaut masquant un trou.

**Vérifié par test** (`test_runs_moteur_central.py::test_coupon_central_genere_sans_moteur_concurrent`) :
la jambe persistée porte bien `categorie="Total"`, `handicap=2.5`, `guide="guide Total"` —
récupérés depuis le pool, pas None.

**Différence de comportement connue, non masquée** : `moteur_central/selection.py` compose **un
seul coupon par run** (2 à 5 jambes), jamais la génération dynamique multi-coupons (4-5
coupons/jour) ajoutée le 11/10/2026 au chemin "deterministe" — ce sont deux fonctionnalités
indépendantes, la bascule de moteur ne les fusionne pas. Si plusieurs coupons/jour sont
attendus avec `moteur="central"`, c'est un développement séparé, non fait ici.

## 4. Tests ajoutés — confirment l'exécution du bon moteur, sans moteur concurrent

`backend/tests/test_runs_moteur_central.py` (5 tests, tous passés) :

| Test | Vérifie |
|---|---|
| `test_coupon_central_genere_sans_moteur_concurrent` | `moteur="central"` est bien le DÉFAUT (non passé explicitement) ; `ae.generer_coupons` (deterministe) n'est **jamais** appelé (`mock.Mock(side_effect=AssertionError(...))` — lève si appelé) ; coupon persisté avec `profil="central"`, champs complets récupérés du pool |
| `test_moteur_explicite_central_identique_au_defaut` | Même résultat avec `moteur="central"` explicite |
| `test_pool_insuffisant_termine_en_erreur_jamais_de_repli` | 1 seul match (sous le minimum de 2 jambes) → run en `"erreur"`, détail explicite ("Moteur central : aucun coupon composé..."), `ae.generer_coupons` toujours jamais appelé |
| `test_pool_vide_termine_en_erreur_jamais_de_repli` | Pool vide → même garantie |
| `test_depuis_run_refuse_explicitement_pour_moteur_central` | `--depuis-run` avec `moteur="central"` → erreur explicite, pas une tentative silencieuse |

**Suite complète exécutée** (`backend/tests`, `bet_agent`, `moteur`, `moteur_central`, `tests`) :
**677 passés** (672 avant cette mission + 5 nouveaux), **0 régression**. 4 tests existants
(`test_runs.py`) ont dû fixer `moteur="deterministe"` explicitement — ils testaient ce chemin
précis (incident réel du 10/10/2026, run #129) et auraient autrement suivi le nouveau défaut
sans le vouloir ; 2 tests d'API (`test_api.py`) ont été corrigés en figeant `moteur=
"deterministe"` dans `routers/runs.py` (API hors périmètre, voir §2).

## 5. Instruction 4 — aucun repli silencieux, erreur signalée clairement

- `executer_moteur_central()` lève une exception (`RuntimeError`) dans tous les cas
  d'impossibilité : pool vide, aucun coupon composé (contrainte de diversité, cote hors cible,
  pas assez de candidats fiables), jambe retenue introuvable dans le pool d'origine.
- `runs.py:executer_run()` ne capture JAMAIS cette exception localement pour basculer vers
  `deterministe`/`agent` — elle remonte jusqu'au bloc `except Exception` déjà existant (lui-même
  inchangé), qui clôture le run en `statut="erreur"` avec `detail` = message exact de
  l'exception. `app.taches.tache_run` renvoie alors le code de sortie 1 (déjà le comportement
  existant, voir `backend/app/taches.py`) — le workflow GitHub Actions apparaît en rouge,
  visible immédiatement, jamais un succès trompeur.

## 6. Validation de production — blocages précis, NON résolus par cette mission

**Décision explicite de l'utilisateur** (après présentation de ces blocages) : préparer la
bascule sur la branche malgré les limites ci-dessous — AUCUNE n'est levée par ce travail, elles
restent entières et sont documentées ici pour que la décision de fusion/déploiement se fasse en
connaissance de cause :

1. **`MOTEUR_CENTRAL_ACTIVE` reste hardcodé `false`** partout ailleurs dans le code/la
   documentation (shadow uniquement) — convention écrite le 10/10/2026, jamais revisitée pour
   la production avant cette mission.
2. **Aucun backtest n'existe sur la sortie propre de `moteur_central`** (`score_central`/
   `selection.py`) — seulement des tests unitaires de forme/correction (`moteur_central/tests/`),
   jamais une mesure ROI/Brier/calibration réelle de ses coupons composés.
3. **L'arbitrage par marché (`choix_moteur.comparer`) est non fonctionnel en pratique
   aujourd'hui** : il exige ≥30 paris jugés par marché (`hist_cotes`), qui compte **0 ligne
   jugée** (`docs/audit_hist_cotes.md`, cette session) — `choisir_par_marche` renvoie donc
   systématiquement "indisponible", et le "central" se réduit de fait à "bet_agent ∪ moteur
   trié par score", jamais au vrai arbitrage par performance qu'il est censé incarner.
4. **`moteur/` (dont dépendent les candidats "moteur") n'est backtesté que sur 1/20
   combinaisons championnat×saison**, avec une surconfiance de calibration documentée et non
   corrigée au-delà de 80% de probabilité annoncée (`docs/audit_moteur_20_combinaisons.md`,
   `docs/diagnostic_btts_calibration.md`).
5. **Le plan de migration déjà écrit avant cette mission** (`docs/audit_moteur_unique.md`, §4)
   posait explicitement comme condition : "pas de bascule avant un backtest complet avec
   critères de décision écrits (Brier/LogLoss meilleurs que la baseline, calibration correcte
   sur ≥2 saisons indépendantes)" — condition non remplie à ce jour.

**Recommandation, non appliquée sans validation séparée** : avant toute fusion vers `main` ou
tout passage réel avec `--telegram`, exécuter au minimum un backtest walk-forward de la sortie
`moteur_central.selection.selectionner` elle-même (pas seulement de `moteur/` brut), sur
plusieurs saisons indépendantes, avec des cotes historiques réelles — actuellement indisponible
(voir `docs/plan_importation.md`, `docs/audit_hist_cotes.md`).

## 7. Ce qui n'a PAS été fait

- Aucune fusion vers `main`, aucun déploiement, aucun passage réel du workflow.
- Aucun envoi Telegram réel (tous les tests utilisent une fausse fonction `agent5_envoyer_coupons`
  qui renvoie `True` sans appel HTTP).
- Aucune donnée Supabase modifiée.
- Les anciens moteurs (`deterministe`, `agent`) sont intégralement conservés, sélectionnables
  explicitement, et couverts par leurs tests existants (inchangés sauf fixation explicite du
  paramètre `moteur=` dans les 4 tests qui en dépendaient implicitement).
