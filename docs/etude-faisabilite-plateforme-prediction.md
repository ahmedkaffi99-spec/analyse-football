# Étude de faisabilité — plateforme professionnelle de prédiction sportive

Date : 04/11/2026 · Statut : **proposition à valider — aucun développement de la plateforme n'est commencé.**
Les prix indiqués sont des **ordres de grandeur non vérifiés** : chaque fournisseur doit être consulté pour un devis avant tout achat.

---

## 0. Résumé exécutif

**Verdict.** Construire l'infrastructure est techniquement faisable et raisonnable en coût. **Prouver qu'elle dégage un avantage économique est incertain**, et c'est le vrai risque du projet, pas la technique.

Ce que nos propres mesures établissent déjà (système actuel, depuis le 22/10) :

| Constat | Chiffre |
|---|---|
| Modèle seul contre marché seul (53 matchs, 3 marchés de buts) | Le modèle est le moins bon des 6 mélanges testés, sur les 3 marchés |
| Jambes à edge positif (modèle > marché) | 60 % de réussite, rendement −11,5 % par jambe (48 jambes) |
| Jambes à edge négatif | 78 % de réussite, rendement +5,0 % (153 jambes) |
| Consensus de 10 bookmakers contre 1xBet seul | Aucun gain mesurable ; 1xBet a la marge la plus basse en 1X2 (2,1 %) |
| Coupons de 5 à 8 jambes | Espérance structurellement < 1 : la marge (≈ 3 % par jambe) se cumule |

**Conséquences pour la conception.**
1. Le marché est le point de départ, pas l'adversaire : le modèle doit prouver qu'il **ajoute** de l'information à une cote de clôture sans marge.
2. Le **Closing Line Value (CLV)** devient l'indicateur n° 1, avant le ROI (le ROI met des centaines de paris à converger, le CLV beaucoup moins).
3. Le **format des paris** pèse autant que le modèle : paris simples ou handicaps asiatiques à faible marge, pas des combinés de 8 jambes.
4. L'investissement est **échelonné par portes de décision** (go / no-go chiffrés) : on n'achète les données chères qu'après avoir prouvé, sur des données peu coûteuses, que l'approche a un avantage.

---

## 1. Architecture complète

```
                      ┌──────────────────────────────────────────────┐
  Fournisseurs ───►   │ 1. Collecte (connecteurs + planificateur)    │
  (stats, cotes,      └───────────────┬──────────────────────────────┘
   compos, météo)                     ▼
                      ┌──────────────────────────────────────────────┐
                      │ 2. Validation & qualité (contrats de schéma, │
                      │    dédoublonnage, détection d'anomalies)     │
                      └───────────────┬──────────────────────────────┘
                                      ▼
        ┌─────────────────────────────────────────────────────────────────┐
        │ 3. Entrepôt : PostgreSQL (+TimescaleDB pour les cotes en série) │
        │    brut immuable → nettoyé → variables (feature store)          │
        └───────┬──────────────────────────┬──────────────────────┬───────┘
                ▼                          ▼                      ▼
   ┌─────────────────────┐   ┌──────────────────────────┐  ┌───────────────────┐
   │ 4. Moteurs par      │   │ 5. Intelligence des cotes│  │ 6. Backtesting    │
   │ marché (buts, 1X2,  │   │ (sans marge, consensus,  │  │ walk-forward, CLV │
   │ corners, cartons…)  │   │ mouvements, CLV)         │  │ calibration       │
   └─────────┬───────────┘   └────────────┬─────────────┘  └─────────┬─────────┘
             └──────────────┬─────────────┴────────────────────────  │
                            ▼                                        │
              ┌──────────────────────────────┐                       │
              │ 7. Registre de modèles (MLflow)◄─────────────────────┘
              └──────────────┬───────────────┘
                             ▼
              ┌──────────────────────────────┐
              │ 8. Probabilités calibrées +  │
              │    cotes équitables          │
              └──────────────┬───────────────┘
                             ▼
              ┌──────────────────────────────┐   ┌──────────────────────┐
              │ 9. Gestion du risque (EV,    │──►│ 10. Rapports + API + │
              │    Kelly fractionné, corrél.)│   │  tableau de bord     │
              └──────────────────────────────┘   └──────────────────────┘
       Transversal : orchestrateur d'agents, monitoring, journalisation, sécurité
```

**Principe de séparation** : tout chiffre vient d'un calcul versionné et testé. Les agents IA lisent, comparent, détectent des contradictions et rédigent ; ils ne produisent **jamais** une statistique ni une probabilité (§11).

---

## 2. Infrastructure nécessaire

Dimensionnement réaliste du football (5 grands championnats + divisions 2 + coupes européennes) :

| Élément | Volume estimé | Conséquence |
|---|---|---|
| Matchs historiques (10 saisons, ~25 compétitions) | 60 000 à 100 000 | Petit : tient en mémoire d'un seul serveur |
| Événements/tirs par match (avec xG) | 25 à 40 lignes par match → 2 à 4 millions | PostgreSQL suffit |
| Cotes (ouverture → clôture, 10 bookmakers, ~50 marchés) | 1 à 5 milliards de lignes/an si capture fine | Séries temporelles : TimescaleDB, voire ClickHouse plus tard |
| Entraînement | Arbres de gradient, régressions, Poisson/bayésien | **CPU suffit** ; le GPU n'apporte presque rien ici |

**Verdict technique** : au début, un serveur PostgreSQL bien configuré, un planificateur de tâches et un stockage objet couvrent 95 % du besoin. Kafka, Kubernetes et ClickHouse sont justifiés seulement si on capte les cotes en continu et en temps réel sur beaucoup de bookmakers. On les prépare (interfaces propres) sans les déployer d'emblée.

---

## 3. Fournisseurs cloud recommandés

| Option | Pour | Contre | Quand |
|---|---|---|---|
| **Supabase / Postgres géré** (déjà en place) | Zéro exploitation, déjà branché | Plafonds de taille/connexions, pas de TimescaleDB | Phases 1-6 |
| **Hetzner / OVH (serveurs dédiés ou VPS)** | Meilleur rapport prix/performance, disques NVMe, simple | Exploitation à notre charge, pas de services gérés | Dès que les cotes en série dépassent Supabase |
| **AWS / GCP / Azure** | Services gérés (RDS, S3, SageMaker/Vertex), GPU à la demande, conformité | 2 à 4 fois plus cher à capacité égale | Palier « institutionnel » ou besoin de GPU ponctuel |
| **GPU à la demande (Lambda, RunPod, Vast…)** | Payer à l'heure, seulement pour les réseaux neuronaux | Utile surtout pour tests, pas en continu | Phase 7, si les tests montrent un gain |

**Recommandation** : rester sur Supabase + GitHub Actions jusqu'à la porte n° 1, puis un serveur dédié Hetzner/OVH (PostgreSQL + TimescaleDB) ; GPU à l'heure uniquement si un réseau neuronal bat les arbres de gradient en validation.

---

## 4. Configuration matérielle

| Palier | Base de données / calcul | Stockage | GPU |
|---|---|---|---|
| **Professionnel** | 1 serveur : 8 à 16 cœurs, 64 Go RAM | 1 à 2 To NVMe | aucun |
| **Avancé** | 2 serveurs (base + calcul), 16 à 32 cœurs, 128 Go RAM, réplica de lecture | 4 à 8 To NVMe + sauvegardes objet | 1 GPU à la demande |
| **Institutionnel** | Cluster géré, haute disponibilité, réplication multi-zones | 20 To+ | pool de GPU à la demande |

Le dimensionnement GPU est volontairement faible : sur des données tabulaires de cette taille, **XGBoost/LightGBM/CatBoost sur CPU** égalent ou battent les réseaux neuronaux. Un GPU permanent serait un coût sans justification technique.

---

## 5. Fournisseurs de données sportives

À évaluer sur trois critères : profondeur historique, couverture (ligues, joueurs, xG, compositions, blessures), licence d'usage (usage commercial, redistribution, scraping interdit ou non).

| Besoin | Candidats | Remarques |
|---|---|---|
| Résultats, stats équipe, compos, blessures | **API-Football** (déjà utilisé), Sportmonks, Sportradar | API-Football pro couvre déjà une partie ; à comparer à Sportmonks |
| xG, xA, événements joueur, données de position | **StatsBomb (Hudl)**, **Opta / Stats Perform**, Wyscout | Les plus riches, licences chères et négociées ; StatsBomb publie aussi des données ouvertes limitées |
| xG gratuits / ouverts | Understat, FBref (via StatsBomb/Opta) | **Vérifier les conditions d'usage** : le scraping peut être interdit |
| Cotes historiques (ouverture → clôture) | **Betfair Exchange (données historiques)**, Football-Data.co.uk (gratuit, clôture), OddsPortal (scraping : conditions à vérifier), The Odds API | Indispensable pour le CLV : sans cotes de clôture, pas de validation |
| Cotes en temps réel | Pinnacle (accès restreint), Betfair API, The Odds API, Sportradar/Genius | Pinnacle est la référence « sharp » mais l'accès n'est pas garanti |
| Météo | Open-Meteo (gratuit), Meteostat | Impact faible mais bon marché |
| Arbitres, calendriers | API-Football, Transfermarkt (conditions à vérifier) | |

**Ordres de grandeur annuels (à confirmer par devis)** : API sportives intermédiaires : de quelques centaines à quelques milliers d'euros ; flux de cotes : idem ; **licences de données d'événements premium (Opta, StatsBomb) : de dizaines de milliers d'euros par an**, souvent plus pour un usage commercial.

---

## 6. Stratégie d'acquisition des données historiques

1. **Commencer gratuit/peu cher pour prouver l'approche** : Football-Data.co.uk (résultats + cotes de clôture de nombreux bookmakers sur ~25 ans pour les grands championnats), plus ce que nous avons (8 849 matchs avec statistiques, 5 saisons).
2. **Ajouter les cotes d'ouverture et de mouvement** (Betfair historique, ou capture maison) : sans elles, le CLV complet n'existe pas.
3. **Capture prospective maison dès maintenant** : enregistrer à intervalles réguliers les cotes de tous les marchés suivis, jusqu'à la clôture. C'est la seule source de cotes d'avant-match fines gratuites, et elle crée une donnée que personne ne peut racheter.
4. **Acheter xG/événements seulement après la porte n° 1** (voir §13), pour ne payer que si le gain mesuré le justifie.
5. **Règles** : données brutes immuables, horodatage de réception, versionnage, aucune valeur inventée (champ vide + indicateur de manque), traçabilité de la source de chaque ligne.

---

## 7. Comparaison des modèles statistiques

| Modèle | Idéal pour | Forces | Limites | Décision |
|---|---|---|---|---|
| Poisson indépendant | Buts, comptages simples | Simple, rapide, notre base actuelle | Sous-estime les scores fleuves et les nuls | Référence de comparaison |
| **Dixon-Coles** | Buts, score exact, 1X2 | Corrige les petits scores et la corrélation, décroissance temporelle | Hypothèses fixes | **À implémenter en premier** |
| Poisson bivarié | Buts avec corrélation | Capte la dépendance entre équipes | Estimation plus lourde | À tester |
| **Binomiale négative** | Corners, tirs, fautes, parfois buts | Gère la sur-dispersion (variance > moyenne) | Paramètre de dispersion à estimer | **Standard pour les comptages** |
| Inflation de zéros | Cartons rouges, penaltys | Excès de zéros | Données rares | Cas par cas |
| **Bayésien hiérarchique** | Équipes à peu de données, divisions inférieures | Partage l'information, incertitude propre | Calcul plus lourd (MCMC) | Très pertinent pour l'incertitude |
| Elo | Force relative, variable d'entrée | Léger, interprétable | Ne donne pas de distribution de buts | Variable d'entrée |
| Modèles xG | Qualité de jeu | Moins bruité que les buts | Dépend de la donnée | Nécessite données d'événements |
| Régression logistique | 1X2, BTTS, marchés binaires | Calibrée, robuste, interprétable | Linéaire | Référence ML |
| **XGBoost / LightGBM / CatBoost** | Tout, avec nombreuses variables | Meilleur sur données tabulaires | Risque de sur-ajustement, calibration à refaire | **Cœur de la couche ML** |
| Random Forest | Référence | Robuste | Dépassé par le boosting | Comparaison |
| Réseaux neuronaux | Séquences, données de joueurs | Capte des motifs complexes | Besoin de beaucoup de données, peu d'avantage sur tabulaire | Seulement si gain prouvé |
| Monte-Carlo | Combinés, simulations de saison, corrélations | Flexible | Dépend des modèles amont | Pour le risque et les combinés |
| Ensembles | Final | Réduit la variance | Complexité | **Étape finale, avec le marché comme variable** |

**Règle de décision** : un modèle plus complexe n'est retenu que s'il bat la référence sur des données hors échantillon, avec une marge supérieure à son incertitude.

---

## 8. Stratégie de Machine Learning

1. **Cible** : pour chaque marché, une variable précise (ex. buts de chaque équipe, résultat, nombre de corners).
2. **Le marché comme variable explicative** : on apprend le résidu du marché plutôt que de le refaire (approche « stacking »). Notre test montre que ce que le modèle ajoute est faible : il faut le mesurer proprement.
3. **Variables** (feature engineering, sans fuite) : forces d'équipe dynamiques (Elo, Dixon-Coles), forme pondérée par le temps, xG pour/contre, repos et déplacements, absences chiffrées (valeur marchande ou minutes perdues), arbitre, météo, enjeu.
4. **Validation walk-forward** : on entraîne sur le passé, on teste sur la période suivante, on avance. Aucune donnée postérieure à l'heure de prédiction ; les variables sont horodatées.
5. **Calibration** : régression isotonique ou de Platt sur un jeu séparé ; on mesure l'erreur de calibration par tranche.
6. **Opérations ML** : MLflow (expériences, registre, versions), réentraînement planifié, détection de dérive (distribution des variables et des erreurs), alerte si le Brier se dégrade.
7. **Garde-fous** : trois jeux séparés (entraînement / validation / test final jamais touché avant décision).

---

## 9. Architecture des marchés spécialisés

Un moteur par famille, avec **ses données, ses variables, son modèle et sa validation propres**. Contrat commun : entrée = match + horodatage ; sortie = distribution de probabilités + incertitude + version du modèle.

| Famille | Variable à prédire | Modèle de départ | Variables clés | Validation |
|---|---|---|---|---|
| Résultat (1X2, DNB, double chance, handicaps) | Différence de buts | Dixon-Coles → ensemble | Force d'équipe, avantage du terrain, absences | Brier, log-loss, calibration, CLV |
| Buts (Over/Under, BTTS, score exact, mi-temps, buts par équipe) | Buts de chaque équipe (corrélés) | Poisson bivarié / binomiale négative | xG, rythme, style | Log-loss sur la distribution, CLV |
| Corners | Corners par équipe | Binomiale négative | Possession, centres, style, écart de force | Log-loss, calibration par ligne |
| Cartons | Cartons par équipe | Binomiale négative + effet arbitre | Arbitre, enjeu, rivalité, fautes | Idem ; rouges : inflation de zéros |
| Tirs / tirs cadrés | Tirs par équipe | Binomiale négative | Volume offensif/défensif, tactique | Idem |
| Hors-jeu, fautes, penaltys | Comptages rares | Binomiale négative / zéros gonflés | Arbitre, style | Idem ; rareté → bayésien hiérarchique |
| Performances individuelles | Événements par joueur | Modèle par joueur (minutes × taux) | Compositions, taux par 90 min | Dépend de données joueur |

Les marchés dont la donnée est insuffisante sont **désactivés** (pas de probabilité plutôt qu'une probabilité inventée).

---

## 10. Conception de la base de données

Schémas principaux (PostgreSQL ; TimescaleDB pour `cotes_ticks`) :

| Table | Rôle | Clés / remarques |
|---|---|---|
| `competitions`, `equipes`, `joueurs` | Référentiels | Identifiants internes + correspondance par fournisseur (`sources_ids`) |
| `matchs` | Calendrier, résultat, arbitre, météo | Horodatage coup d'envoi (UTC) |
| `compositions`, `evenements`, `stats_match_equipe`, `stats_match_joueur` | Données de jeu | Un instantané par source, horodaté |
| `blessures`, `suspensions` | Absences | Date de début/fin + date de connaissance (évite la fuite) |
| `cotes_ticks` | Cotes par bookmaker, marché, ligne, sélection, horodatage | Série temporelle, partitionnée par mois |
| `cotes_ouverture_cloture` | Vues matérialisées | Pour le CLV |
| `variables` (feature store) | Variables par match et horodatage de prédiction | Garantit l'absence de fuite |
| `modeles`, `entrainements`, `predictions` | Registre, historique | Version du modèle, des variables, des données |
| `paris_suivis`, `resultats_paris` | Suivi réel | Cote prise, cote de clôture, mise, résultat |
| `journal_qualite` | Anomalies, données rejetées | |

Principes : tables brutes **immuables** (ajout seulement), horodatage de réception sur toute ligne, séparation brut / nettoyé / variables, sauvegardes chiffrées et testées.

---

## 11. Organisation des agents autonomes

Un **orchestrateur** (programme déterministe, pas un modèle de langage) planifie, appelle les agents, compare leurs sorties et signale les contradictions.

| Agent | Nature | Rôle | Interdit |
|---|---|---|---|
| Collecte | Code | Appelle les fournisseurs, stocke le brut | — |
| Validation | Code + règles | Contrats de schéma, anomalies | Corriger en inventant |
| Analyse des matchs | Code + IA de lecture | Synthétise forme, absences, contexte | Chiffres non issus de la base |
| Buts, corners, cartons, tirs, 1X2 | Code (modèles) | Probabilités par marché | Opinion à la place du calcul |
| Intelligence des cotes | Code | Sans marge, consensus, mouvements, CLV | — |
| Gestion du risque | Code | EV, Kelly fractionné, corrélations, exposition | — |
| Backtesting | Code | Rejoue, mesure, compare à la référence | Réutiliser les données de test |
| Analyste principal | IA de rédaction | Assemble le rapport, relève les contradictions | Inventer ou modifier un chiffre |

**Garde-fou technique** : l'IA reçoit uniquement des chiffres issus de la base et un schéma de sortie ; une étape de vérification refuse tout nombre absent des entrées. C'est l'architecture que nous appliquons déjà au système actuel (validation Python des paris proposés par l'IA).

---

## 12. Architecture de sécurité

- **Secrets** : coffre de secrets (jamais dans le code ni les journaux), rotation, accès au moindre privilège.
- **Réseau** : base non exposée publiquement, accès par tunnel ou liste d'adresses, TLS partout.
- **Accès** : comptes nominatifs, authentification forte, rôles (lecture, exploitation, administration), journal d'audit.
- **Données** : sauvegardes chiffrées et testées (restauration trimestrielle), séparation production / développement, aucune donnée personnelle de parieur non nécessaire.
- **Chaîne de livraison** : dépendances figées et analysées, exécution en conteneurs, revue avant mise en production, **aucune action externe (achat, envoi, pari) sans autorisation explicite**.
- **Conformité** : respect des licences de données (revente, scraping) et de la réglementation des jeux d'argent du pays d'usage — **à faire valider par un juriste**, ce que je ne peux pas faire.

---

## 13. Feuille de route et portes de décision

| Phase | Contenu | Livrable vérifiable | Porte |
|---|---|---|---|
| 1 | Faisabilité (ce document) | Décision sur le palier | — |
| 2 | Audit de l'existant | Rapport : à garder, à remplacer | — |
| 3 | Architecture des données | Schéma, contrats, plan de migration | — |
| 4 | Données historiques | Cotes de clôture + 5 à 10 saisons, qualité mesurée | — |
| 5 | Moteurs statistiques (Dixon-Coles, binomiale négative, bayésien) | Modèles testés sur walk-forward | **Porte 1** : bat-il la référence Poisson hors échantillon ? |
| 6 | Moteurs par marché | Un moteur par famille, avec validation | — |
| 7 | Machine learning | Boosting + calibration + registre | **Porte 2** : le modèle + marché bat-il le marché seul (Brier/log-loss) ? |
| 8 | Intelligence des cotes | Sans marge, consensus, mouvements, CLV en capture prospective | — |
| 9 | Backtesting complet | Rapport par marché, ligue, tranche de cote | **Porte 3** : CLV > 0 sur ≥ 2 000 paris simulés, intervalle de confiance exclusif de 0 ? |
| 10 | Gestion du risque | EV, Kelly fractionné, corrélations | — |
| 11 | Tableau de bord + API | Rapports par match | — |
| 12 | Production | Déploiement avec suivi réel, montants limités | **Porte 4** : CLV et calibration confirmés en réel sur 3 mois ? |

**Règle d'arrêt** : si une porte échoue, on s'arrête, on documente et on ne finance pas la suite. La plateforme reste utile comme outil d'analyse et de maîtrise du risque.

À chaque phase : architecture présentée, décisions justifiées, tests automatisés, limites documentées, coût estimé, et **votre autorisation avant tout achat important ou action externe**.

---

## 14. Budget estimatif (ordres de grandeur, à confirmer par devis)

Hypothèse : football d'abord, extension à d'autres sports ensuite. Les coûts de développement supposent une équipe réduite ; ils peuvent être internalisés ou confiés.

| | **Professionnel** | **Avancé** | **Institutionnel** |
|---|---|---|---|
| Objectif | Prouver l'avantage à coût maîtrisé | Production mono-sport, données riches | Multi-sports, données premium, temps réel |
| Données | API sportives + cotes historiques (≈ 1 à 5 k€/an) | + xG/événements d'un fournisseur intermédiaire (≈ 5 à 30 k€/an) | + licences Opta/StatsBomb, flux de cotes (≈ 50 à 200 k€/an et plus) |
| Infrastructure | 1 serveur + base gérée | 2 serveurs + sauvegardes + GPU ponctuel | Cluster géré, haute disponibilité |
| Équipe (développement) | 1 ingénieur data/ML à temps partiel + moi | 2 à 3 personnes | 5 personnes et plus |
| Coût initial de mise en place | quelques k€ à 20 k€ | 50 à 150 k€ | 300 k€ et plus |

Le palier **Professionnel** est celui qui permet de franchir les portes 1 à 3 ; les paliers supérieurs ne se justifient qu'après.

## 15. Coûts opérationnels mensuels (indicatifs)

| Poste | Professionnel | Avancé | Institutionnel |
|---|---|---|---|
| Serveurs / cloud | 50 à 300 € | 500 à 2 000 € | 5 à 20 k€ |
| Données (abonnements) | 100 à 400 € | 500 à 3 000 € | 5 à 20 k€ |
| GPU à la demande | 0 | 0 à 300 € | 1 à 5 k€ |
| Outils (suivi, journaux, alertes) | 0 à 100 € | 100 à 500 € | 1 à 3 k€ |
| IA de rédaction (API) | 20 à 100 € | 100 à 500 € | 500 à 2 k€ |
| **Total hors personnel** | **≈ 200 à 900 €** | **≈ 1 200 à 6 000 €** | **≈ 12 à 50 k€** |

---

## 16. Risques

**Statistiques**
- **Pas d'avantage** : le marché est très efficace ; le modèle peut simplement égaler le marché. *Mitigation* : portes de décision, CLV.
- **Sur-ajustement et fuite de données** : *Mitigation* : walk-forward, variables horodatées, jeu de test intouché.
- **Petits échantillons** : des centaines de paris avant toute conclusion. *Mitigation* : intervalles de confiance, ne jamais conclure sur quelques dizaines de cas (nous l'avons déjà vécu).
- **Dérive** (changement de règles, de style de jeu) : *Mitigation* : surveillance, réentraînement.

**Techniques**
- **Dépendance aux fournisseurs** (arrêt, changement de format, quotas — l'abonnement API-Football a déjà été suspendu). *Mitigation* : connecteurs interchangeables, données brutes conservées, plan de repli.
- **Qualité des données et correspondance des noms d'équipes** : *Mitigation* : référentiel interne, contrôles automatiques.
- **Sur-ingénierie** (Kafka, Kubernetes sans besoin) : *Mitigation* : technologies ajoutées seulement si un seuil mesuré l'exige.

**Financiers et opérationnels**
- **Marge des bookmakers et combinés** : une espérance < 1 par jambe donne une perte garantie à long terme. *Mitigation* : paris à faible marge, mise adaptée, arrêt si le CLV est négatif.
- **Limitation de comptes** par les bookmakers : borne le gain, quel que soit le budget.
- **Coût de données premium sans retour prouvé** : *Mitigation* : achat après la porte 1.
- **Risque de ruine** : *Mitigation* : Kelly fractionné, plafond d'exposition.

**Juridiques**
- **Licences de données** (scraping, redistribution) et **réglementation du jeu** selon le pays : à valider par un juriste.

---

## Décisions à prendre pour passer à la phase 2

1. **Palier de départ** : je recommande **Professionnel**, avec passage au palier supérieur seulement après la porte 1.
2. **Priorité** : qualité des prédictions, format des paris (simples / handicaps asiatiques), ou les deux en parallèle.
3. **Données** : feu vert pour l'**audit de l'existant** et pour la **capture prospective des cotes** (coût quasi nul).
4. **Aucun achat** de données ou d'infrastructure n'est engagé sans votre accord explicite, par devis.
5. **Périmètre sportif** : football seul pour les phases 1 à 9, extension ensuite.
