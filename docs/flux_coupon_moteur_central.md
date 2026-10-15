# Flux complet de génération d'un coupon — moteur central (15/10/2026)

## 1. Qu'est-ce que "central" ?

`moteur_central` n'est **pas** un modèle de prédiction de plus — c'est une couche
d'**arbitrage** qui regroupe les forces de deux moteurs existants en un seul pipeline de
décision :

- **bet_agent** (Poisson classique) : rapide, couvre tous les marchés, mais inadapté aux
  marchés à forte variance (tirs, corners, cartons — voir §7).
- **moteur/** (10 modèles spécialisés) : Poisson/Dixon-Coles pour les buts, **binomiale
  négative** pour tirs/corners/cartons (surdispersion réelle prise en compte), calibré sur
  4 saisons complètes des 5 grands championnats.

`moteur_central` ne recalcule rien lui-même : il **compare**, **arbitre** marché par marché,
**exclut** ce qui est structurellement peu fiable, puis **compose** le(s) coupon(s) à partir
de ce qui reste — la "puissance" vient de la combinaison, pas d'un modèle unique plus gros.

## 2. Combien de chemins/processus pour produire UN coupon combiné ?

**17 étapes distinctes**, réparties en **5 couches** : déclenchement → collecte → double
calcul de probabilité → arbitrage/filtrage → composition → publication.

## 3. Flux détaillé, de haut en bas (top-down)

```
┌─────────────────────────────────────────────────────────────────────────┐
│ COUCHE 0 — DÉCLENCHEMENT                                                 │
└─────────────────────────────────────────────────────────────────────────┘
 1. GitHub Actions (cron horaire 6h-14h UTC, ou déclenchement manuel)
        │
 2. .github/workflows/pipeline-quotidien.yml → python -m app.taches run
        │
 3. backend/app/taches.py:tache_run() → runs.py:executer_run(moteur="central")

┌─────────────────────────────────────────────────────────────────────────┐
│ COUCHE 1 — COLLECTE (bet_agent/collecte_donnees.py)                      │
└─────────────────────────────────────────────────────────────────────────┘
 4. Sélection des matchs du jour
      → selectionner_matchs_du_jour_api_football() : 5 grands championnats +
        Ligue des Champions/Europa League, filtré par délai avant coup d'envoi (45 min min),
        exclusion réserve/jeunes/féminines, dédoublonnage
      → repli sur MATCHS_MANUELS seulement si l'automatique ne trouve RIEN
 5. Pour chaque match retenu : cotes réelles (API-Football/1xBet), stats historiques,
    stats détaillées (10 derniers matchs), classement, confrontations directes, blessures
      → tout vient d'API-Football depuis le 13/10/2026 (OddsPapi retiré)

┌─────────────────────────────────────────────────────────────────────────┐
│ COUCHE 2 — DOUBLE CALCUL DE PROBABILITÉ (deux moteurs, en parallèle)      │
└─────────────────────────────────────────────────────────────────────────┘
 6. bet_agent/analyser_et_envoyer.py:agent3_calcul_pool_candidats()
      → UN pool de candidats (match, marché, sélection, cote, probabilité Poisson, edge)
      → généré pour TOUS les marchés disponibles (buts, BTTS, Double Chance, tirs,
        corners, cartons, fautes, hors-jeux...)
 7. backend/app/services/comparaison_moteurs.py:comparer_candidats()
      → pour chaque candidat bet_agent, cherche une prédiction CONCURRENTE via moteur/
        (10 modèles : Poisson/Dixon-Coles pour les buts, binomiale négative pour
        tirs/corners/cartons) — seulement si (a) le marché est mappé
        (MARCHE_MOTEUR_PAR_CATEGORIE) ET (b) l'historique hist_matchs des DEUX équipes est
        suffisant (sinon : "indisponible", jamais un chiffre inventé)

┌─────────────────────────────────────────────────────────────────────────┐
│ COUCHE 3 — ARBITRAGE ET FILTRAGE (moteur_central_run.py)                 │
└─────────────────────────────────────────────────────────────────────────┘
 8. decision_centrale.py:construire_candidats()
      → transforme chaque paire (bet_agent, moteur) en objets CandidatCentral distincts,
        un par moteur responsable
 9. moteur_central/choix_moteur.py:choisir_par_marche()
      → décide PAR MARCHÉ quel moteur a le meilleur ROI réel (hist_cotes jugé) — garde les
        deux si la décision est indisponible/égalité (jamais un choix arbitraire)
10. moteur_central/shadow.py:construire_pool_central()
      → fusionne selon cette décision
11. moteur_central_run.py:_exclure_bet_agent_marches_surdisperses() (15/10/2026)
      → retire les candidats bet_agent (Poisson) sur tirs/corners/cartons/fautes/
        hors-jeux — seules les prédictions moteur (binomiale négative, correcte pour ces
        marchés à forte variance) y restent éligibles

┌─────────────────────────────────────────────────────────────────────────┐
│ COUCHE 4 — COMPOSITION DU/DES COUPON(S)                                  │
└─────────────────────────────────────────────────────────────────────────┘
12. ae.nb_coupons_dynamique() : dimensionne le nombre de coupons au nombre RÉEL de matchs
    éligibles (jamais un chiffre fixé à l'avance)
13. Pour chaque coupon (boucle avec exclusion croisée des matchs déjà utilisés) :
      a. moteur_central/score_central.py : note chaque candidat restant (probabilité,
         edge, historique réel si disponible)
      b. moteur_central/selection.py : recherche exhaustive (2 à 5 jambes, une seule par
         match) → garde la combinaison dont la cote tombe dans la cible (1.3-3.0) avec le
         meilleur score moyen
14. verifier_unicite_matchs_coupons() : garde-fou final, bloque la publication si un match
    apparaît malgré tout dans 2 coupons

┌─────────────────────────────────────────────────────────────────────────┐
│ COUCHE 5 — PUBLICATION                                                   │
└─────────────────────────────────────────────────────────────────────────┘
15. _rejoindre_candidat_bet_agent() : chaque jambe retenue est rejointe à son candidat
    bet_agent d'origine (categorie/handicap/guide/onglet/contexte complets)
16. agent4_rediger_coupons() : rédaction LLM (ou repli automatique sans IA si tous les LLM
    échouent) + persistance (table coupons/jambes, Supabase)
17. agent5_envoyer_coupons() : envoi Telegram, un message par coupon
```

## 4. Garanties actives à chaque run

- **Jamais de match inventé** : un marché sans donnée suffisante est omis, jamais deviné.
- **Jamais de repli silencieux** : un échec de moteur_central termine le run en erreur
  explicite, jamais une bascule discrète vers un autre moteur.
- **Unicité croisée** : un même match ne peut jamais apparaître dans deux coupons du même
  run (exclusion proactive + garde-fou final).
- **Marché adapté au bon modèle** : buts/BTTS/Double Chance (Poisson, approprié) restent
  chez bet_agent ; tirs/corners/cartons (surdispersés) passent exclusivement par moteur/
  (binomiale négative) depuis le 15/10/2026.

## 5. Limites connues, non résolues

- `moteur_central` ne peut comparer que les matchs où **les deux équipes** sont dans
  l'historique backfillé (5 championnats domestiques) — un match de Ligue des Champions
  entre une équipe des 5 grands championnats et une équipe d'un autre pays n'a pas de
  prédiction moteur concurrente, seulement bet_agent (buts/BTTS/Double Chance restent
  disponibles, tirs/corners/cartons non).
- L'arbitrage par ROI réel (`choix_moteur`) est non fonctionnel aujourd'hui : `hist_cotes`
  n'a aucune ligne jugée — en pratique, la décision est toujours "indisponible" (les deux
  moteurs sont gardés, départagés uniquement par score).
- Aucun backtest n'existe encore sur la sortie COMPLÈTE de moteur_central (sélection finale,
  pas seulement les modèles bruts de moteur/).
