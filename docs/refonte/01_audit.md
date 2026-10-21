# Audit complet — 21/10/2026

Périmètre : `bet_agent/` (production), `moteur/` (modèles + backtest), `moteur_central/` (arbitrage
des deux moteurs), `backend/` (API, persistance, vérification), workflows GitHub Actions, base
Supabase (lecture seule). Aucune modification de `main`, aucune écriture Supabase, aucun envoi Telegram.

## 1. État des lieux (chiffres mesurés)

| Élément | Constat |
|---|---|
| Code de production | `bet_agent/analyser_et_envoyer.py` : 3 511 lignes (probabilités, parsing des marchés, clients IA, Telegram, sélection, rédaction) ; `collecte_donnees.py` : 1 989 lignes |
| Deux moteurs de probabilité | `bet_agent` (production, Poisson, formules propres) et `moteur/` (backtest, 11 modèles, binomiale négative, issues à 5 états). Ils ne partagent **aucune** fonction de calcul |
| Trois pipelines de sélection | `deterministe` (selectionner_combo_cote_cible), `central` (moteur_central), `agent` (IA, défaut) |
| Historique | `hist_matchs` : 8 849 matchs, **5 championnats seulement** (L1, PL, Liga, Serie A, Bundesliga), 7 418 terminés, stats complètes (tirs, fautes, corners : 7 417 ; cartons : 7 205 ; arbitre : 7 443) |
| Cotes historiques | `hist_cotes` : 35 887 lignes, **du 10 au 12/10/2026 seulement**. `cotes` (production, 919 039 lignes) **n'a pas d'horodatage** (colonnes : id, match_id, marche_id, marche, handicap, periode, selection, cote) |
| Vérité terrain de l'EV | uniquement `jambes` jouées : 1 315 lignes, dont **476 `non_verifiable` (36 %)**, 23 `push`, 45 `en_attente` |
| Tests | 744 tests passent (bet_agent, backend, moteur, moteur_central) |

## 2. Bugs et incohérences de calcul

| # | Gravité | Problème | État |
|---|---|---|---|
| C1 | Critique | Sommes de Poisson figées à 25 événements : pour fautes/tirs (μ≈22–26) P(Over 25,5 \| μ=26) = 0,0 ⇒ tout « Under » surestimé. Cause réelle du Total Tirs à 50 % réel / 69 % annoncé | **Corrigé (PR #81)** |
| C2 | Majeur | Surdispersion ignorée en production (Poisson pur pour corners/tirs/fautes). Mesure : variance/moyenne des totaux = corners 1,16 ; tirs 1,34 ; cadrés 1,10 ; fautes 1,23 ; buts 0,98 ; cartons 0,98 | **Corrigé (PR #81)** : binomiale négative |
| C3 | Majeur | Push compté comme `p_gain + 0,5·p_push` : l'EV réelle d'un remboursement est `p_gain·c + p_push − 1`. Écart = `p_push·(0,5c − 1)` (≠ 0 dès que c ≠ 2). Touche les lignes entières/quart (handicap, totaux) | À corriger (phase 1) — `moteur/modeles/marches.esperance` est déjà exact |
| C4 | Majeur | xG de forme = moyenne tous lieux confondus ⇒ **aucun avantage du terrain** (réel : 1,45 vs 1,22 but sur 7 110 matchs) ; seul l'Elo (poids 0,4) en apporte | Backtest lancé (`backtest-avantage-domicile`) |
| C5 | Majeur | Probabilité affichée = 0,35·modèle + 0,65·marché sans marge ⇒ l' « edge » stocké est un edge **rétréci**, pas une EV : moyenne annoncée entre −7 % et +20 % selon la catégorie, indépendante du rendement réel | À redéfinir (phase 4) |
| C6 | Majeur | Production couvre Ligue des champions/Europa/autres (ex. Galatasaray, Viking FK, LASK) mais `moteur/` ne sait prédire que les 5 championnats de `hist_matchs` (priors de ligue indisponibles) | Conception : modèles indépendants de la compétition + priors par défaut |
| C7 | Moyen | 36 % des jambes `non_verifiable` (corners/cartons sans stats finales, catégories sans règle de jugement) : le suivi de performance est aveugle sur un tiers des paris | À traiter (phase 3) |
| C8 | Moyen | Jugement des résultats dupliqué : `verifier_resultats.juger_resultat` et `moteur.modeles.registre.issue_reelle` (deux implémentations des mêmes règles) | À unifier |
| C9 | Moyen | Trois chaînes de repli pour les buts attendus (stats saison, 10 derniers matchs, estimation depuis les cotes) avec des sémantiques différentes ; la dernière est circulaire (utilise les cotes pour estimer ce qu'on compare aux cotes) | À encadrer |
| C10 | Mineur | Code mort : `_edge_calculable(edge, proba)` ignore `proba` ; constantes Elo dupliquées (`moteur/features.py`, `analyser_et_envoyer.py`) | À nettoyer |
| C11 | Mineur | Lissage : priors fixes (buts 1,3 ; ligue réelle 1,45/1,22) ⇒ biais domicile/extérieur sur petit échantillon | À mesurer avec C4 |

Vérifié correct : `issue_ligne`/`issue_total`/handicap référencé domicile (`moteur/modeles/marches.py`),
Poisson indépendant (nul réel 26,4 % vs 25,8 % prédit : **pas** de Dixon-Coles nécessaire),
dé-marge des cotes (normalisation multiplicative ; Double Chance normalisée à 2),
absence de fuite du futur dans `moteur/features.py` (test dédié).

## 3. Performances réelles en production (jambes distinctes, envoyées, jugées)

| Catégorie | n | Réel | Annoncé | ROI réel |
|---|---|---|---|---|
| Total (buts) | 89 | 71,9 % | 67,5 % | +7,4 % |
| Total Équipe 1 / 2 | 65 / 49 | 64,6 % / 73,5 % | 66,3 % / 68,4 % | +5,9 % / +8,7 % |
| Double Chance | 47 | 61,7 % | 69,3 % | −7,4 % |
| Handicap | 31 | 58,1 % | 67,4 % | −22,5 % |
| Total Corners | 28 | 67,9 % | 71,4 % | −7,3 % |
| Total Tirs | 26 | 53,8 % | 68,3 % | −6,6 % |
| Total Cartons | 17 | 47,1 % | 67,2 % | −34,9 % |
| BTTS | 16 | 50,0 % | 59,7 % | −21,6 % |

Lecture : les marchés de **buts** sont bien calibrés et rentables sur l'échantillon ; handicap, cartons,
BTTS, Double Chance sont sur-estimés. Échantillons petits : à confirmer, pas à sur-interpréter.

## 4. Dette structurelle

1. Un fichier de 3,5 k lignes mélange cinq responsabilités (calcul, collecte de marché, IA, Telegram, sélection).
2. Duplication : probabilités ×2, jugement ×2, métriques ×2 (`moteur.backtest.metriques`, `moteur_central.metriques`), sélection ×4.
3. Le backtest (`moteur/`) ne teste pas ce qui tourne en production (`bet_agent`) : **la cohérence backtest ↔ production n'est pas garantie**. Les ~12 backtests de `diagnostics.yml` réimplémentent en ligne le modèle de production.
4. Aucune interface commune pour un « modèle de marché » : données requises, paramètres, validation sont implicites.
5. Contrainte de données : pas d'historique de cotes ⇒ pas de backtest ROI rétrospectif crédible au-delà de 3 jours. L'EV ne peut être validée qu'en avant (forward) à partir de `jambes`.
