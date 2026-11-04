# Phase 2 — Rapport final (2026-11-04)

Branche : `claude/phase2-audit-comparaison` (rien dans `main`, aucune dépense, aucun pari, aucune donnée historique modifiée).
Tout ce qui suit vient de runs réels (GitHub Actions, lecture seule) ; les limites sont indiquées à chaque point.

## 1. Référence aléatoire (reproductible)
Définition : la stratégie choisit des paris ; la référence rejoue 1 000 fois le MÊME problème (mêmes matchs, mêmes marchés, mêmes dates donc même
ordre pour le drawdown, même nombre de paris par match×marché, même fourchette de cotes) en tirant la sélection au hasard. Graine fixe (2026),
code `bet_agent/phase2_reference.py`, 5 tests. Les 10 premières simulations et les IC95 sont affichés dans les logs.

**A. Walk-forward Football-Data, 5 ligues, 5 999 matchs, règle « proba(modèle Dixon-Coles) ≥ proba juste d'ouverture + 3 points », cotes d'ouverture Pinnacle :**

| Marché | Stratégie : ROI [IC95 bootstrap] / CLV | Aléatoire : ROI moyen [IC95] / CLV moyen [IC95] | Rang de la stratégie |
|---|---|---|---|
| 1X2 (n=4 472) | −13,2 % [−17,9 ; −8,5] / −3,6 % | −6,9 % [−10,8 ; −2,8] / −3,0 % [−3,2 ; −2,8] | meilleure que 0 % des simulations : **pire que le hasard** |
| 1X2, 35 % modèle + 65 % ouverture (n=997) | −12,5 % [−21,7 ; −2,8] / −3,5 % | −5,7 % [−14,2 ; +2,8] | 6e percentile : pire que le hasard |
| Over/Under 2,5 (n=3 762) | −4,0 % [−7,5 ; −0,9] / −3,3 % | −3,4 % [−6,6 ; −0,1] / −3,3 % | 37e percentile : indiscernable du hasard |
| Handicap asiatique, demi-lignes (n=1 023) | +3,0 % [−3,0 ; +9,1] / −0,3 % | −1,8 % [−7,8 ; +4,2] / −2,1 % [−2,5 ; −1,7] | 94e percentile (p=0,06) ; CLV hors de l'IC du hasard |
| Handicap, 35 % modèle + 65 % ouverture (n=461) | +0,4 % [−8,8 ; +9,4] / +0,5 % | −0,8 % [−9,5 ; +7,8] / −1,8 % [−2,4 ; −1,3] | 60e percentile |

Lecture : le modèle n'a **aucun avantage démontré** en 1X2 (il est même significativement pire) ni en Over/Under. Au handicap asiatique, un signal faible
et non significatif apparaît (ROI) avec un CLV meilleur que le hasard ; avec 3 marchés × 2 stratégies testés, il faut le traiter comme une hypothèse à
confirmer hors échantillon, pas comme un edge. Par championnat (handicap, modèle seul) : D1 +14,7 %, E0 +4,7 %, SP1 +6,0 %, I1 −0,5 %, F1 −6,7 % (n=157-227 chacun, bruit élevé).

**B. Règle de production rejouée (marge de valeur finale ≥ 0, cotes 1,25-3,00), 399 paris :** ROI −8,5 % [−17,6 ; +0,7] contre hasard −5,3 % [−13,7 ; +2,8] ; 22e percentile,
indiscernable du hasard. Drawdown 48,0 u (hasard 35,1 u [14,1 ; 61,9]).

## 2. Comparaison du moteur de production avec Pinnacle
Méthode : le vrai moteur (`agent3_calcul_pool_candidats`, aucun code modifié) est rejoué sur la collecte brute archivée de chaque run terminé depuis le 22/10 :
30 runs sur 31 (le run 201 : archive introuvable, HTTP 500), 140 matchs, 22 752 paris candidats distincts (dernière collecte par match×marché×sélection).
Pour chaque pari : probabilité du modèle de production SEUL, marché 1xBet sans marge (au moment de la collecte), résultat final de production (65 % marché + 35 % modèle).
Résultats réels : score Football-Data (match terminé). Référence : Pinnacle clôture (1X2) ; **Over/Under et handicap : Pinnacle est absent des fichiers 2026/27
(vérifié par recensement des colonnes), repli sur la clôture Bet365, source indiquée**. 73 des 140 matchs ont été retrouvés dans les 5 championnats (date ±1 jour, noms ≥ 80/100) ;
les 67 autres sont hors des 5 championnats (Ligue des champions, Europa League, divisions inférieures…), pas des échecs de rapprochement.
Limite d'échéance : les probabilités de production datent de la collecte (quelques heures avant le match), la clôture de la référence est au coup d'envoi.

## 3. Les quatre approches (mêmes événements, même résultat ; Brier plus bas = mieux ; Δ apparié ± erreur type)
**Tous marchés communs, 301 événements :**

| Approche | Brier | Log-loss | Δ vs référence |
|---|---|---|---|
| Référence (Pinnacle 1X2 ; Bet365 O/U-AH) | 0,2046 | 0,5942 | — |
| Marché 1xBet seul | 0,2078 | 0,6016 | +0,0032 ± 0,0012 |
| Modèle de production 35 % + référence 65 % | 0,2071 | 0,6003 | +0,0025 ± 0,0013 |
| Production final (65 % 1xBet + 35 % modèle) | 0,2093 | 0,6053 | +0,0047 ± 0,0017 |
| Modèle de production seul | 0,2150 | 0,6183 | +0,0104 ± 0,0037 |
| Référence aléatoire (taux de base constant, en échantillon) | 0,2376 | 0,6682 | +0,0330 ± 0,0075 |

Classement stable : référence sharp < marché 1xBet < final de production < modèle seul < aléatoire. Sur les **2 711 paris jugés** (sans exigence de référence), le final de production
est moins bon que le marché 1xBet seul : +0,0014 ± 0,0004 (≈ 3,5 σ) ; le modèle seul : 0,1707 contre 0,1638 pour le marché. Le poids de 35 % du modèle dégrade donc légèrement la probabilité.
(Test walk-forward indépendant sur 5 999 matchs, autre modèle : même sens.) Réserve : un seul mois de matchs, un seul fichier de référence par marché.

## 4. Résultats par marché
* **Double chance** (219 événements) : référence 0,1916 ; 1xBet +0,0025 ; final +0,0042 ± 0,0016 ; modèle +0,0100 ± 0,0039.
* **Total** (73 événements, ligne 2,5, référence Bet365) : référence 0,2371 ; 1xBet +0,0036 ± 0,0032 ; final +0,0060 ± 0,0045 ; modèle +0,0137 ± 0,0089. Le hasard (taux de base) est proche : marché presque 50/50.
* **Handicap** : seulement **9** événements communs (la référence ne couvre que la ligne principale, la production en choisit d'autres) → **non concluant**.
* Production vs 1xBet, tous les paris (Brier final − 1xBet) : Handicap +0,0018 ± 0,0009 (n=497) ; Total +0,0010 ± 0,0006 (n=813) ; Total équipe 1 +0,0017 ± 0,0011 ; Total équipe 2 +0,0010 ± 0,0010 ; BTTS +0,0023 ± 0,0024 (n=73).
* Par championnat (événements communs) : D1 (60) le modèle seul égale la référence (+0,0005 ± 0,0070) ; E0 (69) +0,0094 ± 0,0098 ; F1 (37) +0,0115 ± 0,0097 ; I1 (82) +0,0138 ± 0,0061 ; SP1 (53) +0,0170 ± 0,0089.
* ROI simulé de la règle de production par marché (n, ROI) : Double chance 27, −23,4 % ; Handicap 91, −13,2 % ; Total 135, −5,0 % ; Total équipe 1 62, −4,1 % ; Total équipe 2 52, −11,0 %.
  Par championnat : D1 +0,8 % ; E0 +4,6 % ; F1 +14,3 % ; I1 −43,2 % ; SP1 −5,5 % (très variable, IC non significatifs).

## 5. Calibration
* Production rejouée (2 711 paris) : ECE final 0,0207 ; marché 1xBet 0,0257. Tranches du final : 0-10 % annoncé 8 → réel 8 ; 10-20 : 15 → 13 ; 20-30 : 25 → 24 ; 30-40 : 35 → 29 ; 40-50 : 45 → 40 ;
  50-60 : 54 → 52 ; 60-70 : 65 → 64 ; 70-80 : 75 → 72 ; 80-90 : 85 → 86 ; 90-100 : 92 → 93. Légère surestimation entre 30 % et 50 % ; bonne calibration au-dessus. Une calibration correcte (ECE bas) n'implique pas un meilleur Brier : le final reste moins bon que le marché.
* Walk-forward (5 999 matchs) : 1X2 modèle ECE 0,008 / marché 0,010 (correct) ; O/U 0,016 / 0,015 ; **handicap : modèle ECE 0,055** (ses écarts avec la ligne sont du bruit : ex. « 70-80 % » réalisé 46 %).
* Erreurs de prédiction : nuls observés 24,9 % (Poisson 23,5 %, Dixon-Coles 24,7 %) ; écarts ≥ 3 buts 16,1 % (modèles 16,9 %) ; totaux ≥ 5 : 15,7 % (16,2 %) ; totaux ≤ 1 : 22,8 % (23,4-24,1 %). Dixon-Coles corrige les nuls ; la binomiale négative = Poisson (pas de sur-dispersion une fois la force des équipes prise en compte).

## 6. Closing Line Value
* Walk-forward : CLV des paris du modèle à l'ouverture : 1X2 −3,6 %, O/U −3,3 %, handicap −0,3 % ; hasard : −3,0 %, −3,3 %, −2,1 %. Seul le handicap sort de l'IC du hasard (CLV −0,3 % contre [−2,5 ; −1,7]).
  Un pari aveugle perd environ la marge de la maison : un CLV négatif n'est donc pas anormal, la comparaison pertinente est « stratégie contre hasard ».
* Production : CLV −3,10 % sur les 72 paris de la règle ayant une référence (hasard −2,63 % [−3,8 ; −1,5]) → dans l'intervalle du hasard. Handicap −2,3 % ; Total −3,6 %. EV annoncée par le moteur +3,51 % contre EV au prix juste de la référence −3,10 % : **l'espérance annoncée n'est pas confirmée par le marché**.

## 7. Audit des données historiques (causes)
* `hist_predictions` vide : aucune écriture dans le code (seul le schéma `HistPrediction` existe, aucun appel) — jamais branché ; les probabilités modèle seul / marché seul ne sont pas conservées par jambe.
* `cotes` sans horodatage par ligne : la table n'a pas de colonne de date ; un horodatage **indirect** existe (cotes.match_id → matchs.run_id → runs.lance_le) mais les matchs purgés rompent le lien (357 jambes pointent vers des matchs qui n'existent plus).
* `hist_cotes` : 35 887 lignes les 10-12 octobre seulement, `bookmaker` toujours NULL (colonne morte), 0 jugée ; pourquoi la capture s'est arrêtée après le 12/10 : non établi (à diagnostiquer).
* 479 jambes non vérifiables : 190 + 91 le 1-2 octobre (matchs sans score à l'époque), 156 sur des matchs supprimés, ~20 fin septembre, le reste isolé ; par famille : corners 136/294 et cartons 41/121 (statistiques détaillées API-Football indisponibles), buts/résultat 302. Depuis le 17/10 : 1 seule jambe non vérifiable hors corners/cartons (le bug « double chance 12 » a été corrigé le 17/10).
* 98 runs abandonnés/en erreur : 29 « aucun match avec marchés 1xBet » (26/09-16/10), 19 interrompus après 2 h (job arrêté), 9 libellés « abandonné » alors que le détail dit « terminé » (20-30/10), 8 « aucun profil valable », 3 DataError `VARCHAR(32)` sur `cotes` (la longueur maximale de `marche_id` est exactement 32), 3 DeepSeek HTTP 402 solde insuffisant (22-24/10), ~27 causes isolées.
* `hist_matchs` : 8 849 lignes, 0 doublon, 0 match terminé sans score, mais figée au 17/10 ; scores des autres matchs absents de `matchs` (seuls les matchs de coupons sont scorés), d'où l'usage de Football-Data pour juger.
* Football-Data 2026/27 : Pinnacle seulement en 1X2 ; pas d'Over/Under ni de handicap Pinnacle ; clôture Bet365 disponible.

## 8. Corrections recommandées (aucune appliquée sans accord)
1. Élargir `cotes.marche_id` (VARCHAR 32 → 64, non destructif) ou tronquer proprement. 2. Corriger le libellé des runs terminés marqués « abandonné » et ajouter un garde-fou « zombie » (arrêt/relance propre après 2 h).
3. Ajouter, de façon additive, `proba_modele_seul_pct`, `proba_marche_pct` et l'horodatage de collecte aux jambes/cotes, et brancher l'écriture de `hist_predictions`.
4. Ne plus purger les matchs référencés par des jambes (ou copier coup d'envoi/score dans la jambe). 5. Enregistrer les scores de tous les matchs collectés (Football-Data/ API-Football), pas seulement ceux des coupons.
6. Poids du modèle : tous les tests (5 999 matchs, 2 711 paris) disent que 35 % dégrade la probabilité ; tester 0-15 % et Dixon-Coles hors échantillon avant toute décision (non modifié).
7. Handicap : ne pas sélectionner d'après l'écart modèle-ligne (modèle mal calibré à cet endroit) ; étudier des signaux indépendants. 8. Corners/cartons : tant que les statistiques API-Football manquent, les marquer « non évaluables » plutôt qu'« en attente ».
9. Remplacer Poisson par Dixon-Coles pour le 1X2 (nuls). 10. Valider les conditions d'utilisation de chaque source avant automatisation (voir 10).

## 9. État de la collecte toutes les six heures
* **Elle ne tourne pas encore** : un `cron` GitHub ne s'exécute que depuis la branche par défaut ; `phase2.yml` n'est que sur la branche de travail. Seules 4 exécutions manuelles ont eu lieu.
* Journal `captures_gratuites_journal` (3 lignes) : #1 et #2 `vide` (code antérieur : le fichier `fixtures.csv` de 5 428 octets ne contenait que 17 matchs de B1/E1/E2/E3 des 3-4/11, aucun des 5 championnats) ; #3 `sans_match_cible` (comportement normal en milieu de semaine, exit 0).
* Validé par tests unitaires (184 tests verts) : dédoublonnage par « changement seulement », horodatage UTC, provenance (URL + empreinte SHA-256 du fichier), journal de chaque tentative, échec bruyant, BOM, ré-essais en cas de verrou base.
  Un blocage (deadlock) est survenu quand j'ai lancé deux jobs en parallèle : corrigé par ré-essais, et je ne parallélise plus.
* **Non encore validé en conditions réelles** : l'insertion de vraies cotes (aucune ligne des 5 championnats dans le fichier à ce jour), donc ni le dédoublonnage réel, ni la qualité des cotes, ni la conservation de l'historique sur plusieurs passes. Le prochain essai utile : un week-end (vendredi/samedi) quand le fichier contiendra les matchs.
* Limite de la source : `fixtures.csv` donne l'ouverture/valeur courante, pas des instantanés réguliers ; les cotes de clôture viennent des fichiers de résultats (Football-Data).

## 10. Décisions nécessaires pour la suite
1. Fusion de la capture (workflow `phase2.yml` + tables additives) dans `main` pour activer le cron ? (non fait, en attente de votre accord après vérification de la fiabilité) — ou continuer par lancements manuels le week-end.
2. Understat : envoyer le brouillon `docs/understat-demande-autorisation.md` (à votre nom) ; aucune collecte tant que la confirmation écrite n'est pas reçue (verrou en place).
3. Football-Data : les données anglaises/écossaises relèvent de Football DataCo (licence pour usage commercial/paris) ; les conditions du site .co.uk n'ont pas pu être lues. Statut « à vérifier » dans le registre `sources_donnees`. Souhaitez-vous que j'étudie les conditions et alternatives ?
4. Autoriser les corrections additives de schéma (point 8.1 et 8.3) sur une branche de travail ?
5. Autoriser des tests de poids du modèle (0-15 %) et Dixon-Coles en walk-forward hors échantillon ?
6. Approuver (ou non) le passage à la Phase 3. **Je ne le lance pas sans votre approbation explicite.**
