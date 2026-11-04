# Phase 2 — Résultats intermédiaires et audit de faisabilité Understat

Date : 2026-11-04. Branche : `claude/phase2-audit-comparaison`. Statut : **rapport intermédiaire — aucune modification
d'architecture n'est appliquée, rien n'est fusionné dans `main`, aucune dépense.**

## A. Comparaison walk-forward (données gratuites Football-Data, Pinnacle) — résultats réels

Échantillon : 5 championnats (E0, F1, D1, I1, SP1), 5 999 matchs testés hors échantillon (février 2022 → mai 2025),
chaque prédiction n'utilise que le passé (test automatique anti-fuite). Modèle de test = forces attaque/défense par
équipe + avantage du terrain, décroissance temporelle ; **ce n'est pas encore le modèle de production** (pas d'Elo,
H2H, shrinkage de production). Marché = cotes Pinnacle sans marge.

| Marché | Marché clôture (Brier) | Modèle seul | Δ vs marché | Meilleur mélange | Verdict |
|---|---|---|---|---|---|
| 1X2 (n=5 999) | 0,5723 | 0,5879 (Dixon-Coles) | +0,0156 ± 0,0016 | w=0,15 : +0,0009 ± 0,0002 | le marché est meilleur ; tout poids donné au modèle dégrade |
| Over/Under 2,5 (n=5 944) | 0,4741 | 0,4861 | +0,0120 ± 0,0018 | w=0,15 : +0,0005 ± 0,0003 | idem |
| Handicap asiatique, demi-lignes (n=1 450) | 0,4980 | 0,5119 | +0,0139 ± 0,0044 | w=0,15 : +0,0003 ± 0,0007 | idem (écart non significatif pour le mélange) |

* La dégradation est monotone avec le poids du modèle : 0 → 0,15 → 0,35 → 0,5 → 1. **Aucun mélange ne bat le marché de clôture.**
* L'ouverture Pinnacle est elle-même moins bonne que la clôture (Brier 0,5737 contre 0,5723) : l'information arrive entre les deux.
* **Poisson ≈ binomiale négative** (écarts < 0,0001) : la dispersion estimée est à la borne haute, donc pas de sur-dispersion
  par équipe une fois la force des équipes prise en compte. **Dixon-Coles est un peu meilleur** : il corrige la sous-estimation
  des nuls (observé 24,9 % ; Poisson 23,5 % ; Dixon-Coles 24,7 %) et gagne ~0,0006 de Brier en 1X2.
* Écarts ≥ 3 buts : observé 16,1 %, modèles 16,9 % ; totaux ≥ 5 : observé 15,7 %, modèles 16,2 % ; totaux ≤ 1 : observé 22,8 %, modèles 24,1 %.
  Les queues sont légèrement **surestimées** (pas sous-estimées) — l'hypothèse « le modèle sous-estime les gros scores » est infirmée sur cet échantillon.
* Calibration : 1X2 correcte (ECE 0,008 modèle, 0,010 marché). **Handicap : le modèle est mal calibré (ECE 0,055)** : quand il
  s'écarte de 50 % (ligne déjà fixée par le marché), il a tort (ex. « 70-80 % » réalisé 46 %). Ses désaccords avec la ligne sont du bruit.
* Paris à l'ouverture quand le modèle dépasse le marché de ≥ 3 points : CLV négatif (1X2 −3,6 % ; O/U −3,3 % ; handicap −0,3 %), ROI
  1X2 −13 à −14 % (± 2,4), O/U −4,0 % (± 1,7), handicap +2,8 % (± 3,1, non significatif). Réserve : un pari « à l'aveugle » a déjà un CLV
  d'environ −(marge d'ouverture) ; la référence « pari aléatoire » doit être calculée pour mesurer le vrai écart (prochaine étape).

Conclusion prudente : sur ces données, **le marché Pinnacle est mieux calibré que ce type de modèle statistique** ; la valeur
du modèle est dans l'estimation de la probabilité de base (Dixon-Coles) et dans la combinaison, pas dans la détection d'« edges » contre le marché.
Cela rejoint la mesure interne (poids du modèle optimal ≤ 0,35, rien de significatif).

## B. Audit de données de la base (lecture seule, 2026-11-04)

* `hist_matchs` : 8 849 lignes, 5 championnats, saisons 2022→2026 ; 7 414 terminés, aucun doublon, aucun terminé sans score ; saison 2026 partielle (arrêtée ~17 oct.) ; 1 435 matchs futurs.
* `hist_cotes` : 35 887 lignes (10–12 oct. uniquement), `bookmaker` toujours NULL (colonne morte), 0 jugée → inexploitable pour un backtest.
* `hist_predictions` : **vide** (0 ligne). `cotes` : 1 040 585 lignes **sans horodatage** → aucune série temporelle / CLV possible jusqu'ici.
* `jambes` : 1 909 jambes ; 878 gagnées, 473 perdues, 68 push, **479 non vérifiables (25 %)** (corners 59/62, double chance, Over/Under, BTTS), 11 en attente ; 84 jambes sans proba ni edge.
* `runs` : 243, dont 98 « abandonné/erreur » (40 %) — à diagnostiquer (stabilité de la collecte).
* Correctif Phase 2 : table `cotes_gratuites` (série temporelle horodatée, source tracée) alimentée toutes les 6 h par le workflow `phase2.yml` (après fusion).

## C. Audit de faisabilité — intégration d'Understat

**Constat de vérification (réel)** : depuis les runners GitHub, `https://understat.com/robots.txt` et `https://understat.com/` ont répondu
HTTP 200 avec la **même page de 26 719 caractères (gabarit « errors.css »)** : pas de robots.txt réel, aucun lien de conditions
d'utilisation/licence, aucune ligne de liste de championnats. Cette réponse ressemble à une page d'erreur/anti-robot servie aux IP de centre
de données. Depuis la sandbox de développement, l'hôte est bloqué par le proxy. **Je n'ai rien contourné et je n'ai collecté aucune donnée de match.**

**Licence / conditions (non vérifiées à la source)** : aucune page de conditions n'a pu être lue. Seul indice, de seconde main
(documentation d'un paquet R communautaire) : le support aurait indiqué en 2018 que les données sont libres d'usage non commercial,
sans notice officielle autorisant le scraping, avec attribution recommandée. Ancien, informel, révocable. **Tant que vous n'avez pas validé
l'usage (ou obtenu l'accord écrit d'Understat), aucune collecte automatisée.** Si l'usage de ce projet est commercial (paris), le risque est réel.

**Données (selon sources tierces, à confirmer en accès réel)** : championnats EPL, La Liga, Bundesliga, Serie A, Ligue 1, RFPL ; saisons
depuis 2014/15 ; par match : buts, xG des deux équipes, probabilités 1X2 propres au site ; par tir : minute, xG, coordonnées, résultat, situation,
type de tir, joueur, passeur, côté ; par équipe/saison : xG, xGA, npxG, npxGA, tirs, PPDA, deep, xPTS ; par joueur/saison : buts, xG, xA, tirs,
key passes, xGChain, xGBuildup. **Absent : corners, cartons, fautes, hors-jeux, cotes, compositions.** → inutile pour ces marchés.
Les 5 championnats suivis sont couverts (la Russie n'est pas utile).

**Utilisation par moteur (variables réellement disponibles uniquement)**
* Buts : xG/xGA par équipe (taux de création/concession lissés par la décroissance temporelle) comme entrée du taux de buts ; tirs et qualité de tirs.
* 1X2 : force offensive/défensive xG-based (plus stable que les buts, souvent plus prédictive des matchs suivants — à démontrer par backtest, pas à supposer).
* Handicap : différence de xG attendue ; mais voir A : le modèle ne bat pas la ligne, donc xG ne sera utile que s'il améliore le Brier hors échantillon.
* Tirs : nombre de tirs et de tirs cadrés par équipe, partiellement ; sinon API-Football déjà en base.
* Autres marchés : aucune variable Understat pertinente.

**Cohérence et comparaison (plan de contrôle, à exécuter après autorisation)** : score Understat = score `hist_matchs`/Football-Data ;
somme des xG des tirs = xG du match ; nombre de tirs vs statistiques de tirs de `hist_matchs` ; xG vs `xg` d'API-Football quand présent ;
couverture par championnat/saison ; mapping des noms d'équipes (table `mapping_equipes` validée, jamais de fuzzy silencieux).

**Schéma PostgreSQL proposé (additif, tables préfixées `us_`, non créé)** : `us_matchs`, `us_tirs`, `us_equipes_saison`,
`us_joueurs_saison`, `mapping_equipes (source, nom_source, id_api_football, confiance, valide_le)`. Colonnes de provenance sur chaque
ligne : `source`, `url`, `collecte_le`, `hash_brut`, `version_parseur`, `licence_ref` ; JSON brut conservé dans `us_brut` pour audit.
Valeurs absentes = NULL, jamais estimées. Aucune lecture par la sélection de coupons tant que le backtest n'a pas prouvé un gain.

**Risques** : licence/CGU incertaines ; accès apparemment filtré pour les IP de centre de données ; pas d'API officielle (HTML/JSON embarqué
qui peut changer sans préavis) ; xG = modèle propriétaire (non vérifiable) ; une seule source ne doit jamais être unique (exigence respectée :
croisement avec Football-Data et API-Football).

**Alternatives gratuites** : Football-Data.co.uk (résultats, tirs, cotes, déjà intégré) ; API-Football (tirs/stats déjà en base) ; FBref/StatsBomb open data
(licences à vérifier séparément avant toute collecte).

## D. Décisions demandées (rien n'est fait sans accord)
1. Understat : confirmez-vous l'usage (non commercial / accord écrit à demander) ou préférez-vous des alternatives ?
2. Autoriser la fusion de la branche pour activer la capture gratuite toutes les 6 h ?
3. Autoriser, pour la suite de la Phase 2, le calcul de la référence « pari aléatoire » (CLV de base) et la comparaison avec le modèle réel de production ?
