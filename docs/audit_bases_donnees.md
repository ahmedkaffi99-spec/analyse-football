# Audit des bases de données — ahmedkaffi99-spec/analyse-football

**Date de l'audit** : 2026-10-11
**Méthode** : lecture directe de Supabase (projet `fpwsitpdkruoknwmgjzr`, schéma `public`) via
`mcp__Supabase__list_tables(verbose=true)` + requêtes `execute_sql` en lecture seule, et lecture
directe des modèles SQLAlchemy (`backend/app/models.py`, `backend/app/models_historique.py`) et
des migrations (`mcp__Supabase__list_migrations`). Aucune donnée modifiée, aucune migration
appliquée. Tous les comptages ci-dessous viennent de requêtes réellement exécutées (horodatées
dans la session) — aucun chiffre n'est repris d'un rapport antérieur sans nouvelle vérification.

Supabase était accessible pendant tout l'audit — aucun blocage d'accès à signaler sur ce point.

## 1. Vue d'ensemble des tables (schéma `public`)

| Table | Lignes | Rôle réel | RLS |
|---|---|---|---|
| `runs` | 132 | 1 ligne = 1 exécution du pipeline quotidien (ou import) | activé |
| `matchs` | 1 539 | Matchs **du jour** collectés par le pipeline (fenêtre ~26/09–10/10/2026, pas un historique de saison) | activé |
| `cotes` | 794 637 | Cotes 1xBet brutes des matchs du jour (toutes sélections de tous marchés), **sans horodatage propre** | activé |
| `coupons` | 150 | Coupons envoyés (1 par run par profil) | activé |
| `jambes` | 1 027 | Paris individuels des coupons, avec `proba_modele_pct`/`edge_pct` et résultat réel | activé |
| `hist_matchs` | 760 | Backfill API-Football (scores + stats finales) — **uniquement Premier League, saisons 2023 et 2024** | activé |
| `hist_cotes` | 14 427 | Capture prospective des cotes vues par bet_agent (ROI futur) — **0 ligne jugée, tout vient du 10/10/2026** | activé |
| `hist_predictions` | 0 | Table du moteur (`moteur/`), jamais encore alimentée | activé |
| `hist_decisions_centrales` | 3 | Journal shadow du moteur_central | activé |

Pas d'autres tables, vues matérialisées ou schémas supplémentaires dans `public` au moment de
l'audit. `backend/vues.sql` définit des vues SQL (`match_complet` notamment, vue applicative, pas
une table physique) — non auditées en détail ici (hors périmètre historique/backtest).

## 2. Détail par table

### 2.1 `runs`
- Colonnes : `id (PK)`, `lance_le`, `termine_le`, `source` (`api`|`import`), `statut`, `detail`,
  `nb_matchs`, `nb_matchs_avec_marches`, `nb_marches`, `envoye_telegram`.
- Aucune clé étrangère entrante propre — référencée par `matchs.run_id`, `coupons.run_id`,
  `hist_cotes.run_id`, `hist_decisions_centrales.run_id` (toutes `ON DELETE CASCADE`).
- Fraîcheur : 132 runs du 2026-09-26 au 2026-10-10 (~2 semaines, cadence quotidienne multi-run).
- Compatibilité moteur/backtest : **aucune**, cette table ne concerne que le pipeline temps réel.

### 2.2 `matchs` + `cotes`
- `matchs` : `id (PK)`, `run_id (FK runs)`, `domicile`, `exterieur`, `ligue` (varchar libre, **pas
  de FK vers une table compétitions**), `coup_envoi`, `fixture_id_oddspapi`, `fixture_id_api_football`,
  `score_domicile/exterieur`, `donnees` (JSON brut : stats, classement, H2H, blessures...).
- `cotes` : `id (PK)`, `match_id (FK matchs)`, `marche_id`, `marche`, `handicap`, `periode`,
  `selection`, `cote` — **aucune colonne d'horodatage** : impossible de savoir à quel instant une
  cote a été vue, seulement à quel match/run elle appartient.
- Champ `ligue` en texte libre (ex. "Premier League", "2. Bundesliga", "La Liga") : non normalisé,
  629/1539 matchs ont `ligue = NULL`. Vérifié : seulement **22 matchs "Premier League", 16 "Ligue
  1", 6 "Serie A", 2 "La Liga", 24 "Bundesliga"** sur toute la fenêtre — ce sont des matchs du jour
  collectés par le pipeline en production, **pas un historique de saison**.
- Doublons : aucun contrôlé nécessaire ici (table opérationnelle, pas un référentiel). Pas de
  duplicata structurel possible (PK auto-incrémentée par run).
- Compatibilité moteur/backtest : **faible** — cette table n'a pas de notion de saison, pas de FK
  vers une table de compétitions/équipes stable, et aucune des cotes n'est horodatée avant le coup
  d'envoi de façon vérifiable indépendamment du run. Utile pour le pipeline temps réel, pas pour
  un historique multi-saison.

### 2.3 `coupons` + `jambes`
- `coupons` : `id (PK)`, `run_id (FK)`, `jour`, `profil`, `nom`, `cote_min/max/totale`,
  `proba_combinee_pct`, `texte`, `statut`, `bilan_envoye`.
- `jambes` : `id (PK)`, `coupon_id (FK)`, `match_id (FK matchs, nullable)`, `libelle_match`,
  `domicile`, `fixture_id_oddspapi`, `categorie`, `marche`, `handicap`, `selection`, `cote`,
  `proba_modele_pct`, `edge_pct`, `guide`, `onglet`, `resultat`.
- Qualité : 1 027 jambes, répartition des résultats vérifiée par requête — `gagne=336`,
  `perdu=195`, `push=19`, `non_verifiable=469`, `en_attente=8` (audits précédents de cette
  session). Les probabilités/edges sont enregistrées **avant** le résultat (fiables comme données
  "avant-match"), mais seulement pour les paris **déjà retenus** par la stratégie de production —
  pas l'univers complet des marchés évalués chaque soir.
- Compatibilité moteur/backtest : **utile mais partielle** — c'est la seule table de production
  avec probabilité pré-match + résultat réel, mais c'est un échantillon biaisé par la sélection
  (survivorship : seuls les paris jugés "solides" par le catalogue y figurent).

### 2.4 `hist_matchs` (backfill API-Football)
- Colonnes : `match_id (PK, = fixture_id API-Football)`, `date`, `competition_id`, `competition`,
  `saison`, `home_id`, `home`, `away_id`, `away`, `arbitre`, `statut`, `home_score`, `away_score`,
  `stats (JSON)`, `maj_le`.
- Contenu réel vérifié (`GROUP BY competition_id, saison`) :

  | competition_id | competition | saison | matchs | avec score | avec bloc stats (non vide) |
  |---|---|---|---|---|---|
  | 39 | Premier League | 2023 | 380 | 380 | 380 (JSON présent) |
  | 39 | Premier League | 2024 | 380 | 380 | 380 (JSON présent) |

  **Aucune autre ligue, aucune saison 2025 (2025/2026), aucune des 4 autres compétitions
  prioritaires (La Liga, Serie A, Bundesliga, Ligue 1).**
- Qualité fine des statistiques (vérifiée champ par champ sur les 760 lignes, via
  `stats->'home'->>'champ'`) :

  | Champ | Lignes avec valeur / 760 | Par saison (/380) |
  |---|---|---|
  | `possession` | 300 | **150 (≈39,5 %)** |
  | `corners` | 300 | **150 (≈39,5 %)** |
  | `shots` / `shots_on_target` | 300 | **150 (≈39,5 %)** |
  | `yellow_cards` | 294 | **147 (≈38,7 %)** |
  | **`xg` (expected goals)** | **0** | **0 (0 %)** |

  **Correctif du 2026-10-11** : une version précédente de cet audit indiquait à tort "≈79 %" en
  divisant le total combiné des 2 saisons (300) par 380 au lieu de 760 — repris ici après une
  vérification par saison séparée (`GROUP BY saison`) qui a révélé l'erreur. Le vrai taux par
  saison est **≈39,5 %**, pas 79 %. Le bloc `stats` JSON est non-NULL sur les 760 lignes, mais les
  champs internes ne sont renseignés qu'environ 4 matchs sur 10 — vraisemblablement parce que le
  run de backfill initial (run #1, 07/10/2026, ~75 secondes seulement pour 760 matchs) a été
  borné par `--limite-appels-stats` (150 par saison, valeur déduite du compte rond mais non
  confirmée dans les logs bruts, inaccessibles via l'API utilisée). **Aucune valeur de xG n'est
  fournie par la source réelle** : le champ existe dans le schéma (`moteur/features.py`) mais
  n'est jamais rempli — conformément à l'instruction de la mission, il ne doit pas être traité
  comme disponible.
- Doublons : 0 (vérifié par `GROUP BY home_id, away_id, date HAVING count(*)>1`).
- Champs manquants : `arbitre` renseigné sur 100 % des lignes (0 NULL) ; aucun match `FT/AET/PEN`
  sans score (0 incohérence statut/score détectée).
- Compatibilité moteur/backtest : **bonne pour ce qu'elle couvre** — c'est le format attendu par
  `moteur/features.py`/`moteur/backtest.py` (`HistMatch.vers_dict`), alimentée de façon idempotente
  (upsert par `match_id`) par `backend/app/services/historique.py:backfill_ligue_saison`, déjà
  déclenchable via le workflow `.github/workflows/backfill-historique.yml`. **Mais la couverture
  réelle ne représente qu'1 championnat sur 5 et 2 saisons sur les ≥4 demandées.**

### 2.5 `hist_cotes` (capture prospective)
- 14 427 lignes, **toutes du 2026-10-10** (3 runs), **0 ligne avec `resultat` rempli** — la
  fonction de jugement (`capture_historique.juger_cotes_en_attente`) existe dans le code mais n'a
  manifestement jamais tourné à son terme sur ces données, ou les matchs ne sont pas encore
  terminés/reliés.
- Colonnes mortes confirmées par la documentation du modèle (`models_historique.py`) et
  l'audit du 10/10/2026 déjà réalisé dans cette session : `match_id` et `bookmaker` existent en
  base réelle mais ne sont jamais écrits par le code actuel.
- Compatibilité moteur/backtest : **nulle pour l'instant** — conçue pour mesurer un ROI futur,
  mais sans aucune ligne encore jugée, elle ne fournit aucun résultat historique exploitable
  aujourd'hui.

### 2.6 `hist_predictions`
- 0 ligne. Table définie (`moteur.contrat`/journal de calibration), jamais alimentée en
  production. Aucune donnée à auditer.

### 2.7 `hist_decisions_centrales`
- 3 lignes seulement (journal shadow du moteur_central, un par run où ce mode a tourné).
  Hors périmètre direct de l'historique de matchs/cotes, mentionné pour complétude.

## 3. Autres mécanismes de stockage découverts
- `backend/data/bet_agent.db` : base **SQLite locale** (tests/dev), pas la base de production.
- `backend/data/collecte_run_1.json`, `collecte_run_2.json` : exports JSON de runs ponctuels, pas
  un entrepôt historique.
- `bet_agent/donnees_collectees.json` : fichier temporaire de collecte (écrasé à chaque run,
  `ENTREE_JSON`), jamais conservé comme historique.
- `backend/schema.sql`, `backend/supabase_api.sql`, `backend/vues.sql` : scripts SQL
  complémentaires (vues applicatives, droits API) — pas de table historique additionnelle trouvée.
- Aucun entrepôt de données externe (S3, fichiers Parquet/CSV historiques) trouvé dans le dépôt.

## 4. Conclusion de l'audit

La seule donnée **historique multi-match réellement exploitable pour un backtest** aujourd'hui
est `hist_matchs` (Premier League, saisons 2023/2024 et 2024/2025, 760 matchs, scores + stats
partielles, zéro xG). Tout le reste (`matchs`/`cotes`, `jambes`, `hist_cotes`) est soit une
fenêtre de production de ~2 semaines sans profondeur de saison, soit une capture prospective pas
encore jugée. **Aucune cote historique horodatée avant coup d'envoi n'existe nulle part dans la
base pour des saisons passées** — seul `hist_cotes` a un horodatage, mais uniquement pour les
cotes vues en temps réel depuis le 10/10/2026.
