-- Phase 3 — contraintes d'unicité (à lancer APRÈS 01 et 02, une fois 01 entièrement vide). Une transaction : tout ou rien.
-- Index uniques (et non ALTER TABLE ... ADD CONSTRAINT) pour pouvoir utiliser des expressions et des conditions partielles.
begin;

-- 1. Un seul coupon par profil et par run.
create unique index if not exists uq_coupons_run_profil on coupons (run_id, profil);

-- 2. Pas deux fois le même pari dans un coupon (handicap NULL traité comme une valeur).
create unique index if not exists uq_jambes_coupon_pari
  on jambes (coupon_id, libelle_match, marche, selection, coalesce(handicap, -999));

-- 3. Un match n'apparaît qu'une fois par run.
create unique index if not exists uq_matchs_run_equipes on matchs (run_id, domicile, exterieur);

-- 4. Un seul plan de vérification NON CLOS par run (le code remplace uniquement les plans non clos ; un plan clos reste en historique).
create unique index if not exists uq_plans_run_non_clos on plans_verification (run_id) where rapport_final_envoye is false;

-- 5. Une seule étude par jour et par type dans la mémoire.
create unique index if not exists uq_memoire_jour_type on memoire_agent (jour, type);

commit;

-- Volontairement ABSENT : index unique sur cotes (match_id, marche_id, handicap, periode, selection). 0 doublon aujourd'hui, mais
-- ~40-50 Mo d'index supplémentaires sur 1,05 million de lignes (la table pèse déjà 141 Mo, index compris 32 Mo).
-- EXÉCUTÉ le 07/11/2026 à 01h14 UTC (hors fenêtre du cron) : cinq index créés, tous uniques, valides et prêts ; aucune donnée modifiée.
