# Phase 6 — Marchés statistiques : production et moteur Phase 5 contre le marché 1xBet (2026-11-04)

Méthode : collectes archivées des runs terminés depuis le 22/10 **rejouées** avec le vrai moteur ; résultats = totaux Football-Data (`fd_matchs`) pour les 5 championnats
(73 matchs retrouvés, **6 278 paris statistiques jugés** hors poussées). Moteur Phase 5 = binomiale négative par équipe ajustée **avant** le 22/10 (aucune fuite). Brier, plus bas = mieux.
Limites : un mois de matchs seulement ; plusieurs lignes d'un même match sont fortement corrélées (l'échantillon efficace est bien plus petit que n) ; « Yellow Cards » 1xBet supposé = jaunes seuls.

| Catégorie | n | Brier 1xBet | Modèle de production seul | Final de production | Δ final − 1xBet | Moteur Phase 5 (NB) | Δ NB − 1xBet |
|---|---|---|---|---|---|---|---|
| **Toutes** | 6 278 | 0,1888 | 0,1952 | 0,1895 | +0,0007 ± 0,0003 | 0,1824 | +0,0009 ± 0,0012 (non sign.) |
| Total corners | 2 432 | 0,1808 | 0,1817 | 0,1804 | −0,0005 ± 0,0004 | 0,1814 | +0,0005 ± 0,0012 |
| Total cartons | 690 | 0,1812 | 0,1924 | 0,1834 | +0,0021 ± 0,0011 | 0,1889 | **+0,0077 ± 0,0038** (NB moins bon) |
| Total fautes | 98 | 0,2079 | 0,2180 | 0,2086 | +0,0007 ± 0,0035 | 0,2214 | **+0,0135 ± 0,0063** (NB moins bon) |
| Total tirs | 132 | 0,2297 | 0,2647 | 0,2388 | +0,0091 ± 0,0036 | 0,2038 | **−0,0259 ± 0,0089** (NB meilleur, ≈ 2,9 σ) |
| Total tirs cadrés | 140 | 0,1303 | 0,1380 | 0,1311 | +0,0008 ± 0,0020 | 0,1214 | **−0,0089 ± 0,0030** (NB meilleur, ≈ 3 σ) |
| Totaux par équipe (corners, cartons, fautes) | 56 à 1 244 | 0,19-0,23 | plus haut | ≈ marché | −0,0001 à +0,0135 | — | — |

Lecture prudente :
* **Le modèle de production seul est moins bon que le marché partout**, et le mélange final ne l'améliore pas (≈ égal sur les corners, légèrement moins bon ailleurs) : même conclusion que sur les buts.
* **Corners : le marché est aussi bon que n'importe quel moteur testé** (production et NB à égalité, dans le bruit).
* **Tirs et tirs cadrés : le moteur NB par équipe (Phase 5) bat le marché 1xBet** (≈ 3 σ), alors que cartons et fautes, c'est l'inverse. Ce sont des **indices à confirmer**, pas des preuves : petit échantillon (≈ 40-60 matchs), lignes corrélées, comparaison multiple (5 catégories).
* Paris « moteur Phase 5 ≥ 1xBet + 3 points » (922 sur 3 492) : ROI −2,2 % [−8,4 ; +4,2] contre −15,0 % [−21,0 ; −9,6] pour le hasard (meilleur que 100 % des simulations) — il évite surtout les mauvais côtés ; l'intervalle contient 0, **aucun profit démontré**. Par catégorie : tirs n=53 +30,4 % (très bruité), cartons +1,7 %, tirs cadrés +2,5 %, corners −5,0 % (n=584), fautes −33,1 % (n=37).
* **Conclusion de décision** : ne rien changer au moteur de coupons ; suivre prospectivement tirs / tirs cadrés (le rejeu s'actualise à chaque exécution, les matchs s'accumulent) et ne retenir un avantage que si le Brier et le CLV se confirment sur un échantillon plus grand.

## Amélioration livrée avec cette phase : vérification des jambes statistiques sans API-Football
Constat : sans API-Football (abonnement terminé le 30/10), **toute jambe corners/cartons/tirs/fautes était déclarée « non vérifiable » immédiatement**.
Désormais, la vérification se replie sur `fd_matchs` (Football-Data, 5 championnats ; rapprochement par date ±1 jour et noms ≥ 80/100 des deux côtés, aucune valeur inventée) et, si le match n'y est pas encore, la jambe reste « en attente » pendant le délai habituel (2 jours) au lieu d'être classée non vérifiable.
La saison courante de Football-Data est mise à jour toutes les 6 h par le workflow `phase2.yml` (5 fichiers, insertion seule). Test automatique ajouté (jambe corners jugée par Football-Data sans API-Football).
