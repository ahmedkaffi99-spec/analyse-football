# Audit — vers un moteur unique de prédiction

**Date** : 2026-10-11. **Méthode** : lecture directe du code réel (pas de supposition), exécution
réelle de la suite de tests, exécution réelle (partielle, voir §4) du backtest walk-forward
existant sur des données `hist_matchs` réellement présentes en Supabase. Aucune donnée Supabase
modifiée pendant cet audit, aucun Telegram envoyé, aucun nouveau backfill lancé.

## 1. Données de référence consultées

- `docs/couverture_historique.md` : 5 championnats (Premier League, La Liga, Serie A,
  Bundesliga, Ligue 1) × 4 saisons (2022/2023-2025/2026) tous collectés dans `hist_matchs`
  (confirmé par requête directe, inchangé depuis la dernière mission). **xG = 0% partout, cotes
  historiques horodatées = 0% partout** — confirmé encore vrai à ce jour, aucune régression.
- `docs/plan_importation.md` : blocage cotes historiques toujours ouvert (aucune source
  confirmée).
- `docs/audit_bases_donnees.md` : schéma des tables de production (`runs`/`matchs`/`cotes`/
  `coupons`/`jambes`) vs historique (`hist_*`), déjà séparés et à jour.

## 2. Pipeline quotidien réel — diagramme

```
GitHub Actions "Pipeline quotidien" (.github/workflows/pipeline-quotidien.yml)
  cron horaire (6h07-13h07 UTC) + workflow_dispatch
        │
        ▼
  python -m app.taches run [--telegram] [--moteur deterministe|agent]
        │  (backend/app/taches.py:tache_run)
        ▼
  backend/app/services/runs.py:executer_run()
        │
        ├─ moteur="deterministe" (OFFICIEL depuis le 03/10/2026, défaut) ───────────────────┐
        │     bet_agent/collecte_donnees.py → bet_agent/analyser_et_envoyer.py:              │
        │     generer_coupons() → composition automatique (Monte Carlo, Python seul) →       │
        │     agent4_rediger_coupons() (LLM : RÉDACTION texte seulement, ne choisit rien)     │
        │                                                                                     │
        └─ moteur="agent" (DeepSeek autonome, 30/09-03/10/2026, encore disponible) ───────────┘
              bet_agent/agent_pilote.py : choisit lui-même les paris, collecte, rédige, envoie

        ▼ (un seul des deux chemins ci-dessus produit la sortie réelle, jamais les deux à la fois)
  enregistrer_coupons() → table coupons/jambes (Supabase, SORTIE RÉELLE #1)
        │
        ▼ (si --telegram)
  agent5_envoyer_coupons() [chemin "deterministe"] OU notifier_telegram interne [chemin "agent"]
        → Telegram (CHAÎNE DE PUBLICATION RÉELLE, un seul message par jour)

  ── Après que tout ce qui précède est déjà committé (jamais utilisé pour la sélection/Telegram) ──
        ├─ MOTEUR_COMPARAISON_ACTIVE (off par défaut) → comparaison_moteurs.comparer_candidats()
        │     bet_agent vs moteur/ — informatif seulement, imprimé dans les logs
        ├─ capture_historique.capturer_predictions() — TOUJOURS actif (pas de flag), écrit
        │     hist_cotes (capture prospective, jamais lue par la sélection)
        └─ MOTEUR_CENTRAL_SHADOW (off par défaut) → decision_centrale.calculer_et_journaliser_shadow()
              bet_agent vs moteur/ vs moteur_central/ — écrit hist_decisions_centrales, jamais lu
```

**Entrée** : une seule (`pipeline-quotidien.yml` → `app.taches run`) — ✅ déjà conforme.
**Sortie normalisée** : une seule table `coupons`/`jambes`, un seul format de texte envoyé — ✅
déjà conforme (consolidé en un coupon unique depuis le 03/10/2026, voir historique du dépôt).
**Chaîne de publication** : une seule (Telegram, un message/jour, gardé par
`ticket_deja_produit_aujourdhui`) — ✅ déjà conforme, aucun doublon d'envoi possible.

## 3. Redondances réelles identifiées

| # | Composant | Nature de la redondance | Conflit réel avec la prod ? |
|---|---|---|---|
| R1 | `bet_agent/analyser_et_envoyer.py` (moteur="deterministe") vs `bet_agent/agent_pilote.py` (moteur="agent") | **2 chemins de décision complets**, sélectionnables par un flag CLI/workflow_dispatch, chacun capable de choisir les paris ET d'envoyer Telegram | Non — mutuellement exclusifs par run (jamais les deux en même temps), mais ce sont 2 moteurs de prédiction réels, pas 1 |
| R2 | `moteur/` (Poisson/Dixon-Coles/Elo/ML, 10 modèles + calibration + backtest, déjà très avancé) | 3e moteur de prédiction, actuellement JAMAIS utilisé pour la sélection réelle — seulement comparé en mode informatif (R3) ou backtesté hors-ligne | Non — isolé, aucun chemin ne le relie à Telegram |
| R3 | `moteur_central/` (fusion bet_agent + moteur, score_central.py, melange.py) | 4e "moteur", conçu comme futur point de convergence, gardé par `MOTEUR_CENTRAL_ACTIVE=false` (toujours faux) | Non — shadow-only, écrit seulement `hist_decisions_centrales` |
| R4 | `comparaison_moteurs.py` + `decision_centrale.py` | 2 modules de comparaison distincts qui recalculent chacun un pool de candidats séparément (`agent3_calcul_pool_candidats` appelé jusqu'à 2 fois par run si les 2 flags sont actifs) | Non fonctionnel, mais travail dupliqué pour rien si les 2 flags sont actifs ensemble |

**Aucune redondance ne casse "une seule sortie/une seule chaîne de publication"** — ces garanties
sont déjà respectées. La vraie redondance porte sur le **nombre de moteurs de prédiction qui
existent dans le dépôt** (4 : bet_agent déterministe, agent_pilote, moteur/, moteur_central/),
alors que la mission en demande 1 à terme.

## 4. Plan de migration vers un moteur unique (PROPOSITION — rien exécuté)

Ce plan n'a **pas** été appliqué : la mission demande explicitement de ne pas modifier la
stratégie de production avant validation. Il sert de feuille de route.

1. **Geler `agent_pilote.py` comme chemin de secours, pas comme moteur égal** : documenter
   (déjà en partie fait dans `runs.py`) que "deterministe" est LE moteur officiel ; `agent`
   reste disponible pour comparaison manuelle mais n'est plus proposé par défaut dans
   `pipeline-quotidien.yml` (actuellement `default: deterministe`, déjà le cas — seule
   l'option reste sélectionnable manuellement, à retirer dans une étape ultérieure si
   confirmé inutile).
2. **Valider `moteur/` sur l'historique réel désormais disponible** (5 championnats × 4
   saisons, voir §5) avant d'envisager un remplacement de `bet_agent/analyser_et_envoyer.py`.
   Pas de bascule avant un backtest complet avec critères de décision écrits (Brier/LogLoss
   meilleurs que la baseline, calibration correcte sur ≥2 saisons indépendantes).
3. **Si `moteur/` est validé** : le faire passer de "shadow comparaison" (R3/R4) à "source de
   la probabilité réellement utilisée", en remplaçant le mélange interne de
   `analyser_et_envoyer.py` par un appel à `moteur.modeles.registre.predire_match` — supprimer
   alors `agent_pilote.py` et `moteur_central/` (ou les geler définitivement) SEULEMENT après
   vérification de leurs dépendants (aucun fichier de production ne doit les importer).
4. **Fusionner `comparaison_moteurs.py`/`decision_centrale.py`** pour ne calculer le pool de
   candidats qu'une fois par run (R4) — optimisation mineure, sans urgence.

Chaque étape ci-dessus est un changement de production distinct, à valider séparément — aucune
n'est faite dans cette mission.

## 5. POIDS_MARCHE — audit de la formule et désactivation réversible

**Formule exacte vérifiée dans le code** (`bet_agent/analyser_et_envoyer.py`, fonction
`evaluer_marches_toutes`) :
```
p = (1 - POIDS_MARCHE) * p_modele + POIDS_MARCHE * p_marche
edge_pct = (p * cote - 1) * 100
```
`p_marche` = probabilité implicite du marché **sans la marge du bookmaker** (normalisée par
`probabilites_sans_marge`), `p_modele` = probabilité du modèle Poisson. **Une seule utilisation
réelle** de `POIDS_MARCHE` dans tout le dépôt (confirmé par recherche exhaustive) ; 1 test de
non-régression existant (`test_backtest_production.py::test_ae_poids_marche_vaut_bien_0_65_
aujourdhui`) protège déjà sa valeur par défaut.

**Changement appliqué** (réversible, valeur par défaut INCHANGÉE) :
```python
POIDS_MARCHE = float(os.getenv("POIDS_MARCHE_OVERRIDE") or 0.65)
```
- Sans `POIDS_MARCHE_OVERRIDE` défini (cas de la production aujourd'hui, aucune variable ajoutée
  à `pipeline-quotidien.yml`) : **comportement strictement identique à avant** — vérifié par le
  test déjà existant, toujours vert.
- `POIDS_MARCHE_OVERRIDE=0` : désactive totalement l'influence du marché, la probabilité finale
  devient purement celle du modèle Poisson — vérifié par un nouveau test
  (`bet_agent/test_poids_marche_override.py`) qui compare `evaluer_marches_toutes` à
  `_evaluer_marches_brut` (probabilité modèle pure) et confirme l'égalité.
- **Aucun code ni donnée supprimé** — `hist_cotes`/`cotes` intacts, la constante reste modifiable
  dans les deux sens.
- **Je n'affirme aucune amélioration de performance** de cette désactivation : elle n'a été ni
  activée en production, ni backtestée comparativement (nécessiterait de rejouer §4/§6 avec
  `POIDS_MARCHE_OVERRIDE=0`, non fait dans cette mission — proposé comme prochaine étape).

## 6. Évaluation des modèles — ce qui existe déjà vs ce qui a été mesuré maintenant

**Constat important** : contrairement à ce que la mission semblait supposer, la plupart des
briques demandées **existent déjà** dans `moteur/` (travail antérieur de cette session, phases
7-25) :

| Demandé | État réel trouvé dans le code |
|---|---|
| Elo (force relative) | **Déjà implémenté** — `moteur/features.py:Historique._calculer_elo` (Elo avant chaque match, mise à jour après seulement, aucune fuite) |
| Poisson / Dixon-Coles (buts) | **Déjà implémenté** — `moteur/modeles/registre.py`, `rho_dixon_coles` configurable (`moteur/config.py`) |
| Machine Learning (scikit-learn) | **Déjà implémenté** — `moteur/comparaison.py:comparer()` (LogisticRegression + HistGradientBoostingClassifier, avec repli propre si scikit-learn absent) |
| Calibration des probabilités | **Déjà implémenté** — `moteur/calibration.py`, calibrage walk-forward mois par mois (jamais sur le futur) |
| Forme récente / domicile-extérieur | **Déjà implémenté** — `moteur/features.py:construire_features` (fenêtre de forme configurable, moyennes domicile/extérieur séparées) |
| Backtest walk-forward, sans fuite | **Déjà implémenté** — `moteur/backtest.py:executer()` (calibration sur mois strictement antérieurs, cote strictement antérieure au coup d'envoi, sinon ROI explicitement indisponible) |

**Ce qui manquait réellement** : ces briques n'avaient jamais été exécutées sur de vraies
données multi-championnats, parce que `hist_matchs` ne couvrait qu'1 championnat avant la
mission précédente. **C'est fait pour la première fois ici — mais partiellement (1/20
combinaisons championnat×saison), voir limite ci-dessous.**

### Baseline réelle obtenue (Premier League, saison 2024/2025, 380 matchs réels)

Exécution réelle de `moteur.backtest.executer()` sur les 380 matchs de Premier League 2024/2025
chargés depuis `hist_matchs` (via Supabase, lecture seule), sans aucune cote historique (aucune
n'existe, voir §1) :

```
Matchs : 380 — Prédictions binaires générées : 22 312 (tous marchés/modèles confondus)
Brier global     : 0.2187
Log loss global  : 0.6693
Win rate global   : 0.5000 (attendu structurellement ~0.5 pour des marchés Over/Under équilibrés)

Calibration par tranche de probabilité annoncée :
  0-50%  : n=9780  proba moy=0.313  fréquence réelle=0.328  écart=+0.015
  50-60% : n=5525  proba moy=0.528  fréquence réelle=0.537  écart=+0.009
  60-70% : n=2606  proba moy=0.645  fréquence réelle=0.638  écart=-0.007
  70-80% : n=2851  proba moy=0.747  fréquence réelle=0.726  écart=-0.021
  80-90% : n=834   proba moy=0.840  fréquence réelle=0.758  écart=-0.082  <- SURCONFIANCE
  90-100%: n=716   proba moy=0.959  fréquence réelle=0.862  écart=-0.097  <- SURCONFIANCE

Sélection/ROI/seuils : INDISPONIBLES ("aucune cote historique antérieure aux matchs") — exact,
  conforme à l'instruction de ne jamais affirmer un ROI sans les cotes nécessaires.
```

**Lecture honnête** : la calibration est bonne jusqu'à ~80% de probabilité annoncée, mais le
moteur est **mesurablement surconfiant au-delà de 80%** (sur-estime ses propres certitudes de
8-10 points) — un vrai signal, mesuré sur des données réelles, qui mériterait d'être creusé avant
toute bascule de production (§4, étape 2). Le modèle n°7 (sur 10, `par_modele` dans la sortie
brute) a le pire Brier (0.2578) et log-loss (0.8822) de tous — à identifier et investiguer en
priorité dans un futur backtest complet.

### Limite assumée de cette mesure — NE PAS généraliser

**Cette baseline couvre 1 combinaison championnat×saison sur les 20 désormais disponibles**
(Premier League 2024/2025 seulement). Les 19 autres (La Liga, Serie A, Bundesliga, Ligue 1, et
les autres saisons de Premier League) n'ont **pas** été passées dans le backtest pendant cette
mission : extraire ~7 600 lignes `hist_matchs` (avec leur bloc `stats` JSON) via l'outil SQL de
cette session dépasserait plusieurs fois la limite de taille d'un appel et consommerait un
volume de contexte disproportionné pour peu de valeur ajoutée par rapport à l'exécuter une
seule fois via un script avec un accès direct à `DATABASE_URL` (CI, ou poste avec `backend/.env`
configuré) — ce script (`moteur/backtest.py`, déjà écrit et déjà fonctionnel, démonstration
ci-dessus) n'a besoin d'aucun développement supplémentaire, seulement d'être exécuté 20 fois (ou
une fois sur l'union des 20) dans un environnement avec accès direct à la base. **Recommandation
concrète pour la suite** : ajouter un petit script `moteur/executer_backtest_complet.py` (ou une
tâche `app.taches`) qui boucle sur les 5 championnats × 4 saisons via `historique.charger_matchs`
et exécute `backtest.executer`, pour obtenir la grille complète sans repasser par cette session.
Aucun chiffre pour les 19 autres combinaisons n'est avancé ici — ni bon, ni mauvais.

## 7. Suite de tests — avant/après

| | Avant cette mission | Après (avec le flag POIDS_MARCHE_OVERRIDE + ses tests) |
|---|---|---|
| Tests (`backend/tests`, `bet_agent`, `moteur`, `moteur_central`) | 631 passés | **635 passés** (+4 nouveaux, 0 régression) |
| Comportement par défaut de `POIDS_MARCHE` | 0.65 codé en dur | 0.65 (inchangé), surchargeable explicitement |
| Fichiers de production modifiés | — | `bet_agent/analyser_et_envoyer.py` (1 ligne, réversible) |
| Tests ajoutés | — | `bet_agent/test_poids_marche_override.py` (4 tests) |

Aucun déploiement, aucune fusion vers `main`, aucun changement de workflow GitHub Actions, aucun
envoi Telegram, aucune collecte historique relancée, aucune donnée Supabase modifiée pendant
cette mission.

## 8. Ce qui attend une validation explicite avant toute action

- Basculer `POIDS_MARCHE_OVERRIDE` en production (même pour un test ponctuel) — nécessite un
  backtest comparatif chiffré d'abord (§5).
- Exécuter le backtest complet sur les 20 combinaisons (§6) — techniquement prêt, pas lancé ici.
- Toute étape du plan de migration §4 (retrait d'`agent_pilote.py`/`moteur_central/`, bascule
  de `analyser_et_envoyer.py` vers `moteur/`) — aucune n'est amorcée.
- Investigation du modèle n°7 (pire Brier/log-loss) et de la surconfiance >80% — signalés, non
  corrigés.
