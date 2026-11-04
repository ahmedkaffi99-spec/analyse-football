# Décision du 2026-11-04 — poids du marché dans la probabilité finale : 0,65 → 0,90

**Changement** : `POIDS_MARCHE_OVERRIDE=0.90` dans `pipeline-quotidien.yml` (le modèle ne pèse plus que 10 % au lieu de 35 %). Réversible : retirer la ligne (retour à 0,65). Aucun changement de code ; les sélections, profils et validateurs sont inchangés.

**Pourquoi** (probabilité finale = (1 − w) × marché sans marge + w × modèle ; Brier plus bas = mieux ; écart apparié vs marché seul) :
| Source | n | w = 0,05 | w = 0,10 | w = 0,15 | w = 0,35 (ancienne valeur) | w = 1 |
|---|---|---|---|---|---|---|
| Production rejouée (1xBet) | 2 711 paris | +0,0001 ± 0,0001 | +0,0003 ± 0,0001 | +0,0005 ± 0,0002 | **+0,0015 ± 0,0004** | +0,0069 |
| Walk-forward 1X2 (Pinnacle) | 10 791 matchs | +0,0002 ± 0,0001 | +0,0005 ± 0,0001 | +0,0008 ± 0,0002 | +0,0026 ± 0,0004 | +0,0145 |
| Walk-forward Over/Under | 10 644 matchs | +0,0001 | +0,0002 | +0,0004 | +0,0016 ± 0,0005 | +0,0108 |
Aucun poids du modèle n'améliore le marché ; la perte croît avec le poids. À 10 %, la perte est ≈ 5 fois plus petite qu'à 35 %. On garde 10 % (et non 0) pour conserver une trace du modèle dans les probabilités affichées et ses garde-fous (écarts anormaux repérés), sans payer le coût mesuré.

**Effet attendu** : probabilités affichées plus proches du marché (mieux calibrées), moins d'« edges » artificiels dus au modèle. Les paris restent à valeur espérée négative (marge du bookmaker) ; ce changement n'en crée pas de positive.
**Contrôle** : le rejeu `phase2-production-vs-pinnacle` continue de comparer modèle/marché/final ; relire le tableau « POIDS DU MODÈLE » après quelques semaines de nouveaux matchs.
