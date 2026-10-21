# Plan de migration par phases (chaque phase : tests verts, équivalence prouvée, rien dans `main`)

| Phase | Contenu | Critère de sortie |
|---|---|---|
| 0 | Audit + architecture (ce dossier) | validé par l'utilisateur |
| 1 | `moteur/lois.py` à bornes adaptatives ; `moteur/issues.py` (jugement et EV uniques) ; interface `ModeleMarche` + 9 spécialistes derrière `predire_match` inchangé | tests golden : sorties identiques à l'existant, sauf corrections déclarées |
| 2 | Adaptateur de features de production ; `bet_agent` appelle les spécialistes au lieu de ses formules | probabilités production = probabilités backtest sur 100 % des cas de test |
| 3 | Résultats : `verifier_resultats` délègue à `moteur.issues` ; réduction des 36 % de `non_verifiable` | taux de jambes jugées mesuré avant/après |
| 4 | Valeur : EV exacte, probabilité modèle et probabilité marché stockées séparément (migration **proposée**, non appliquée) | audit EV forward sur `jambes` |
| 5 | Calibration et seuils par marché par backtest hors échantillon | rapport de calibration par spécialiste |
| 6 | Shadow en production, puis bascule sur décision explicite | métriques shadow ≥ legacy sur marchés cibles |
| 7 | Découpage de `analyser_et_envoyer.py` (IA, Telegram, collecte), suppression du code mort | plus aucun module > 800 lignes ; zéro duplication de formule |
