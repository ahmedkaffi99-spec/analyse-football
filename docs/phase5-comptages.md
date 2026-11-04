# Phase 5 — Moteurs de comptage (corners, cartons jaunes, tirs, tirs cadrés, fautes), 2026-11-04

Données : `fd_matchs` (Football-Data, 5 championnats, 2016-2026) ; **14 722 matchs testés hors échantillon**, walk-forward (refit tous les 21 jours sur les 3 dernières années, test à partir de 2018-08-12, aucun accès au futur — test automatique).
**Football-Data ne donne pas de cotes pour ces marchés** : on mesure la qualité des probabilités (Brier, log-loss, calibration), pas un ROI.
Comparaison : référence naïve (fréquence de dépassement de la ligue sur 12 mois) / Poisson par équipe / binomiale négative (NB) par équipe. Δ = écart de Brier apparié vs référence naïve (négatif = mieux), ± erreur type.

| Statistique (total du match) | Lignes testées | Δ Brier Poisson | Δ Brier NB | Calibration (ECE) Poisson → NB | Dispersion r (NB) | Verdict |
|---|---|---|---|---|---|---|
| **Fautes** | 22,5 / 24,5 / 26,5 | −0,0096 à −0,0124 (±0,0011) | −0,0096 à −0,0125 | 0,015-0,024 → 0,014-0,022 | ≈ 470 (≈ Poisson) | **signal d'équipe net** (≈ 9-11 σ) |
| **Tirs** | 22,5 / 24,5 / 26,5 / 28,5 | −0,0041 à −0,0058 (±0,001) | −0,0049 à −0,0071 | 0,030-0,035 → **0,014-0,020** | ≈ 30 (sur-dispersé) | signal net ; **NB nettement mieux calibrée** |
| **Tirs cadrés** | 7,5 / 8,5 / 9,5 / 10,5 | −0,0035 à −0,0056 (±0,001) | −0,0036 à −0,0059 | 0,020-0,023 → 0,015-0,018 | ≈ 90 | signal net (≈ 4-6 σ) |
| **Cartons jaunes** | 2,5 / 3,5 / 4,5 / 5,5 | −0,0024 à −0,0030 (±0,0007) pour 2,5-4,5 ; −0,0005 pour 5,5 | idem | ≈ 0,010-0,015 | ≈ 500 (≈ Poisson) | signal modeste (3-4 σ), nul pour la ligne 5,5 |
| **Corners** | 8,5 / 9,5 / 10,5 / 11,5 | ≈ +0,0006 (±0,0008) | −0,0005 à +0,0002 | **0,034-0,035 → 0,025-0,026** | ≈ 16 (très sur-dispersé) | **aucun avantage sur la référence naïve** ; Poisson mal calibré |

Lecture :
* Les marchés de **fautes, tirs et tirs cadrés** ont une vraie composante propre à chaque équipe (style de jeu, arbitrage) que la moyenne de ligue ne capture pas : un moteur par équipe améliore nettement la probabilité. Pour les **corners**, le modèle par équipe n'apporte rien de mesurable.
* La **binomiale négative est préférable** dès qu'il y a sur-dispersion (corners, tirs) : meilleure calibration, Brier égal ou meilleur ; Poisson suffit pour les fautes et les cartons.
* **Limite majeure** : améliorer la probabilité par rapport à une moyenne de ligue ne prouve pas un avantage sur le **bookmaker**, dont les cotes intègrent déjà ces effets d'équipe. Il faut comparer à des cotes réelles : voir la phase suivante (rejeu des cotes 1xBet collectées).
* Les résultats servent aussi à vérifier les jambes corners/cartons/tirs/fautes **non vérifiables** aujourd'hui (statistiques API-Football indisponibles) : Football-Data fournit ces totaux pour les 5 championnats.
