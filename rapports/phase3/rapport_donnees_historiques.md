# Rapport — données historiques et contraintes d'unicité (aucune donnée modifiée)

Examen du 06/11/2026, exclusivement par des requêtes SELECT. Aucune correction n'a été appliquée.

## 1. Matchs sans heure de coup d'envoi — 778 sur 2 960

- Répartition par run : 509 dans les runs < 100, 146 dans 100-199, 117 dans 200-249, **6 seulement dans les runs ≥ 250**. Le problème est essentiellement historique ; 9 matchs sont sans heure à partir du run 240.
- 282 de ces matchs portent des jambes ; 11 ont des jambes encore « en attente » dans des runs envoyés. Sans heure, le plan de vérification les traite « une fois par heure » (sans fin estimée).
- Les `donnees` JSON ne contiennent aucune heure : elle ne peut pas être reconstruite depuis le match lui-même.
- **Récupérable** : 250 matchs ont exactement une heure candidate (même affiche, autre run, heure connue entre 1 jour avant et 4 jours après le lancement), 0 ambigu. **528 sont irrécupérables.**
- Proposition (non exécutée) : `backend/migrations/phase3/04_corrections_proposees_NON_RECOMMANDEES_SANS_REVUE.sql` — transaction annulée par défaut (`rollback`), à relire. Les 528 autres restent sans heure (aucun impact sur les résultats futurs).
- Prévention : les 6 cas récents (≥ 250) méritent un examen de la collecte du jour correspondant ; je ne l'ai pas fait ici.

## 2. Jambes sans match associé — 41 (toutes « en attente »)

- Uniquement les runs **266 (18 jambes)** et **267 (23 jambes)** ; aucun run envoyé n'est concerné (0 jambe sans match dans un run envoyé) : aucun impact sur les résultats réels.
- Ces runs n'ont aucune ligne dans `matchs` (la collecte n'avait pas pu être enregistrée) : les 41 jambes **ne sont pas rattachables** (ni par identifiant de fixture, ni par libellé).
- Proposition : ne rien modifier ; elles restent exclues des statistiques et du bilan (Phases 1-2). Si vous préférez un état explicite, un statut `non_verifiable` serait possible sur votre demande.

## 3. Coupons jamais vérifiés

- 23 coupons « en attente » : **5 datent de plus de 2 jours** (c144, c145, c146, c152, c153, tous d'octobre) ; 3 appartiennent à des runs envoyés (c144, c152, c153), 2 à des runs non envoyés.
- Un seul coupon envoyé n'a **aucune jambe jugée** : c153 (run 134, 12/10, 2 jambes en attente).
- Aucune incohérence détectée : 0 coupon « perdu » sans jambe perdue ; 0 bilan à envoyer pour un coupon clos d'un run envoyé.
- 17 coupons sont sans jambe (statut « vide ») : normaux (abstentions).
- Proposition : relancer la vérification sur les 3 coupons envoyés (leurs matchs sont terminés depuis longtemps) ; ceux qui ne se laissent pas juger passent en `non_verifiable` (par une opération autorisée, pas automatique).

## 4. Doublons existants

| Table | Clé testée | Résultat |
|---|---|---|
| `coupons` | (run, profil) | 0 |
| `jambes` | (coupon, match, marché, sélection, ligne) | 0 |
| `matchs` | (run, domicile, extérieur) | **1** : run 2, Slovenia - Scotland (ids 9 et 21), sans cote ni jambe |
| `cotes` | (match, marché, ligne, période, sélection) — 1 097 991 lignes | 0 |
| `memoire_agent` | (jour, type) | 0 |
| `plans_verification` | run (plans non clos) | 0 |

Autre constat (non corrigeable par une contrainte) : 75 couples (coupon, match) ont deux jambes sur le même match, héritage de l'ancien moteur qui l'autorisait.

## 5. Contraintes d'unicité préparées (non exécutées)

Fichiers : `backend/migrations/phase3/` (lisez `00_LISEZMOI.md`).

| Index | Données actuelles | Avis |
|---|---|---|
| `uq_coupons_run_profil` | propre | recommandé |
| `uq_jambes_coupon_pari` (ligne NULL = valeur) | propre | recommandé |
| `uq_matchs_run_equipes` | **1 doublon à supprimer d'abord** (fichier 02, avec garde-fous) | recommandé |
| `uq_plans_run_non_clos` (partiel) | propre | recommandé : le code remplace seulement les plans non clos |
| `uq_memoire_jour_type` | propre | recommandé |
| unicité sur `cotes` | propre | **déconseillée** : +40-50 Mo d'index sur une base déjà pleine (la table pèse 141 Mo) |

Vérification côté application : `backend/tests/test_migrations_unicite.py` rejoue ces index sur la base de test ; les doublons sont refusés, et un run complet, le passage cron, l'envoi et le plan fonctionnent normalement avec les contraintes. Retour arrière : `99_annulation.sql` (supprime uniquement les index).
Ordre prévu : 01 (vérifications) → 02 (suppression d'un match en double) → 03 (index) — chaque étape sur autorisation expresse.
