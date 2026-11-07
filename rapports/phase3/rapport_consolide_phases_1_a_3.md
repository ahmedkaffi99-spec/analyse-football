# Rapport consolidé — Phases 1 à 3 (07/11/2026)

Branche `claude/analyse-matchs-football-796va6` (= `main` + travail non committé). `main`, le stash « ébauche NON validée » et les deux branches `sauvegarde/…-avant-fusion-20261106-2315` sont intacts. Aucun commit, aucun push, aucun pipeline réel, aucun Telegram.
Tests : bet_agent 686 passés, backend 267 passés.

## Phase 1 — sécurité des envois
Bilans uniquement pour les runs envoyés ; envois partiels et doublons corrigés (réessais Telegram sûrs, run partiel compté comme envoyé) ; alertes sur abandon, erreur, envoi partiel, run bloqué ; aucune dépense IA quand la collecte est vide.

## Phase 2 — fiabilité du moteur
`SEUIL_PROBA_MIN` robuste et divisions par zéro supprimées ; profils du formulaire et de secours unifiés (`profils_smart.py`) ; garde « un run envoyé bloque le jour quel que soit son statut » ; statistiques, bilans, mémoire et qualité des marchés alignés sur la seule définition « coupon envoyé ».

## Phase 3 — mesure et maîtrise
Coûts et tokens par modèle et vainqueur du vote enregistrés ; budget IA journalier (3 $, UTC, alerte à 80 % et à l'épuisement, aucun appel payant à budget épuisé) ; garde légère du cron (≈ 20 passages sur 24 ne coûtent plus rien) ; outils d'aperçu et d'export de la mémoire.

## Opérations sur la base réalisées le 07/11/2026 (toutes vérifiées)
| Opération | Résultat |
|---|---|
| Sauvegarde de la mémoire (`memoire_agent_sauvegarde_20261107`) | 8 lignes, empreinte identique à la source, restauration prouvée par une table de test (0 différence) ; accès public fermé |
| 180 corrections d'heures (confiance forte) | 180 lignes modifiées (garde « exactement 180 »), empreinte `id;heure` identique au CSV ; 598 matchs restent sans heure (528 sans solution + 70 en attente) ; les 528 sans solution : empreinte des identifiants et des lignes identiques à l'état d'avant ; reste de la table `matchs` : empreinte identique à l'état d'avant |

## Clôture (07/11/2026) — état final
**Opérations réalisées et vérifiées sur la base :**
| Opération | Résultat |
|---|---|
| Suppression du match 21 (run 2) | Exécutée par l'utilisateur dans l'éditeur SQL de Supabase (la confirmation du serveur n'arrivait pas à l'utilisateur) : 1 ligne supprimée (`21, 2, Slovenia, Scotland`). Contrôle : match 9 conservé, 2 959 matchs, empreinte des matchs restants identique à l'état d'avant (`706569dc28e47106643e513fad65eb6a`), 598 matchs sans heure inchangés, 0 jambe et 0 cote touchées |
| Vérification 01 relancée | 0 doublon sur coupons, jambes, matchs, mémoire et plans |
| Cinq index uniques (créés à 01h14 UTC, hors cron, en une opération « tout ou rien ») | `uq_coupons_run_profil` (32 ko), `uq_jambes_coupon_pari` (224 ko), `uq_matchs_run_equipes` (152 ko), `uq_plans_run_non_clos` (partiel, 16 ko), `uq_memoire_jour_type` (16 ko) : tous uniques, valides et prêts ; définitions conformes au fichier 03 ; aucune donnée modifiée (coupons 378, jambes 2 212, runs 271, empreinte de `memoire_agent` inchangée) |

**Décisions de l'utilisateur appliquées** : la table de test `memoire_agent_restauration_test` reste en base (RLS activée, droits publics retirés) ; la sauvegarde mémoire est validée et intacte ; les 180 corrections d'heures sont terminées et jamais rejouées ; les 45 (moyenne) et 25 (faible) restent interdites ; les cinq études préparées sont conservées sans remplacement.

**Reliquat unique :** le remplacement des cinq études, en attente de la validation de `etudes_finales_a_valider.md` (SQL prêt et bloqué par un garde : `07_remplacement_etudes_PRET_NON_EXECUTE.sql`).

Rien n'est committé ni poussé (consigne de l'utilisateur) : le travail reste dans l'arbre de travail de `claude/analyse-matchs-football-796va6`. `main`, le stash et les deux branches de sauvegarde sont intacts.

**Retour arrière des index si nécessaire** : `99_annulation.sql` (supprime seulement les index). Restauration du match 21 : `rapports/phase3/sauvegardes/match_21_doublon_run2_restauration.sql`.
