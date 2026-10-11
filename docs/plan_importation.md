# Plan d'importation — historique 5 championnats

Ce plan ne propose **aucune importation massive immédiate** : conformément au périmètre de la
mission, aucune donnée n'a été téléchargée ou importée pendant cette session. Il documente les
sources identifiées, ce qui est déjà outillé, ce qui reste à construire, et les blocages réels.

## 1. Sources déjà présentes et autorisées dans le dépôt

### 1.1 API-Football (clé `API_FOOTBALL_KEY`, plan Pro depuis le 30/09/2026)
- **Déjà utilisée** par `backend/app/services/historique.py` pour `hist_matchs` (scores + stats
  finales via `/fixtures` et `/fixtures/statistics`). C'est la source des 760 lignes existantes.
- Plan Pro = 300 appels/min, pas de restriction d'ancienneté de saison connue (`SAISON_MAX_PLAN_
  GRATUIT=2100` par défaut = aucune restriction pratique).
- **Confirmé par audit** : ne fournit PAS de xG pour les fixtures déjà backfillées (0/760) — à
  ne pas présenter comme une source de xG pour les 5 championnats.
- **Endpoint `/odds` (candidat pour les cotes historiques)** : existe et est déjà utilisé en
  lecture par `bet_agent/adaptateur_api_football.py` (`capturer_api_football_adapte`), mais
  **uniquement pour des fixtures du jour en production, jamais testé sur une fixture passée
  dans cette session**. Il est donc **confirmé techniquement accessible par fixture_id** (la
  même clé `match_id` que `hist_matchs`), mais **NON CONFIRMÉ** sur deux points : (a) si l'odds
  renvoyée pour une fixture ancienne est bien la cote PRÉ-match (ou une cote de clôture/un
  instantané non horodaté avec précision), (b) si le plan Pro actuel couvre réellement les
  saisons 2023/2024-2024/2025 déjà backfillées sur cet endpoint précis. **Vérifier ce point
  consommerait du quota réel sur la clé de production — non testé ici, nécessite une
  autorisation explicite avant le premier appel réel.**

### 1.2 OddsPapi (clé actuelle du pipeline temps réel)
- Fournit des cotes **en temps réel uniquement** (confirmé par l'audit `hist_cotes`, qui ne
  capture que depuis le run en cours) — **aucune indication dans le code ou la documentation
  que ce fournisseur propose un archive de cotes historiques**. Ne doit pas être présenté comme
  une source de cotes historiques.

## 2. Ce qui est déjà outillé (réutilisable sans développement)

- `.github/workflows/backfill-historique.yml` + `backend/app/services/historique.py` :
  backfill scores/stats par (ligue, saisons), idempotent (upsert par `match_id`), limite de
  débit déjà gérée (`_respecter_rate_limit_api_football`), option `--sans-stats` et
  `--limite-appels-stats` pour maîtriser le coût en quota. **Déjà prêt pour les 4 championnats
  manquants** — il suffit de le déclencher avec `ligue=140` (La Liga), `135` (Serie A), `78`
  (Bundesliga), `61` (Ligue 1), et les saisons voulues. **Non déclenché dans cette mission**
  (autorisation d'importation non donnée).

## 3. Ce qui manque et doit être construit

| Besoin | État | Risque/coût |
|---|---|---|
| Backfill La Liga/Serie A/Bundesliga/Ligue 1, saisons 2023-2025 | Outil prêt, jamais exécuté pour ces ligues | ~4 ligues × 3 saisons × 380 matchs × 2 appels (fixtures + stats) ≈ 9 000 appels API-Football — à étaler dans le temps (rate limit 300/min, mais mieux vaut garder une marge), coût financier dépendant du plan souscrit (non vérifié ici, voir compte réel) |
| Backfill saison 2025/2026 (en cours) | Même outil, mais saison PAS terminée → matchs à statut mixte (FT/NS/PST) : le backfill gère déjà ce cas (`STATUTS_TERMINES`), mais la saison devra être rebackfillée périodiquement pour récupérer les scores des matchs restants | Faible techniquement, nécessite une re-exécution régulière |
| Cotes historiques horodatées pré-match (2023-2026) | **Aucune source confirmée** dans le dépôt | Bloqué — voir §4 |
| xG pour les 5 championnats | **Non fourni par la source actuelle** (API-Football, plan Pro, confirmé 0/760) | Soit accepter l'absence de xG, soit évaluer une source payante tierce (Understat, FBref, Opta...) — **aucune vérification de droits d'utilisation effectuée, à faire avant tout import** |
| Normalisation ligue/équipe dans `matchs`/`cotes` (production) | Hors périmètre (table de production, non modifiée) | N/A |

## 4. Blocage principal : cotes historiques horodatées

**Aucune source de cotes historiques pré-match horodatées n'est confirmée accessible dans ce
dépôt.** Deux pistes existent mais ne sont PAS validées :
1. API-Football `/odds` sur fixture passée — accessibilité technique probable mais sémantique du
   timestamp non confirmée (voir §1.1). Vérifier nécessite un appel réel (coût quota, autorisation
   requise) avant de pouvoir conclure.
2. Un fournisseur tiers spécialisé (ex. Betfair historical data, OddsPortal archives, Pinnacle
   historical odds API) — **aucun de ces fournisseurs n'est intégré ni mentionné dans ce dépôt**,
   et leur utilisation impliquerait très probablement une licence payante dont les droits
   d'utilisation (revente, usage commercial, fréquence de requêtage) devraient être vérifiés
   avant tout import, conformément à l'instruction explicite de la mission.

**Jusqu'à la levée de ce blocage, aucun backtest avec ROI réel ne peut être calculé sur les
saisons passées** (seule la calibration probabiliste pure — Brier/log-loss sur buts/scores — est
possible sans les cotes, voir `bet_agent/backtest_production.py` déjà existant pour cet usage
restreint).

## 5. Étapes proposées, dans l'ordre, chacune nécessitant une autorisation séparée

1. **Confirmer l'endpoint `/odds` d'API-Football sur une poignée de fixtures déjà backfillées**
   (ex. 5 fixtures de Premier League 2023/2024) — un appel réel, limité, pour vérifier la
   sémantique du timestamp retourné. Coût : quelques appels API, négligeable sur un plan Pro.
   **Nécessite une autorisation explicite avant le premier appel.**
2. Si confirmé utile : backfiller les cotes de Premier League 2023-2025 via cet endpoint avant
   d'étendre aux 4 autres championnats — valider le pipeline sur un périmètre déjà connu.
3. Backfiller scores+stats (déjà outillé) des 4 championnats manquants, saisons 2023-2026,
   avec `--limite-appels-stats` pour contrôler le coût par exécution.
4. Si l'étape 1 échoue ou est jugée insuffisante : évaluer un fournisseur tiers de cotes
   historiques, avec vérification des droits AVANT tout essai d'import.
5. Mettre en place le jugement différé de `hist_cotes` (`juger_cotes_en_attente`, déjà écrit,
   jamais planifié) pour que la capture prospective en cours depuis le 10/10/2026 commence à
   produire un vrai historique ROI au fil du temps, indépendamment des saisons passées.

## 6. Ce qui N'est PAS fait et ne doit pas être présumé fait

- Aucune donnée n'a été importée, aucune requête d'écriture envoyée à Supabase.
- Aucun appel API-Football/OddsPapi réel n'a été effectué pendant cette mission (seules des
  requêtes `SELECT` en lecture sur Supabase ont été exécutées).
- Aucun droit d'utilisation de source tierce n'a été vérifié (aucune source tierce n'a même été
  contactée).
