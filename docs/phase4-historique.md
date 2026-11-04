# Phase 4 — Base historique Football-Data (2026-11-04)

Branche `claude/phase4-historique`. Import **insert-only** de 5 championnats × 11 saisons (2016/17 → 2026/27) dans la table `fd_matchs`
(résultats, mi-temps, arbitre, tirs/cadrés/corners/fautes/cartons, cotes d'ouverture et de clôture), provenance sur chaque ligne (URL + SHA-256 + date de collecte).
Rien n'est supprimé ni modifié ; une relance n'ajoute que les nouveaux matchs. Source « à vérifier » dans le registre (usage de recherche, 1 requête par fichier).

## Qualité mesurée (requêtes SQL sur la base)
* **18 389 matchs**, 0 doublon (clé unique), 0 score aberrant (> 15), dates 2016-08-12 → 2026-11-02, 5 championnats × 11 saisons.
* **Statistiques de match** (tirs, corners, cartons) : **100 %** des matchs sur toute la période → permet de tester des moteurs Tirs / Corners / Cartons sur 10 ans.
* **1X2 Pinnacle** : ouverture 95-96 % et clôture 95-96 % par championnat ; 100 % pour 2016/17 → 2024/25 et 2026/27, mais **51 % en 2025/26** (Pinnacle absent à partir du milieu de saison).
* **Over/Under 2,5 et handicap asiatique** : **aucune cote avant 2019/20** (0 % de 2016/17 à 2018/19) ; 99-100 % de 2019/20 à 2024/25 ; en 2025/26 Pinnacle 51 % mais Bet365 100 % ; en 2026/27 Pinnacle 0 % (Bet365 100 %).
* **Marge Pinnacle 1X2 en clôture** : moyenne 2,73 % (17 533 matchs), min 0,05 %, max 10,2 % ; aucune marge négative ni > 12 %. Quelques marges très basses (< 1 %) sont à surveiller (cotes possiblement ajustées après coup).
* Limites : Bet365 comme repli pour Over/Under et handicap après 2025/26 (moins tranchant que Pinnacle) ; noms d'équipes propres à Football-Data (le rapprochement avec API-Football reste tracé par `mapping_equipes`, à valider).

## Comparaison walk-forward sur 9 saisons (10 791 matchs hors échantillon, test à partir de 2019/20)
(Dixon-Coles / Poisson / binomiale négative ; marché = Pinnacle 1X2, Over/Under et handicap, clôture.)
* **1X2** (n=10 791) : Brier marché 0,5764 ; modèle seul 0,5909 (+0,0145 ± 0,0012) ; mélange 5 % +0,0002 ± 0,0001, 10 % +0,0005 ± 0,0001, 15 % +0,0008 ± 0,0002, 35 % +0,0026 ± 0,0004, 50 % +0,0045 ± 0,0006 → **aucun poids n'améliore le marché ; l'optimum est 0 %**. Calibration : modèle ECE 0,0049, marché 0,0063.
* **Over/Under 2,5** (n=10 644) : marché 0,4751 ; modèle +0,0108 ± 0,0013 ; mélange 5 % +0,0001, 15 % +0,0004 ± 0,0002, 35 % +0,0016 ± 0,0005.
* **Handicap** (n=2 553) : marché 0,4993 ; modèle +0,0153 ± 0,0033 ; mélange 35 % +0,0023 ± 0,0011. Modèle mal calibré (ECE 0,070 contre 0,003 pour le marché).
* Poisson ≈ binomiale négative ; Dixon-Coles légèrement meilleur (nuls : observé 25,3 %, Poisson 23,5 %, Dixon-Coles 24,8 %).
* **Référence aléatoire (1 000 simulations, graine 2026)** — règle « proba modèle ≥ juste d'ouverture + 3 points » :
  1X2 −10,4 % de ROI (n=8 019, IC95 −14,2 à −6,5) contre −4,5 % pour le hasard [−7,8 ; −1,4] : **significativement pire que le hasard** ; CLV −3,35 % (hasard −2,87 %).
  Over/Under −4,1 % contre −3,2 % [−5,5 ; −0,6] (22e percentile) : indiscernable du hasard.
  Handicap : voir l'erratum ci-dessous (corrigé et relancé).

## Erratum — handicap asiatique (rapports Phase 2 et premiers chiffres Phase 4)
La simulation pariait aux cotes d'**ouverture** mais jugeait à la ligne de **clôture** ; quand la ligne avait bougé entre les deux, cote et ligne ne correspondaient pas.
Les ROI/CLV du handicap des rapports précédents (dont « +3,0 %, 94e percentile » en Phase 2) sont donc **invalides**. Corrigé : seuls les matchs à ligne stable sont simulés (test automatique ajouté) ; les chiffres corrigés figurent dans la section suivante. Les Brier/calibration (comparés à la clôture, même ligne) n'étaient pas concernés.
