# Génération dynamique de coupons quotidiens sans doublons

**Date** : 2026-10-11. **Statut** : implémenté, testé, non déployé (aucun run réel, aucun
envoi Telegram effectué par cette mission — voir § 7).

## 1. Décisions explicitement confirmées avant implémentation

Deux conflits réels entre la demande et l'état de production ont été soumis à validation
avant toute modification de code (aucune hypothèse silencieuse) :

1. **Restriction stricte à 5 ligues** — la collecte quotidienne ne cible plus que Premier
   League (Angleterre), La Liga (Espagne), Serie A (Italie), Bundesliga (Allemagne) et
   Ligue 1 (France), au lieu des 9 "LIGUES_MAJEURES" + repli international en vigueur
   jusqu'ici. Confirmé explicitement par l'utilisateur.
2. **Retour à 4-5 coupons/jour** — annule explicitement la décision du 03/10/2026 (revenue à
   un seul coupon après un run réel perdant, run #86 : "4 des 5 coupons perdus le même
   jour"). Confirmé explicitement : "j'annule ce choix du 03/10".

## 2. Règle de dimensionnement dynamique

`bet_agent/analyser_et_envoyer.py` — `nb_coupons_dynamique()` / `construire_profils_dynamiques()` :

| Matchs éligibles | Coupons générés |
|---|---|
| 0-1 | 0 (aucun coupon — jamais de match inventé) |
| 2-5 | 1 |
| 6-9 | 2 |
| 10-15 | 3 |
| 16-19 | 4 |
| ≥ 20 | 5 |

Chaque coupon reçoit un plafond de jambes (`nb_jambes`) borné par
`min(5, nb_matchs_eligibles // nb_coupons)` (jamais moins de 2) — garantit mathématiquement
qu'aucun coupon ne puisse réclamer plus de jambes que le pool ne peut structurellement fournir
une fois l'exclusion croisée appliquée (voir § 3). Ce dimensionnement ne s'applique qu'à la
sélection 100% automatique (`mode_manuel=False`) — la sélection manuelle garde son
comportement inchangé (`PROFILS_COUPON`, un seul coupon avec tous les matchs choisis par
l'utilisateur).

## 3. Unicité croisée entre coupons (règles 5, 6 et 8 de la mission)

Deux mécanismes complémentaires, jamais un seul :

1. **Exclusion proactive** (`matchs_utilises`, dans `generer_coupons`) : chaque match retenu
   par un coupon est retiré du pool disponible pour **tous** les coupons suivants de ce run —
   à la fois pour le chemin Python (repli Monte Carlo, actif par défaut) et pour le chemin IA
   stratège (`agent_strategie.valider()`, dont l'exclusion croisée — initialement limitée à
   l'identité exacte match+marché+sélection — a été élargie au niveau du MATCH entier : un
   match déjà choisi par un profil est refusé pour tout profil suivant, quel que soit le
   marché proposé).
2. **Garde-fou final** (`verifier_unicite_matchs_coupons`, appelé juste avant que
   `generer_coupons` ne renvoie son résultat) : relit l'ensemble des sélections de tous les
   coupons du run et **lève une exception** (bloque, ne corrige jamais silencieusement) si un
   même match apparaît dans deux coupons différents. Ne devrait jamais se déclencher tant que
   le mécanisme (1) fonctionne — un filet de sécurité, pas le mécanisme principal.

Consequence directe de la règle 6 ("au plus un marché par match sur l'ensemble des coupons") :
puisque l'exclusion porte sur le MATCH entier (pas seulement le marché choisi), un match
proposant plusieurs marchés (ex. Total ET BTTS) ne peut de toute façon fournir qu'une seule
jambe à l'ensemble du run — jamais une jambe par marché disponible.

## 4. Restriction aux 5 ligues et désactivation du repli hors-filtre

`bet_agent/collecte_donnees.py` :
- `FILTRE_LIGUES_UNIQUES` cible maintenant exactement les 5 grands championnats (remplace le
  défaut vide du 02/10/2026).
- `ACTIVER_SECOURS_HORS_FILTRE = False` (nouveau) : empêche le repli sur les compétitions
  internationales de secours (`FILTRE_LIGUES_SECOURS`) de repadder artificiellement le nombre
  de matchs en dessous de `NB_MATCHS_MIN` — cohérent avec la règle "ne jamais inventer de
  matchs pour atteindre un quota" (règle 7). Le mécanisme de secours reste présent dans le
  code et réactivable (variable explicite), inactif par défaut.

## 5. Fichiers modifiés

- `bet_agent/collecte_donnees.py` — restriction à 5 ligues, `ACTIVER_SECOURS_HORS_FILTRE`.
- `bet_agent/analyser_et_envoyer.py` — `construire_profils_dynamiques`/`nb_coupons_dynamique`,
  exclusion croisée (`matchs_utilises`/`pool_disponible`), `verifier_unicite_matchs_coupons`.
- `bet_agent/agent_strategie.py` — `valider()` : exclusion croisée élargie du marché exact au
  match entier (`matchs_deja_utilises`), docstring mise à jour.
- `bet_agent/test_correctifs.py`, `bet_agent/test_agent_strategie.py`,
  `bet_agent/test_agent_pilote.py` — mise à jour des tests affectés par (a) le nouveau défaut
  de `FILTRE_LIGUES_UNIQUES` (9 tests, patch explicite de l'ancien défaut vide quand la
  mécanique testée n'a aucun rapport avec les 5 ligues), et (b) la nouvelle règle d'exclusion
  croisée au niveau du match (réécriture d'assertions qui testaient l'ancien comportement
  intentionnellement contredit par cette mission).
- `bet_agent/test_generation_dynamique_coupons.py` (nouveau) — tests dédiés à cette mission
  (voir § 6).

Aucun autre fichier (persistance, rédaction, envoi Telegram, workflow GitHub Actions) n'a été
modifié : `enregistrer_coupons`, `agent4_rediger_coupons` et `agent5_envoyer_coupons` itèrent
déjà génériquement sur N profils, confirmé par lecture de code avant toute modification.

## 6. Tests exécutés

```
python -m pytest bet_agent backend/tests moteur moteur_central tests -q
→ 672 passed
```

Détail du nouveau fichier `test_generation_dynamique_coupons.py` (13 tests, tous les
scénarios obligatoires de la mission) :

| Test | Matchs éligibles utilisés | Scénario couvert |
|---|---|---|
| `test_jour_charge_cinq_coupons_dynamiques` | 25 | Jour chargé → 5 coupons |
| `test_jour_creux_un_seul_coupon` | 4 | Jour creux → 1 coupon |
| `test_zero_match_eligible_aucun_coupon_jamais_invente` | 0 | Zéro match éligible |
| `test_aucun_recouvrement_entre_coupons_sur_un_run_complet` | 12 | Absence totale de recouvrement |
| `test_un_seul_marche_choisi_par_match_meme_si_plusieurs_disponibles` | 3 (1 avec 2 marchés) | Plusieurs marchés, un match |
| `test_garde_fou_final_bloque_un_doublon_construit_a_la_main` | 1 (doublon construit) | Garde-fou final (règle 8) |
| `test_garde_fou_final_ne_se_declenche_pas_sans_doublon` | 2 | Garde-fou : pas de faux positif |
| `test_match_renvoye_deux_fois_dedoublonne` | 2 réels (3 entrées brutes) | Match dupliqué (plusieurs entrées source) |
| `test_match_juste_apres_minuit_UTC_reste_filtre_par_le_delai_normal` | — (fonction horaire) | Passage de minuit UTC |
| `test_match_deja_commence_exclu_meme_proche_de_minuit` | 1 | Match déjà commencé |
| `test_horodatage_avec_offset_non_utc_reste_compare_correctement` | — (fonction horaire) | Fuseau horaire avec offset |
| `test_deux_runs_independants_retrouvent_le_meme_resultat_deterministe` | 3 × 2 runs | Rejeu sans accumulation |
| `test_unicite_verifiee_independamment_a_chaque_appel` | 8 × 2 runs | Rejeu : unicité par run |

Au total, `pytest bet_agent -q` (403 tests du module avant cette mission + 13 nouveaux) passe
intégralement à `416` tests (vérifié : `403 + 13 = 416`, confirmé par
`python -m pytest bet_agent -q`).

## 7. Garanties d'unicité en place (résumé)

1. **Proactive** : un match retenu par un coupon n'est structurellement plus proposable à un
   autre coupon du même run (retrait du pool disponible), pour le chemin Python ET le chemin
   IA stratège.
2. **Défensive** : un contrôle final relit tous les coupons générés et **bloque la
   génération** (exception, jamais une correction automatique) si un doublon est malgré tout
   détecté.
3. **Sans effet de bord entre runs** : l'état d'exclusion (`matchs_utilises`) est une variable
   locale à `generer_coupons`, jamais un état de module — un rejeu du workflow repart d'un pool
   disponible complet, sans verrouillage résiduel d'une exécution précédente.

## 8. Ce qui N'a PAS été fait (restrictions respectées)

- Aucun run réel du pipeline, aucune collecte OddsPapi/API-Football effectuée.
- Aucun envoi Telegram, aucune publication réelle.
- Aucune règle de stratégie (seuils de probabilité, filtres de marché, cote individuelle
  maximale, etc.) modifiée au-delà de ce que cette mission demande explicitement.
