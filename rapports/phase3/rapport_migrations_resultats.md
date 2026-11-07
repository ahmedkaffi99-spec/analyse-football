# Migrations SQL — résultats des vérifications (07/11/2026) — rien n'a été exécuté en écriture

## Migration 01 — vérifications en lecture seule (exécutées)

| Contrôle | Lignes en double |
|---|---|
| `coupons` (run, profil) | 0 |
| `jambes` (coupon, match, marché, sélection, ligne) | 0 |
| **`matchs` (run, domicile, extérieur)** | **1** |
| `memoire_agent` (jour, type) | 0 |
| `plans_verification` non clos (run) | 0 |
| cotes rattachées au doublon | 0 |
| jambes rattachées au doublon | 0 |

## Migration 02 — la ligne exacte concernée (suppression PRÉPARÉE, non exécutée)

Doublon dans le run 2 : même affiche, même heure, mêmes identifiants de fixture, aucune cote, aucune jambe.

| | match 9 (conservé) | **match 21 (à supprimer)** |
|---|---|---|
| run | 2 | 2 |
| affiche | Slovenia – Scotland | Slovenia – Scotland |
| ligue | UEFA Nations League | UEFA Nations League |
| coup d'envoi | 2026-09-26 13:00 UTC | 2026-09-26 13:00 UTC |
| fixture oddspapi / API-Football | id1003621974861510 / 1545658 | id1003621974861510 / 1545658 |
| score | NULL / NULL | NULL / NULL |
| taille des `donnees` | 2 778 caractères | 2 404 caractères |
| cotes / jambes liées | 0 / 0 | 0 / 0 |

Le match 21 est le plus récent et son JSON `donnees` est plus court : le match 9 contient davantage d'informations, d'où le choix de le conserver.
- **Sauvegarde exacte de la ligne 21** : `rapports/phase3/sauvegardes/match_21_doublon_run2.json`.
- **Ordre de restauration** : `rapports/phase3/sauvegardes/match_21_doublon_run2_restauration.sql`.
- **Garde-fous du fichier 02** : il refuse de supprimer si le doublon a changé ou si le match 21 porte des cotes ou des jambes. Il ne supprime que cette ligne (`id = 21`).

## Migration 03 — cinq index uniques (PRÉPARÉS, non exécutés)

`uq_coupons_run_profil`, `uq_jambes_coupon_pari`, `uq_matchs_run_equipes`, `uq_plans_run_non_clos` (partiel), `uq_memoire_jour_type`.
- Seul `uq_matchs_run_equipes` est bloqué tant que le doublon n'est pas supprimé : la création échouerait et toute la transaction serait annulée.
- Les quatre autres index passeraient dès aujourd'hui.
- Annulation : `99_annulation.sql`.

Ordre proposé après votre autorisation : 02 (suppression) → relancer 01 (doit être vide) → 03.

## Précontrôles de la migration 03 — résultats du 07/11/2026 et risques

Résultats : doublons coupons 0, jambes 0, mémoire 0, plans non clos 0, **matchs 1** (le match 21 ci-dessus). Les index uniques déjà présents en base (`uq_cote_gratuite`, `uq_fd_match`, `uq_hist_cote_capture_jour`, `uq_mapping_equipe`) portent sur d'autres tables : aucun conflit de nom avec les cinq nouveaux index.

| Risque | Évaluation | Parade |
|---|---|---|
| `uq_matchs_run_equipes` échoue tant que le match 21 existe | Certain aujourd'hui | Suppression (02) d'abord ; la transaction du fichier 03 est de toute façon « tout ou rien » |
| Verrou pendant la création des index | Négligeable : tables de 400 à 3 000 lignes | Lancer hors de la fenêtre du cron (6h-14h UTC) |
| Un run futur tente d'insérer un doublon (ex. deux coupons de même clé via `profils_json` manuel) | Faible ; le moteur interdit déjà deux fois le même pari dans un coupon | L'erreur surviendrait après l'envoi : run marqué `[APRES_ENVOI]`, jamais renvoyé (Phase 2), coupons non enregistrés |
| Deux études du même jour écrites en parallèle (mémoire) | Très faible | La 2e écriture échouerait au lieu de créer un doublon : voulu |
| Index partiel des plans (`rapport_final_envoye is false`) | Géré : le code remplace seulement les plans non clos ; testé | Annulation possible (`99_annulation.sql`) |
| Taille | Quelques dizaines de ko au total | Aucune |
| Retour arrière | Immédiat, sans perte de données | `99_annulation.sql` supprime seulement les index |

Les tests `backend/tests/test_migrations_unicite.py` rejouent les cinq index sur la base de test : doublons refusés, run complet, relance cron, envoi et plan fonctionnent normalement.
