# Architecture cible — données historiques pour backtest

Construite à partir du schéma **réel** audité (`docs/audit_bases_donnees.md`), pas d'un schéma
idéal théorique. Principe directeur : **réutiliser au maximum ce qui existe déjà et fonctionne**
(`hist_matchs`, `moteur/features.py`, `backend/app/services/historique.py`), n'ajouter du neuf
que pour combler un vide réel, et ne jamais toucher aux tables de production du pipeline
quotidien (`matchs`, `cotes`, `coupons`, `jambes`, `runs`).

## 1. Principe de séparation (déjà respecté, à conserver)

Le schéma actuel sépare déjà correctement deux mondes, par préfixe de table :
- **Pipeline quotidien** (`runs`, `matchs`, `cotes`, `coupons`, `jambes`) : production réelle,
  jamais un historique de saison, jamais à modifier pour les besoins du backtest.
- **Historique/moteur** (préfixe `hist_`) : `hist_matchs` (import), `hist_cotes` (capture),
  `hist_predictions` (nos prédictions), `hist_decisions_centrales` (nos décisions). Cette
  séparation EST la distinction demandée entre « données historiques importées » et
  « prédictions produites par notre système » — elle existe déjà dans le nommage et doit être
  conservée telle quelle, pas réinventée.

## 2. Saisons et compétitions

**Décision : ne pas créer de table `competitions`/`saisons` séparée pour l'instant.**
`hist_matchs.competition_id` (entier API-Football) + `hist_matchs.competition` (nom) +
`hist_matchs.saison` (entier, année de début) remplissent déjà ce rôle de façon dénormalisée mais
fonctionnelle, et c'est le format que `moteur/features.py` (ligne 152,
`_moyennes_ligue(hist, match.get("competition_id"), ...)`) consomme déjà tel quel. Normaliser
casserait la compatibilité sans bénéfice mesuré. Si le besoin de métadonnées de compétition
(format de saison, nombre d'équipes, fuseau horaire des coups d'envoi) apparaît plus tard, une
table `competitions(id PK, nom, pays, format_saison)` purement référentielle pourrait être
ajoutée SANS toucher `hist_matchs` (jointure optionnelle sur `competition_id`).

**IDs des 5 championnats prioritaires (API-Football, déjà utilisés par le workflow de backfill)** :
Premier League=39, La Liga=140, Serie A=135, Bundesliga=78, Ligue 1=61.

## 3. Équipes

**Décision : pas de table `equipes` séparée pour l'instant.** `hist_matchs.home_id`/`away_id`
sont déjà les identifiants stables API-Football (mêmes IDs d'une saison à l'autre), et
`home`/`away` portent le nom au moment du match. Un changement de nom de club entre deux saisons
(rare) resterait visible sans ambiguïté grâce à l'ID stable. Si une table `equipes(id PK, nom,
pays, competition_id)` est introduite plus tard pour un référentiel de noms normalisés (ex.
affichage utilisateur), elle devra rester une pure table de lookup, jamais une clé de jointure
obligatoire pour le moteur.

## 4. Matchs et résultats — `hist_matchs` (déjà adéquate, à étendre en volume, pas en forme)

Schéma actuel conservé à l'identique (`match_id PK = fixture_id API-Football`, `date`,
`competition_id`, `competition`, `saison`, `home_id/home`, `away_id/away`, `arbitre`, `statut`,
`home_score/away_score`). Clé unique déjà correcte : `match_id` seul (pas de risque de doublon
cross-saison puisque l'ID API-Football est globalement unique, pas réutilisé par saison).

**Aucun changement de structure nécessaire** — le seul travail restant est d'étendre la
COUVERTURE (plus de championnats, plus de saisons), pas le schéma. Voir `docs/plan_importation.md`.

## 5. Statistiques détaillées — `hist_matchs.stats` (JSON, déjà adéquat)

Le bloc JSON `{"home": {...}, "away": {...}}` est suffisant et déjà consommé par
`moteur/features.py`/`moteur/modeles/marches.py`. Pas de normalisation en colonnes séparées
proposée : le jeu de statistiques disponibles varie selon la ligue/la saison/le plan API, et un
schéma JSON flexible évite une migration à chaque nouvelle statistique découverte. **Règle à
documenter explicitement dans le code (déjà en partie présente)** : une clé absente signifie
"non fournie par la source", jamais une valeur par défaut (0, null traité comme 0, etc.) — déjà
respecté par `historique.py:_stats_par_equipe`.

## 6. Cotes horodatées avant le coup d'envoi — vide réel, deux cas à distinguer

Il faut distinguer deux besoins différents, actuellement mélangés dans la seule table `hist_cotes` :

**(a) Capture prospective temps réel** (déjà existante, `hist_cotes`) : ce que bet_agent voit
AU MOMENT d'un run réel, pour mesurer le ROI futur des prédictions produites à partir de
2026-10-10. Schéma conservé à l'identique — c'est la bonne table pour ce besoin, elle fonctionne.

**(b) Cotes historiques rétroactives pour les saisons passées (2023-2025)** : **n'existe nulle
part**, et ne PEUT PAS être reconstituée à partir de `hist_cotes` (qui ne capture qu'en temps réel
depuis le 10/10/2026) ni d'OddsPapi (fournisseur de cotes live, pas d'archive historique connue
dans ce dépôt). Si une source légitime de cotes historiques horodatées est identifiée et autorisée
(voir `docs/plan_importation.md`), proposition de table **additive**, jamais fusionnée avec
`hist_cotes` (sémantique différente : capturée rétroactivement vs. vue en temps réel) :

```sql
CREATE TABLE hist_cotes_archive (
    id              SERIAL PRIMARY KEY,
    match_id        INTEGER REFERENCES hist_matchs(match_id) ON DELETE CASCADE,
    bookmaker       VARCHAR(60) NOT NULL,
    marche          VARCHAR(120) NOT NULL,
    ligne           DOUBLE PRECISION,
    selection       VARCHAR(64) NOT NULL,
    cote            DOUBLE PRECISION NOT NULL,
    horodatage_cote TIMESTAMPTZ NOT NULL,     -- heure RÉELLE de la cote, pas l'heure d'import
    source          VARCHAR(60) NOT NULL,     -- nom du fournisseur, pour tracer la provenance
    importe_le      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (match_id, bookmaker, marche, ligne, selection, horodatage_cote)
);
CREATE INDEX ix_hist_cotes_archive_match ON hist_cotes_archive(match_id);
CREATE INDEX ix_hist_cotes_archive_horodatage ON hist_cotes_archive(horodatage_cote);
```
Règle d'upsert : `ON CONFLICT (match_id, bookmaker, marche, ligne, selection, horodatage_cote) DO
NOTHING` — une cote historique est un fait immuable, jamais mise à jour, seulement ajoutée.
**Cette table n'est qu'une proposition, elle ne doit être créée qu'après identification d'une
source réelle et autorisation explicite — voir le blocage documenté dans `plan_importation.md`.**

## 7. Prédictions historiques — `hist_predictions` (déjà adéquate, jamais alimentée)

Schéma déjà complet et aligné sur `moteur.contrat` (`raw_probability`, `probability`,
`calibrated`, `odds`, `implied_probability`, `edge`, `model_version`, `features_version`...).
Aucun changement de structure. **Clé unique manquante à ajouter** pour permettre un upsert sûr
lors de ré-exécutions de backtest (actuellement aucune contrainte d'unicité) :

```sql
ALTER TABLE hist_predictions
    ADD CONSTRAINT uq_hist_predictions_candidat
    UNIQUE (match_id, model, marche, ligne, selection, model_version);
```
Ceci permet un `ON CONFLICT ... DO UPDATE` idempotent si un backtest est relancé avec la même
version de modèle, sans dupliquer les lignes ni devoir tout supprimer avant de ré-importer.

## 8. Décisions du moteur — `hist_decisions_centrales` (déjà adéquate)

Déjà une ligne par run réel, déjà `UNIQUE(run_id)`. Aucun changement. Hors périmètre direct du
backtest historique multi-saison (c'est un journal du mode shadow du pipeline temps réel), gardé
ici pour mémoire de l'architecture globale.

## 9. Résultats des paris et règlement — réutiliser `bet_agent/verifier_resultats.py`

Pas de nouvelle table : le règlement d'un backtest historique doit réutiliser **exactement** les
fonctions déjà utilisées en production pour juger un pari réel (`grader_pick`, `grader_pick_stat`,
`statut_coupon`) — appliquées à `hist_matchs.home_score/away_score`/`stats` au lieu des résultats
API-Football temps réel. C'est déjà ce que fait `bet_agent/backtest_production.py` pour les
marchés basés sur les buts. Le résultat d'un backtest doit s'écrire dans `hist_predictions.decision`
(déjà prévu dans le schéma), jamais dans une nouvelle table parallèle.

## 10. Résumé des changements de schéma proposés

| Changement | Type | Urgence | Autorisation nécessaire |
|---|---|---|---|
| Ajouter une contrainte unique sur `hist_predictions` | migration additive, non destructive | Faible (seulement utile quand `hist_predictions` sera réellement alimentée) | Oui — toute migration reste soumise à autorisation explicite, non appliquée dans cette mission |
| Créer `hist_cotes_archive` | nouvelle table | Faible — seulement si une source de cotes historiques est trouvée et autorisée | Oui, + autorisation de la source de données elle-même |
| Table `competitions`/`equipes` normalisées | optionnelle | Très faible — pas de besoin fonctionnel démontré | N/A (non recommandé pour l'instant) |

**Aucune migration n'a été appliquée par cette mission.** Ce document est une proposition à
valider, pas un changement effectué.
