# Audit comparatif complet — 20 combinaisons championnat × saison

**Date** : 2026-10-11. **Branche** : `claude/analyse-matchs-football-796va6`. **Point de
départ vérifié** : commit `99b2936` (confirmé par `git log`/`git show` avant toute modification,
working tree propre, synchronisé avec `origin`). **Suite de tests avant modification** :
635/635 passés (`backend/tests`, `bet_agent`, `moteur`, `moteur_central`).

Aucune donnée Supabase modifiée, aucun Telegram envoyé, aucune collecte relancée, aucune fusion
de moteurs effectuée, aucun code supprimé, aucun push vers `main`.

## 1. Script créé — accès DB direct sécurisé

`scripts/audit_historique/backtest_complet.py` (nouveau, lecture seule) :
- **Chemin prévu pour une exécution réelle** : `--source db` → `backend/app/database.SessionLocal`
  + `backend/app/services/historique.charger_matchs` — exactement le même mécanisme sécurisé
  (`DATABASE_URL`/`SUPABASE_DB_PASSWORD` via variables d'environnement) que le reste du backend.
  **Aucun secret n'est jamais affiché ni journalisé** — le script ne lit que des champs de
  matchs (scores, dates, stats), jamais une variable de connexion.
- **Chemin utilisé dans cette session** : `--source cache` + `--cache-dir`. **Limite
  d'environnement constatée et documentée, pas contournée en silence** : ce sandbox d'audit n'a
  ni `backend/.env`, ni `DATABASE_URL` en variable d'environnement, ni le driver `psycopg2`
  installé — une connexion Postgres directe est donc impossible ici. Le seul canal de lecture
  directe réellement disponible dans cette session est l'outil Supabase MCP (`execute_sql`),
  qui interroge la vraie base en lecture seule sans qu'aucun identifiant ne transite dans cette
  conversation. Les 20 combinaisons ont été extraites une par une (requêtes `SELECT` strictes,
  agrégées en JSON compact), chaque résultat sauvegardé automatiquement dans un fichier local
  par l'outil lorsqu'il dépasse la taille d'affichage — jamais réaffiché en clair dans cette
  conversation — puis copié dans le cache attendu par `--source cache`.
- Le script boucle les 5 championnats × 4 saisons, appelle **directement**
  `moteur.backtest.executer()` (code déjà existant, non modifié) sur chaque combinaison, avec
  `cotes_par_match={}` (aucune cote historique n'existe, voir `docs/plan_importation.md`).
- Tests : `tests/test_backtest_complet.py` (6 tests, fonctions pures `charger_depuis_cache`/
  `resume`, données synthétiques jamais présentées comme réelles).

## 2-3. Exécution réelle des 20 combinaisons

Protocole **identique** pour les 20 (même `moteur.config.Config()` par défaut, même fonction
`moteur.backtest.executer`, même règle walk-forward) :
- Features (dont l'Elo) construites uniquement à partir des matchs **strictement antérieurs** à
  chaque match prédit (`moteur/features.py:Historique`, vérifié par lecture de code).
- Calibration ajustée **uniquement sur les mois strictement antérieurs** au mois prédit
  (`moteur/backtest.py:calibrer_walk_forward`).
- Cote utilisée (si elle existait) : dernier relevé **strictement avant** le coup d'envoi — ici
  toujours absente, donc ROI/sélection par seuils explicitement marqués indisponibles.

**Résultat réel obtenu (aucune combinaison indisponible)** :

| Championnat | Saison | Matchs | Prédictions | Brier | Log loss |
|---|---|---|---|---|---|
| Premier League | 2022/2023 | 380 | 22 320 | 0.2228 | 0.6820 |
| Premier League | 2023/2024 | 380 | 22 332 | 0.2064 | 0.6389 |
| Premier League | 2024/2025 | 380 | 22 312 | 0.2187 | 0.6693 |
| Premier League | 2025/2026 | 380 | 22 352 | 0.2233 | 0.6711 |
| La Liga | 2022/2023 | 380 | 22 336 | 0.2183 | 0.6516 |
| La Liga | 2023/2024 | 380 | 22 340 | 0.2197 | 0.6620 |
| La Liga | 2024/2025 | 380 | 22 368 | 0.2178 | 0.6755 |
| La Liga | 2025/2026 | 380 | 22 332 | 0.2184 | 0.6772 |
| Serie A | 2022/2023 | 381 | 22 476 | 0.2190 | 0.6719 |
| Serie A | 2023/2024 | 380 | 22 376 | 0.2179 | 0.6685 |
| Serie A | 2024/2025 | 380 | 22 330 | 0.2210 | 0.6633 |
| Serie A | 2025/2026 | 380 | 22 392 | 0.2237 | 0.6617 |
| Bundesliga | 2022/2023 | 308 | 17 668 | 0.2240 | 0.6576 |
| Bundesliga | 2023/2024 | 308 | 17 700 | 0.2102 | 0.6395 |
| Bundesliga | 2024/2025 | 308 | 17 676 | 0.2257 | 0.6998 |
| Bundesliga | 2025/2026 | 308 | 17 684 | 0.2187 | 0.6556 |
| Ligue 1 | 2022/2023 | 380 | 22 220 | 0.2193 | 0.6602 |
| Ligue 1 | 2023/2024 | 308 | 17 676 | 0.2257 | 0.7071 |
| Ligue 1 | 2024/2025 | 308 | 17 676 | 0.2209 | 0.6749 |
| Ligue 1 | 2025/2026 | 308 | 17 632 | 0.2284 | 0.6830 |

**Total : 7 097 matchs réels, 414 198 prédictions binaires évaluées.**

**Globale (pondérée par nombre de prédictions)** : Brier = **0.2198**, Log loss = **0.6681**.
Stable entre championnats (écart max Brier : 0.206-0.228, pas d'anomalie par ligue).

## 4. Comparaison par modèle (agrégée sur les 20 combinaisons) — vs la référence

`moteur/modeles/registre.py` numérote 10 modèles spécialisés (1-7 : marchés de buts
Poisson/Dixon-Coles ; 8-10 : corners/cartons/tirs, loi binomiale négative) :

| Modèle | Marché(s) | n | Brier | Log loss | Comparaison à la référence |
|---|---|---|---|---|---|
| 3 | Handicap / Draw No Bet | 48 904 | **0.1760** | **0.5557** | **Meilleur modèle**, nettement sous la moyenne globale (0.2198) |
| 1 | Résultat (1X2) | 18 339 | 0.2061 | 0.6368 | Au-dessus de la moyenne |
| 2 | Double Chance | 18 339 | 0.2061 | 0.6355 | Au-dessus de la moyenne |
| 5 | Buts équipe domicile | 24 452 | 0.2040 | 0.6437 | Au-dessus de la moyenne |
| 6 | Buts équipe extérieure | 24 452 | 0.2154 | 0.6541 | Proche de la moyenne |
| 4 | Total buts | 36 678 | 0.2169 | 0.6562 | Proche de la moyenne |
| 10 | Tirs / tirs cadrés | 97 792 | 0.2267 | 0.6895 | Sous la moyenne |
| 9 | Cartons | 47 448 | 0.2340 | 0.7109 | Sous la moyenne |
| 8 | Corners | 85 568 | 0.2374 | 0.6993 | Sous la moyenne |
| 7 | **BTTS** | 12 226 | **0.2533** | **0.7703** | **Pire modèle, nettement** |

**Confirmation croisée réelle** : le modèle 7 (BTTS) est déjà documenté dans
`bet_agent/analyser_et_envoyer.py` comme mal calibré en production ("BTTS... mal calibré dans
TOUTES les tranches, ROI -21%", constaté sur 35 paris réels le 03/10/2026, et déjà exclu par
défaut de `CATEGORIES_EXCLUES`). **Ce nouvel audit, sur 414 198 prédictions et 7 097 matchs
réels — un échantillon ~340x plus grand — confirme indépendamment la même conclusion** avec un
moteur entièrement différent (`moteur/`, pas `bet_agent/`). C'est le signal le plus solide de
tout cet audit.

## 5. Calibration globale, données manquantes, doublons, périodes, fuite

**Calibration par tranche (agrégée sur les 414 198 prédictions)** :

| Tranche annoncée | n | Proba moyenne | Fréquence réelle | Écart |
|---|---|---|---|---|
| 0-50% | 182 723 | 0.3255 | 0.3374 | +0.0119 |
| 50-60% | 106 206 | 0.5295 | 0.5345 | +0.0050 |
| 60-70% | 56 750 | 0.6449 | 0.6386 | -0.0063 |
| 70-80% | 39 559 | 0.7453 | 0.7267 | -0.0186 |
| 80-90% | 17 913 | 0.8390 | 0.7894 | **-0.0496** |
| 90-100% | 11 047 | 0.9634 | 0.8643 | **-0.0990** |

**Confirmation à grande échelle d'un signal déjà vu sur 1 seule combinaison dans l'audit
précédent** : le moteur est bien calibré jusqu'à ~80% de confiance annoncée, puis **sur-confiant
au-delà** (annonce jusqu'à 96,3% quand la réalité est à 86,4%). Avec 11 047-17 913 prédictions
par tranche extrême, ce n'est plus un artefact d'un petit échantillon — c'est un vrai défaut de
calibration du moteur aux probabilités élevées, à corriger avant toute bascule de production.

**Données manquantes / doublons (vérifiés directement sur les 20 jeux de données extraits)** :

| Vérification | Résultat |
|---|---|
| Doublons `(home_id, away_id, date)`, les 20 combinaisons | **0** |
| Matchs sans score parmi les 7 097 | **1** (Nantes-Toulouse, Ligue 1 2025/2026, statut `AWD` — déjà documenté, correctement exclu par `est_termine()`, jamais un score inventé) |
| Serie A 2022/2023 | 381 matchs (1 de plus que les 380 attendus — déjà documenté dans `docs/couverture_historique.md`, non lié au backtest) |

**Périodes réellement testées** (bornes `debut`/`fin` vérifiées dans la sortie du script, pas
supposées) : chaque saison couvre bien l'intégralité de la fenêtre calendaire attendue (ex.
Premier League 2024/2025 : 2024-08-16 → 2025-05-25 ; Ligue 1 2025/2026 : 2025-08-15 → 2026-05-29).
Aucun trou de plusieurs semaines détecté dans aucune des 20 séries.

**Risques de fuite de données — vérifiés par lecture de code, pas supposés** :
- Elo : calculé uniquement à partir des matchs antérieurs (`Historique._calculer_elo`,
  `elo_avant` figé avant mise à jour) — vérifié correct.
- Calibration : recalibrée mois par mois, jamais avec des mois futurs
  (`calibrer_walk_forward`) — vérifié correct.
- Cotes : auraient été filtrées strictement avant le coup d'envoi si elles existaient
  (`_cote_avant`) — non exercé ici (aucune cote), mais le code est écrit pour l'exiger.
- **Aucune fuite trouvée.** Le ROI/la sélection par seuils restent explicitement marqués
  `"indisponible" / "aucune cote historique antérieure aux matchs"` par le code lui-même pour
  les 20 combinaisons — jamais une estimation ROI n'est avancée dans ce rapport.

## 6. Effet de POIDS_MARCHE_OVERRIDE — étude séparée, réversible

**Comportement par défaut vérifié inchangé** : `ae.POIDS_MARCHE == 0.65` sans
`POIDS_MARCHE_OVERRIDE` défini (confirmé par exécution réelle avant toute autre action).

Étude réalisée via le harnais déjà existant `bet_agent/backtest_production.py:comparer_poids()`
(poids 0.0 / 0.65 / 1.0) — **uniquement sur `cas_synthetiques_demo.CAS_SYNTHETIQUES_DEMO`**,
puisqu'aucune cote historique réelle n'existe pour en faire un vrai backtest (même limite que
documentée depuis le 10/10/2026 dans ce même fichier) :

| Poids marché | n (cas synthétiques) | Brier | Log loss |
|---|---|---|---|
| 0.0 (marché désactivé) | 278 | 0.2313 | 0.6637 |
| **0.65 (défaut actuel)** | 278 | **0.2218** | **0.6349** |
| 1.0 (marché seul) | 278 | 0.2202 | 0.6305 |

**Lecture strictement honnête, aucune affirmation de performance réelle** : sur ces cas
**synthétiques** (pas des matchs réels), le mélange à 0.65 et à 1.0 font légèrement mieux que 0
— mais ceci ne mesure que la cohérence interne des cas de démonstration, pas une performance en
conditions réelles (`CAS_SYNTHETIQUES_DEMO` est un jeu construit pour les tests, documenté comme
tel). **Aucune conclusion de performance n'est tirée ici** — ce tableau confirme seulement que
le mécanisme de surcharge fonctionne de bout en bout (0.0 produit bien un résultat différent de
0.65/1.0) sans jamais avoir modifié le comportement par défaut en production.

## 7. Reproductibilité — commandes exactes

```bash
# Chemin prévu en production/CI (nécessite DATABASE_URL ou SUPABASE_DB_PASSWORD) :
python scripts/audit_historique/backtest_complet.py --source db \
    --sortie-json resultat_20_combinaisons.json

# Chemin utilisé dans cette session (cache déjà extrait de Supabase en lecture seule) :
python scripts/audit_historique/backtest_complet.py --source cache \
    --cache-dir <dossier contenant 39_2022.json, 39_2023.json, ..., 61_2025.json> \
    --sortie-json resultat_20_combinaisons.json

# Étude POIDS_MARCHE_OVERRIDE (synthétique, réversible) :
cd bet_agent && python3 -c "
from backtest_production import comparer_poids
from cas_synthetiques_demo import CAS_SYNTHETIQUES_DEMO
print(comparer_poids(CAS_SYNTHETIQUES_DEMO, poids_liste=(0.0, 0.65, 1.0)))"
```

Configuration utilisée : `moteur.config.Config()` par défaut (aucun paramètre modifié) ;
`LIGUES_PRIORITAIRES = {39: Premier League, 140: La Liga, 135: Serie A, 78: Bundesliga, 61: Ligue 1}` ;
`SAISONS_PRIORITAIRES = (2022, 2023, 2024, 2025)`.

## 8. Limites assumées

- Les 20 jeux de données ont été extraits via l'outil Supabase MCP de cette session (lecture
  seule, aucun identifiant exposé) plutôt que via une connexion Postgres directe locale, faute
  de `DATABASE_URL`/`SUPABASE_DB_PASSWORD` configurés dans ce sandbox. Le script livré supporte
  nativement le chemin direct (`--source db`) pour une exécution future en CI ou sur un poste
  configuré — recommandé pour toute reproduction indépendante de ces chiffres.
- Aucune cote historique n'existe (`hist_cotes` n'a aucune ligne jugée pour des saisons passées,
  voir `docs/plan_importation.md`) : ROI, sélection par seuils, et edge restent **non
  mesurables** — jamais estimés dans ce rapport.
- L'étude POIDS_MARCHE_OVERRIDE reste synthétique (§6) — aucune validation en conditions
  réelles n'est revendiquée.
- Aucun changement de ce rapport n'a été appliqué à la production : `POIDS_MARCHE` reste à 0.65
  par défaut, aucun moteur n'a été fusionné, aucun fichier supprimé.

## Tests — avant/après cette mission

| | Avant (commit `99b2936`) | Après (ce rapport) |
|---|---|---|
| `backend/tests` + `bet_agent` + `moteur` + `moteur_central` | 635 passés | 635 passés (inchangé, 0 régression) |
| + `tests/` (nouveau `test_backtest_complet.py`, 6 tests) | 643 (avec `test_audit_historique.py` déjà présent) | **649 passés** |

Aucune modification de `bet_agent/analyser_et_envoyer.py` ni d'aucun autre fichier de
production dans cette mission — seuls des fichiers nouveaux (`scripts/`, `tests/`, `docs/`) ont
été ajoutés.

## Commit final

Voir `git log` sur `claude/analyse-matchs-football-796va6` pour le commit exact qui porte ce
rapport, le script et ses tests (créé après la ré-exécution complète de la suite ci-dessus).
