-- Phase 3 — vérifications AVANT toute contrainte d'unicité (lecture seule). Résultat attendu : 0 ligne partout, sauf indication.
-- Constat du 06/11/2026 : seul le doublon de matchs du run 2 existait (m9 / m21, ni cotes ni jambes).

select 'coupons (run_id, profil)' as controle, run_id, profil, count(*) from coupons group by run_id, profil having count(*) > 1;

select 'jambes (coupon, match, marché, sélection, ligne)' as controle, coupon_id, libelle_match, marche, selection, handicap, count(*)
from jambes group by coupon_id, libelle_match, marche, selection, handicap having count(*) > 1;

select 'matchs (run_id, domicile, exterieur)' as controle, run_id, domicile, exterieur, count(*), array_agg(id) as ids
from matchs group by run_id, domicile, exterieur having count(*) > 1;   -- attendu : 1 ligne (run 2, ids {9,21}) avant 02, 0 après

select 'memoire_agent (jour, type)' as controle, jour, type, count(*) from memoire_agent group by jour, type having count(*) > 1;

select 'plans_verification non clos (run_id)' as controle, run_id, count(*) from plans_verification
where rapport_final_envoye is false group by run_id having count(*) > 1;

-- Le doublon de matchs porte-t-il des cotes ou des jambes ? (attendu : 0 et 0)
select 'dependances du doublon' as controle,
       (select count(*) from cotes where match_id in (9, 21)) as cotes,
       (select count(*) from jambes where match_id in (9, 21)) as jambes;
