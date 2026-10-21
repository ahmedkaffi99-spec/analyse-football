# Architecture cible

## Principes

1. **Un seul noyau de calcul.** Production, backtest et vérification des résultats appellent les mêmes
   fonctions. Aucune formule de probabilité, d'EV ou de jugement n'existe en deux exemplaires.
2. **Fonctions pures au centre, I/O en périphérie.** Collecte, base de données, IA et Telegram sont des
   adaptateurs ; les modèles ne font aucun appel réseau et ne lisent aucune variable d'environnement.
3. **Un modèle = un marché.** Chaque modèle déclare ses données requises, sa loi, ses paramètres mesurés
   et sa version ; sans données suffisantes il répond `INSUFFICIENT_DATA` (jamais un chiffre inventé).
4. **L'EV est exacte.** Issues à 5 états (gagné, demi-gagné, remboursé, demi-perdu, perdu) partout ;
   `EV = G(c−1) + DG(c−1)/2 − DP/2 − P`. Plus de `p + 0,5·push`.
5. **Aucune fuite du futur.** Toute feature à l'instant t n'utilise que des matchs terminés avant t.
6. **Les seuils se décident par backtest hors échantillon**, jamais en dur.

## Découpage cible (migration par étapes, `moteur/` devient le noyau)

```
moteur/                       NOYAU PUR (aucun réseau, aucune base, aucun env)
  lois.py                     Poisson, binomiale négative, matrice de scores (bornes adaptatives)
  issues.py                   issue_ligne / jugement UNIQUE (calcul + vérification) + EV exacte
  features.py                 features chronologiques (existant, testé anti-fuite)
  specialistes/               UN MODÈLE PAR MARCHÉ
    base.py                   interface ModeleMarche (données requises, predire, version)
    resultat.py   double_chance.py   handicap.py   buts.py (total/équipe/BTTS)
    corners.py    cartons.py         tirs.py       fautes.py
  valeur.py                   proba implicite, retrait de marge, EV, filtres de plausibilité
  calibration.py              isotone walk-forward (existant)
  coupon.py                   corrélation + composition (existant selection.py, nettoyé)
  backtest.py                 walk-forward — appelle EXACTEMENT specialistes + valeur + coupon

adaptateurs/ (aujourd'hui bet_agent/, backend/)
  donnees/                    API-Football, cotes 1xBet/OddsPapi, Elo, arbitre -> format features
  ia/                         DeepSeek/Groq/OpenRouter (agents familles, pilote)
  telegram/                   rédaction + envoi
  persistance/                SQLAlchemy / Supabase
  verification/               lit les scores finaux, appelle moteur.issues (aucune règle propre)
```

## Les modèles spécialisés

| Modèle | Données propres | Loi / méthode | Paramètres mesurés | Statut |
|---|---|---|---|---|
| Résultat 1X2 | buts pour/contre (10 derniers), Elo, avantage du terrain | matrice de scores Poisson indépendante | Elo poids 0,4 ; nul calibré (backtest) | refonte |
| Double chance | idem 1X2 | dérivé de la matrice + calibration **propre** (biais outsider domicile : −4 à −5 pts) | calibration isotone | refonte |
| Handicap / DNB | idem 1X2 | matrice + 5 issues (push exact) | — | refonte (corrige C3) |
| Buts total / par équipe | buts, ligue | matrice | lissage k mesuré | existant |
| BTTS | buts | matrice | à remesurer | existant |
| Corners | corners pour/contre | binomiale négative | var/moy = 1,16 | refonte |
| Cartons jaunes | cartons, arbitre (n≥5) | Poisson (var/moy 0,98) | poids arbitre 0,6 | existant |
| Tirs / tirs cadrés | tirs pour/contre | binomiale négative | 1,34 / 1,10 | refonte (corrige C1) |
| Fautes | fautes pour/contre | binomiale négative | 1,23 | refonte |
| Hors-jeux | **non collectés dans hist_matchs** | — | — | `INSUFFICIENT_DATA` tant que non collecté |

## Cohérence backtest ↔ production

- Un **adaptateur de features de production** convertit `stats_detaillees_10_matchs` (API-Football) au
  même format que `moteur.features` : le modèle reçoit la même structure en backtest et en production.
- Un test d'**équivalence** (« golden ») compare, sur les mêmes entrées, la sortie de chaque modèle
  refactoré à l'ancienne ; tout écart doit être une correction déclarée (C1–C4).
- Mode **shadow** (déjà présent : `moteur_central/shadow.py`) : le nouveau noyau tourne à côté de la
  production, écrit ses prédictions, sans coupon ni Telegram, jusqu'à validation des métriques.

## Garde-fous de la refonte

- Branche `refonte/moteur-v2`, **aucune fusion dans `main`** sans accord explicite.
- Supabase : lectures seules ; toute migration (ex. horodater `cotes`) est proposée, pas appliquée.
- Telegram : tests avec transport simulé ; aucun envoi réel sans autorisation.
