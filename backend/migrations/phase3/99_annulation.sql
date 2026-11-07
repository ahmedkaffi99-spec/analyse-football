-- Annule 03_contraintes_unicite.sql (supprime seulement les index créés par ce fichier ; aucune donnée touchée).
drop index if exists uq_coupons_run_profil;
drop index if exists uq_jambes_coupon_pari;
drop index if exists uq_matchs_run_equipes;
drop index if exists uq_plans_run_non_clos;
drop index if exists uq_memoire_jour_type;
