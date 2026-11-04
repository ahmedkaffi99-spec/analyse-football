# Phase 3 — Architecture des données (schéma, contrats, plan de migration)

Date : 2026-11-04. Branche : `claude/phase3-architecture-donnees`. Approuvée par l'utilisateur le 2026-11-04 (Understat laissé de côté, StatsBomb ajouté).
Principe : **additif d'abord** (aucune table existante supprimée, aucune donnée historique modifiée), provenance obligatoire, valeurs absentes = NULL (jamais estimées).

## 0. Correction d'une affirmation du rapport Phase 2
Le rapport disait « 357 jambes pointent vers des matchs supprimés ». C'est **faux** : vérification SQL — 0 match absent ; les 357 jambes (dont 156 non vérifiables) sont rattachées
à des matchs **sans coup d'envoi enregistré** (`matchs.coup_envoi` NULL, runs 3 à 238) parce que le coup d'envoi n'était lu que chez API-Football. Corrigé dans le code (repli OddsPapi).
De même la colonne `cotes.marche_id` était déjà tronquée à 32 caractères dans le code ; la troncature est étendue à `periode`, `marche` et `selection`.

## 1. Sources et statut juridique (registre `sources_donnees`, garde-fou `exiger_autorisation`)
| Source | Usage | Statut | Remarque |
|---|---|---|---|
| API-Football | stats, calendrier, cotes (clé de l'utilisateur) | autorisée (abonnement) | quota respecté ; plan actuellement suspendu |
| OddsPapi | cotes 1xBet | autorisée (clé de l'utilisateur) | quota 250/jour |
| Football-Data.co.uk | résultats + cotes (clôture, Pinnacle 1X2 ; Bet365 O/U-AH en 2026/27) | à vérifier | conditions du site non retrouvées ; données anglaises = Football DataCo |
| **StatsBomb Open Data** | tirs + xG par tir, événements (recherche) | **autorisée sous condition d'attribution** | aucune saison en cours ; accord complet à relire avant publication |
| ClubElo | Elo par club | à vérifier (non automatisé) | conditions non retrouvées |
| OpenFootball | calendriers/résultats (domaine public annoncé) | à vérifier (non automatisé) | licence à confirmer par dépôt |
| football-data.org | API gratuite (clé personnelle) | à vérifier (non automatisé) | inscription gratuite à faire par vous ; limites de débit |
| Understat | xG, tirs | **inconnue / bloquée** | laissée de côté (décision du 2026-11-04), verrou conservé |

## 2. Modèle de données cible (entités et contrats)
* **Compétition / saison / équipe** : identifiant canonique = API-Football ; table `mapping_equipes (source, nom_source, id_api_football, confiance, valide_le)` — jamais de rapprochement flou silencieux (le rapprochement par noms de la Phase 2 est tracé mais doit être validé).
* **Match** : `matchs` (collecte) et `hist_matchs` (historique) ; contrat minimal : identifiant, date UTC, équipes canoniques, score final, statut. **Nouveau** : `coup_envoi` toujours renseigné (repli OddsPapi).
* **Cote (série temporelle)** : `cotes_gratuites` (changement seulement, source + empreinte, horodatage UTC) pour les sources gratuites ; `cotes.capture_le` (nouveau) pour la collecte 1xBet. Les lignes antérieures restent NULL (jamais rétro-remplies).
* **Prédiction** : `jambes.proba_modele_pct` (finale) **+ `proba_modele_seul_pct`, `proba_marche_pct`, `collecte_le`** (nouveaux) — indispensables pour évaluer modèle seul / marché seul / mélange sans rejouer les archives.
* **Événements / tirs** : `sb_matchs`, `sb_tirs` (StatsBomb : xG par tir, résultat, type, position) avec `url_source`, `hash_fichier`, `collecte_le`, `licence_ref`.
* **Journal de collecte** : `captures_gratuites_journal` (chaque tentative : ok / sans_match_cible / vide / erreur, octets, empreinte, comptes).

Règles de contrat : (1) toute ligne importée porte sa source, son URL et l'empreinte du fichier ; (2) heures en UTC ; (3) pas d'UPDATE/DELETE sur l'historique brut ; (4) toute nouvelle source passe par le registre (collecte refusée si non autorisée) ; (5) aucune valeur estimée présentée comme observée.

## 3. Plan de migration (appliqué ici, additif, idempotent)
1. `cotes.capture_le`, `jambes.proba_modele_seul_pct`, `jambes.proba_marche_pct`, `jambes.collecte_le` : `ADD COLUMN IF NOT EXISTS` dans `init_db` (NULL pour l'historique).
2. Persistance : coup d'envoi OddsPapi en repli ; écriture des composantes de probabilité ; horodatage des cotes ; troncatures de sécurité.
3. Tables `sources_donnees`, `mapping_equipes`, `sb_matchs`, `sb_tirs`, `cotes_gratuites`, `captures_gratuites_journal` créées par `create_all` (déjà en place ou nouvelles).
4. Rien n'est migré à l'envers : les 1 909 jambes et 1,04 M de cotes existantes restent intactes.
Non fait (à décider) : branchement de `hist_predictions` (écriture par jambe), conservation du détail des cotes par run au-delà de la fenêtre actuelle, validation manuelle de `mapping_equipes`.

## 4. Contrôles de qualité en continu
Journal de capture (statut, hash identique = pas de nouvelle donnée), cohérence StatsBomb (buts reconstitués = score officiel, rapport buts/xG), rapprochement Football-Data tracé (matchs retrouvés/non retrouvés), tests automatisés (backend 188, bet_agent 624).

## 5. Limites
StatsBomb n'a pas de saison en cours : utile pour construire/valider un modèle xG et la calibration, pas pour le pronostic du jour. Les autres sources « à vérifier » ne sont pas automatisées tant que leurs conditions ne sont pas confirmées.

## 6. Résultats mesurés pendant la Phase 3 (runs GitHub Actions, lecture seule sauf import StatsBomb)
### StatsBomb Open Data (import réel dans `sb_matchs` / `sb_tirs`, provenance + empreinte SHA-256)
| Compétition | Matchs disponibles | Importés | Scores cohérents (buts reconstitués = score officiel) | xG total | Buts réels | Buts / xG |
|---|---|---|---|---|---|---|
| Bundesliga 2023/24 | 34 | 34 | 34/34 | 100,5 | 113 | 1,124 |
| Ligue 1 2022/23 | 32 | 25 (plafond d'essai) | 25/25 | 76,8 | 85 | 1,107 |
Aucune erreur, aucun match sans tirs. Les données ouvertes ne couvrent **que certaines équipes** (34 matchs de la Bundesliga 2023/24, 32 de la Ligue 1 2022/23), pas des championnats entiers : utile pour entraîner/valider un modèle xG et la calibration, pas pour le pronostic du jour. L'écart buts/xG (+11-12 %) vient d'échantillons d'équipes très offensives, à ne pas généraliser.

### Poids du modèle dans la probabilité finale (p = (1−w)×marché + w×modèle) — Brier, écart apparié vs marché seul
* **Walk-forward 5 999 matchs (1X2, clôture Pinnacle)** : w=0,05 +0,0002 à +0,0003 (±0,0001) ; 0,10 +0,0006 (±0,0002) ; 0,15 +0,0009 (±0,0002) ; 0,35 +0,0029 (±0,0005) ; 1,00 +0,0156 (±0,0016). Over/Under et handicap : ≤ 0,10 dans le bruit, au-delà dégradation croissante.
* **Production rejouée, 2 711 paris** : w=0 : 0,1638 ; 0,05 : +0,0001 (±0,0001) ; 0,10 : +0,0003 (±0,0001) ; 0,15 : +0,0005 (±0,0002) ; 0,25 : +0,0009 (±0,0003) ; **0,35 (valeur actuelle) : +0,0015 (±0,0004)** ; 0,50 : +0,0024 (±0,0005) ; 1,00 : +0,0069 (±0,0011).
  Sur les 301 événements avec référence : même sens, non significatif individuellement (±0,0002 à ±0,0035).
* Conclusion : sur tous les jeux de données disponibles, **aucun poids du modèle n'améliore le marché ; l'optimum est proche de 0 %**. Aucun changement du poids de production n'est appliqué par cette branche (décision à prendre explicitement, phase suivante).
* Reproductibilité : la référence aléatoire est reproductible à code et graine identiques (graine 2026) ; l'ordre de tirage des groupes a été rendu insensible aux types mixtes entre deux runs, ce qui explique de petits écarts (ex. −5,61 % au lieu de −5,70 %) sans changer les conclusions.

### Capture gratuite toutes les 6 h (cron actif depuis la fusion de la Phase 2)
Le fichier `fixtures.csv` ne contient que des matchs hors des 5 championnats en milieu de semaine (statut `sans_match_cible`, normal). La première vraie capture est attendue avec les matchs du week-end ; le journal `captures_gratuites_journal` en rend compte à chaque passage.
