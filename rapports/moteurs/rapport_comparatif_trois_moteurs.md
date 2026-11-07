# Mise à niveau des trois moteurs — rapport comparatif (07/11/2026)

**Verdict : AUCUN moteur n'est déclaré meilleur.** Il n'existe pas de résultats réglés par moteur (agent, central, déterministe) sur les mêmes matchs, et aucun backtest réel hors échantillon n'a pu être exécuté dans cet environnement (pas d'accès aux données historiques ni à la base). Ce qui est livré : trois moteurs opérationnels et comparables, et l'outillage pour les départager sur des résultats réglés.

## 1. Audit des architectures avant modification

| | Agent (IA) | Central | Déterministe |
|---|---|---|---|
| Entrée | catalogue Python (probabilité = 35 % modèle + 65 % marché sans marge, cotes 1xBet) | même pool, candidats « bet_agent » ou « moteur » (arbitrage par marché sur le ROI historique jugé) | même pool |
| Sélection (avant) | l'IA choisit, Python valide (`agent_strategie.valider`), vote entre modèles | recherche exhaustive **dans une bande de cote** (`COTE_MIN/MAX_CENTRAL`), **6 jambes fixes**, coupons « central_N » sans notion de risque | Monte Carlo `selectionner_combo_cote_cible` **visant une bande de cote**, un seul coupon « jour » ou nombre dynamique de coupons |
| Profils (avant) | trois profils de risque (depuis le 07/11) | aucun | aucun |
| Points faibles constatés | coût IA, probabilité surtout issue du marché | score à poids égaux non validé, cote cible, taille fixe, tirage sans corrélation | cote cible, hasard (Monte Carlo), validation par IA (agent 35) |
| Tests avant | oui | oui (59) | partiels |

Constat commun : la probabilité de départ est la même pour les trois (mélange 35/65), donc les moteurs ne diffèrent que par la **sélection**. Dixon-Coles n'est pas utilisé en production (`rho_dixon_coles = 0`) ; je ne l'ai pas activé faute de validation statistique.

## 2. Ce qui a été fait
- **Base commune** `moteur/profils_risque.py` : les trois profils (prudent, équilibré, risque), règles de cohérence identiques pour les trois moteurs (un pari par match, 2 jambes minimum, diversité famille/sens, un match dans un seul coupon, coupons distincts), probabilité jointe avec correction de corrélation approchée (4 % par paire « même compétition, même famille, même sens »), plancher de sécurité de probabilité jointe pour le profil risque (2 %). **Aucune cote totale ni individuelle n'est ciblée.**
- **Moteur déterministe** `bet_agent/moteur_deterministe.py` : règles Python, répartition des matchs par tours entre les profils, tailles de référence 3 / 4 / 5 jambes bornées par les matchs disponibles, abstention explicite sinon, résultat reproductible (aucun hasard). Branché : `ae.generer_coupons(donnees, profils=...)`.
- **Moteur central** `moteur_central/profils.py` : recherche exhaustive de la meilleure combinaison par profil (utilité du coupon entier : probabilité jointe et cote totale pondérées selon le profil), probabilité calibrée prioritaire, atténuation (≤ 20 %) vers 0,5 quand le Brier historique du marché dépasse 0,25. Branché : `executer_moteur_central(..., profils=...)`.
- **Évaluation** `moteur/evaluation.py` : Brier, log loss, table de calibration, ROI, performance face au marché (Brier du moteur contre Brier de la probabilité implicite), métriques par marché avec seuil d'échantillon, comparaison sur les **mêmes paris** uniquement, stabilité par jour, backtest chronologique hors échantillon (calibration ajustée sur la première moitié, évaluée sur la seconde), forces et faiblesses générées automatiquement, aucun classement sous 100 paris communs réglés. Script `outils/comparer_moteurs.py` (JSON de paris réglés → rapport).
- **Workflow** : le formulaire propose `agent` (défaut), `central`, `deterministe` ; le préparateur transmet les mêmes trois profils aux trois moteurs ; seul l'agent a un pilote IA et un vote ; les deux autres n'appellent aucune IA payante. Les crons n'ont pas été modifiés.

## 3. Comparaison de structure (catalogue SYNTHÉTIQUE de 12 matchs × 4 marchés — ce ne sont PAS des résultats)
| Profil | Déterministe : jambes / cote / proba jointe | Central : jambes / cote / proba jointe |
|---|---|---|
| Prudent | 3 / 3,04 / 0,334 | 2 / 1,69 / 0,585 |
| Équilibré | 4 / 14,29 / 0,081 | 2 / 3,24 / 0,342 |
| Risque | 5 / 28,66 / 0,039 | 6 / 57,01 / 0,020 |
Les deux moteurs produisent des coupons de plus en plus risqués du prudent au risque, mais avec des logiques différentes (le central optimise l'utilité du coupon entier et choisit lui-même la taille ; le déterministe applique une taille de référence). L'agent (IA) n'a pas été exécuté (aucun appel payant) : sa sortie est validée par les mêmes règles Python, et un test prouve que les coupons des deux autres moteurs passent cette validation.

## 4. Tests
1 291 tests locaux réussis, 0 échec, sans réseau ni clé : `moteur` 75, `moteur_central` 68, `bet_agent` 768, `backend/tests` 353, `tests` 27. Nouveaux : 57 tests (base commune et évaluation 26, central 9, déterministe 8, intégration des trois moteurs 11, script de comparaison 3), plus l'adaptation de 4 tests existants (signature des faux moteurs, profils transmis aux trois moteurs). Les tests d'intégration vérifient que les trois moteurs reçoivent les mêmes profils, ne se replient jamais l'un sur l'autre, n'inventent aucune jambe ni cote, respectent un match par coupon et que le formulaire propose chaque moteur. Ils ne prouvent aucune rentabilité prédictive.

## 5. Limites et suite
1. **Pas de backtest réel** : il faut des paris réglés par moteur (même jour, mêmes matchs). Procédure : lancer les trois moteurs en mode essai (sans Telegram) chaque jour, enregistrer les coupons, régler après les matchs, exporter en JSON, puis `python outils/comparer_moteurs.py observations.json`. La comparaison n'est autorisée qu'à partir de 100 paris communs réglés ; au niveau coupon il en faut davantage (les paris d'un même coupon sont corrélés).
2. **Les améliorations de probabilité du central sont des heuristiques non validées** (atténuation par le Brier historique, correction de corrélation de 4 %, poids des utilités par profil). Elles doivent être jugées par le backtest ci-dessus avant d'être conservées.
3. **Dixon-Coles et calibration isotone** : non activés en production ; la calibration reste soumise au seuil `calibration_min_n` de `moteur/config.py`.
4. L'ordre de traitement des profils (prudent d'abord) donne les meilleurs matchs au prudent ; à réévaluer si les résultats montrent un biais.
5. Les paris d'un même coupon et les coupons d'un même jour partagent des matchs/ligues : les intervalles de confiance doivent être calculés par grappe (jour/match), pas par pari.
6. **Planchers de rémunération communs** (ajoutés au moment de la livraison, 07/11/2026) : les trois moteurs refusent une jambe sous 1.20 et un coupon sous 1.60 de cote totale (mêmes variables `COTE_MIN_JAMBE_AGENT` et `COTE_TOTALE_MIN_COUPON`, 0 = désactivé) ; ce sont des planchers de sécurité, pas des cibles. Un pool qui n'offre que des cotes minuscules donne une abstention expliquée.
7. Ces changements sont livrés sur `main` ; le moteur par défaut du cron reste `agent`, les moteurs `central` et `deterministe` ne tournent que lorsqu'on les choisit dans le formulaire.
