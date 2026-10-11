# Bilan et plan de déploiement — PLAN FINAL (Phases 1-3)

**Date** : 2026-10-11. **Branche** : `claude/analyse-matchs-football-796va6`. **Commit de
départ vérifié** : `a8e5089`. **Commit actuel** : `26d6c19` (poussé sur la branche, pas sur
`main`). **CI réelle vérifiée verte** sur ce commit (run GitHub Actions `38110626447`,
`conclusion: success`), pas seulement en local.

**Aucun déploiement, aucune fusion vers `main`, aucun envoi Telegram, aucune collecte relancée
n'a été effectué.** Ce document attend une validation explicite avant toute Phase 4.

## PHASE 1 — Audit et inventaire

### 1.1-1.2 État Git/tests/CI, rapports relus
- `git log`/`git status` vérifiés avant toute action (voir en-tête).
- Relecture de `docs/audit_bases_donnees.md`, `couverture_historique.md`,
  `architecture_historique.md`, `plan_importation.md`, `audit_moteur_unique.md`,
  `audit_moteur_20_combinaisons.md`, `diagnostic_btts_calibration.md`.
- **CI corrigée et vérifiée** (trouvaille réelle de cet audit) : `.github/workflows/tests.yml`
  ne faisait tourner que 4 fichiers de test sur 11 dans `bet_agent/` (reste à l'oubli d'une
  invocation `unittest` jamais mise à jour), et jamais `moteur_central/tests/` ni le dossier
  `tests/` à la racine — donc jamais vérifié par la CI, y compris le hook réversible
  `POIDS_MARCHE_OVERRIDE` ajouté lors d'une mission précédente. **Corrigé** (commit `26d6c19`),
  vérifié localement (659/659) ET sur une vraie exécution GitHub Actions (succès).

### 1.3 Liste exhaustive des tâches restantes, bugs, risques

**Terminé pendant cette session (vérifié, pas supposé)** :
- Historique 5 championnats × 4 saisons dans `hist_matchs` (`docs/couverture_historique.md`).
- Backtest réel walk-forward sur les 20 combinaisons (`docs/audit_moteur_20_combinaisons.md`).
- Diagnostic BTTS complet : hypothèse `rho_dixon_coles` testée et **réfutée** par les
  données ; cause réelle = corrélation quasi nulle entre probabilité et résultat
  (`docs/diagnostic_btts_calibration.md`).
- Comparaison calibration isotone (déjà en prod) vs Platt, protocole chronologique strict :
  aucune amélioration robuste démontrée → **isotone conservée sans changement**.
- `POIDS_MARCHE` : surcharge réversible préparée, **valeur par défaut 0.65 jamais modifiée**.
- CI corrigée pour couvrir réellement tout le dépôt.

**Restant, non fait, explicitement hors périmètre ou en attente d'une décision** :
1. **`hist_cotes` jamais jugée** : `capture_historique.juger_cotes_en_attente` existe mais
   n'est câblée à AUCUNE commande (`app.taches`) ni workflow — la capture prospective démarrée
   le 10/10/2026 ne produira jamais de ROI mesuré tant que ce jugement n'est pas planifié. Gap
   pré-existant, non corrigé ici (changerait un comportement de production, hors autorisation
   de cette mission sans décision explicite).
2. **4 moteurs de prédiction coexistent** (`bet_agent` déterministe [officiel], `agent_pilote`
   [encore sélectionnable], `moteur/`, `moteur_central/`) — plan de migration déjà écrit
   (`audit_moteur_unique.md`), **non exécuté**, conformément à l'interdiction explicite de
   fusion définitive sans validation séparée.
3. **Incohérence de cible de cote totale** trouvée pendant cet audit : `agent_strategie.py`
   (`COTE_TOTALE_MIN = 5.0`, chemin IA, "interdit les cote total moins de 5") vs
   `analyser_et_envoyer.py` (`PROFILS_COUPON[0]["cote_max"] = 2.1`, chemin de repli Python
   Monte Carlo) — deux cibles de cote totale contradictoires selon le chemin réellement pris.
   **Non corrigé** : clarifier l'intention réelle (laquelle est correcte ?) est une décision de
   stratégie de production, explicitement interdite sans validation séparée dans cette mission.
4. **Cotes historiques horodatées** : toujours aucune source confirmée (`plan_importation.md`),
   endpoint `/odds` d'API-Football jamais testé (consommerait du quota réel, autorisation
   distincte requise). ROI sur saisons passées reste non mesurable.
5. **xG** : confirmé absent de la source réelle, limite acceptée, pas une action à faire.
6. **BTTS** : pas de défaut de calcul trouvé ; déjà exclu de la sélection de production
   (`CATEGORIES_EXCLUES`) — cohérent avec le diagnostic, rien à changer.
7. **Marge de Platt vs isotone** : réelle mais mesurée sur un seul découpage temporel, non
   qualifiable de robuste — piste pour un futur travail, pas une action immédiate.

### 1.4 Marchés et plages de cotes — vérifié, pas supposé
**Aucune restriction du système à une plage 1.10-1.30 n'existe nulle part dans le code**
(recherche exhaustive dans `bet_agent/` et `moteur/`). Les plages réelles trouvées :
- `COTE_MIN_JAMBE = 1.20` (`analyser_et_envoyer.py`) : plancher par JAMBE individuelle.
- `PROFILS_COUPON` : cible de cote TOTALE du coupon 1.1-2.1 (chemin de repli Python uniquement).
- `COTE_TOTALE_MIN = 5.0` (`agent_strategie.py`) : plancher de cote totale pour le chemin IA
  (voir l'incohérence §1.3.3 ci-dessus).
- `moteur/config.py` : `cote_min=1.15`, `cote_max=2.00` (configuration du moteur `moteur/`,
  non utilisé en sélection réelle actuellement).
Aucune cote historique n'a été inventée pour cette vérification — uniquement la lecture du code
et des constantes réellement déclarées.

### 1.5 Workflow quotidien unique — confirmé
`pipeline-quotidien.yml` (cron horaire 6h07-13h07 UTC + `workflow_dispatch`) →
`python -m app.taches run` → `runs.py:executer_run()` → moteur `deterministe` par défaut
(`bet_agent/analyser_et_envoyer.py`) → `enregistrer_coupons` (table `coupons`/`jambes`) →
Telegram (`agent5_envoyer_coupons`), un seul coupon/jour (`ticket_deja_produit_aujourdhui`
empêche tout doublon). **Comportement inchangé par cette mission** — voir §Phase 2 ci-dessous.

### 1.6 Moteurs redondants — identifiés, centralisation PRÉPARÉE, pas exécutée
Voir §1.3.2. Aucune dépendance supprimée, aucun fichier retiré.

## PHASE 2 — État des corrections

| Point demandé | Statut | Détail |
|---|---|---|
| Corriger les bugs démontrés | **Aucun bug de calcul trouvé** dans BTTS/handicap (code vérifié correct) | Le défaut BTTS est un manque de pouvoir prédictif, pas un bug |
| `rho_dixon_coles` non calibré | **Étudié, hypothèse réfutée empiriquement** | Aucun changement — une amélioration non démontrée n'est jamais imposée (conforme à l'instruction) |
| Calibration/fiabilité sur tous les marchés | **Évaluée** (20 combinaisons, 414k+ prédictions) | Isotone déjà quasi parfaite sur test tenu à l'écart ; Platt non robuste |
| `POIDS_MARCHE=0.65` préservé | **Oui**, vérifié par test à chaque run | Surcharge réversible existe mais n'est activée nulle part |
| Tests de non-régression + anti-fuite | **Ajoutés** (14 nouveaux tests cette session : 4 POIDS_MARCHE + 10 BTTS/calibration) | Anti-fuite chronologique vérifiée explicitement |
| Un seul chemin d'exécution quotidien, une seule chaîne de publication | **Déjà vrai, confirmé, non modifié** | Voir §1.5 |
| Suite complète + CI + configuration | **Exécuté** : 659/659 local, CI GitHub Actions réelle verte | Commit `26d6c19` |

## PHASE 3 — Préparation de la production

### Liste des modifications (commit candidat : `26d6c19`)
Tout le travail depuis `a8e5089` est **additif ou de configuration CI**, jamais une modification
de comportement du pipeline de production :
1. `bet_agent/analyser_et_envoyer.py` : **1 ligne modifiée** (`POIDS_MARCHE` lit un override
   d'environnement, défaut inchangé — aucune variable de ce nom n'existe dans
   `pipeline-quotidien.yml` ni dans les secrets/variables du dépôt).
2. `.github/workflows/tests.yml` : couverture de test élargie (ne touche aucun workflow de
   production).
3. Nouveaux fichiers uniquement : `scripts/audit_historique/*.py` (3 scripts de diagnostic en
   lecture seule), `tests/*.py` (24 nouveaux tests au total), `docs/*.md` (7 documents).

**Conséquence directe, à vérifier avant toute décision de déploiement** : comme aucune logique
de production n'est modifiée (seul un hook inerte et la CI), fusionner cette branche dans
`main` ne changerait RIEN au comportement réel de `pipeline-quotidien.yml` — même moteur par
défaut, même `POIDS_MARCHE=0.65`, même coupon unique, même chaîne Telegram. C'est vérifiable en
relisant le diff plutôt qu'en le supposant.

### Résultats des tests et de la CI
- Local : 659/659 passés (`backend/tests`, `bet_agent`, `moteur`, `moteur_central`, `tests`).
- GitHub Actions (réel, pas supposé) : run `38110626447` sur commit `26d6c19` →
  `status: completed`, `conclusion: success`.

### Configuration requise, secrets manquants, migrations
- **Aucun nouveau secret requis.** `POIDS_MARCHE_OVERRIDE` reste optionnel et absent.
- **Aucune migration Supabase nécessaire** — aucune table modifiée par ce travail.
- Secrets déjà existants (`DATABASE_URL`/`SUPABASE_DB_PASSWORD`, `API_FOOTBALL_KEY`, etc.) :
  présence déjà confirmée indirectement par les runs CI/Actions réels de cette session
  (backfills et vérifications réussis) — **valeurs jamais affichées ni lues ici**.

### Risques résiduels et conditions de retour arrière
- **Risque principal : aucun** sur le comportement du pipeline (rien n'y change). Risque
  résiduel réel = les points ouverts du §1.3 (hist_cotes jamais jugée, 4 moteurs non fusionnés,
  incohérence de cote totale) — aucun n'est aggravé ni résolu par ce commit.
- **Retour arrière** : trivial si fusionné — `git revert` du merge, puisqu'aucune donnée de
  production ni aucun comportement par défaut n'est modifié. Aucune migration à annuler.

### Workflow qui serait réellement exécuté
`pipeline-quotidien.yml`, inchangé : cron horaire + `workflow_dispatch`, moteur `deterministe`
par défaut, `--telegram` uniquement sur le passage planifié avec garde anti-doublon.

### Plan de surveillance 7 jours (proposé, pas encore commencé)
**Point important à valider avec vous avant de le lancer** : comme ce commit ne change aucun
comportement de production, une surveillance de 7 jours sur `main` observerait le pipeline
**déjà existant et déjà en cours d'exécution quotidienne depuis le 26/09/2026** — pas un
changement nouveau. Si vous confirmez vouloir ce suivi malgré tout (utile pour la santé
opérationnelle générale, indépendamment de ce commit), le plan serait :
- Vérifier chaque jour, via l'API GitHub Actions, le statut du run quotidien (succès/échec,
  durée, logs d'erreur Python).
- Vérifier dans Supabase (lecture seule) : un seul coupon/jour, aucun doublon, aucune jambe
  vide/incomplète, `envoye_telegram` cohérent avec un seul message réel.
- Vérifier le règlement (`verification-resultats.yml`) : comparaison des résultats réels aux
  probabilités enregistrées AVANT le coup d'envoi (déjà garanti par le schéma `jambes.proba_
  modele_pct`/`resultat`), jamais une probabilité recalculée après coup.
- Consigner tout incident (date, commit, workflow, symptôme, cause, gravité, correctif proposé)
  dans un document de suivi dédié — **jamais de modification silencieuse du modèle** pendant
  cette période, conformément à l'instruction.
- **Aucune affirmation de ROI/rentabilité** ne sera tirée de ces 7 jours — seulement la santé
  opérationnelle (échecs, doublons, délais) et la justesse du règlement, pas la performance des
  pronostics.

## Décision demandée

Ce document clôt les Phases 1-3. **Aucune Phase 4 (déploiement) n'a été engagée.**

Merci de confirmer explicitement :
1. Si cette branche doit être fusionnée dans `main` (rappel : comportement identique au
   pipeline actuel, seul bénéfice = CI corrigée + documentation + hook réversible inerte).
2. Si le suivi de 7 jours proposé doit être lancé malgré l'absence de changement de
   comportement, et sur quel périmètre exact.
3. Si l'un des points ouverts du §1.3 (notamment l'incohérence de cote totale, ou le jugement
   de `hist_cotes` jamais câblé) doit être traité dans une mission séparée.
