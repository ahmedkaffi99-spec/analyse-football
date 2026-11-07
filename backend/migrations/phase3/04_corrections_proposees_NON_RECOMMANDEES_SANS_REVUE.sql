-- Phase 3 — PROPOSITION de correction des heures de coup d'envoi manquantes. NON EXÉCUTÉE. À relire avant toute exécution.
-- Principe : un match sans heure reçoit l'heure d'un match IDENTIQUE (mêmes équipes) d'un autre run, avec une heure connue, tombant entre
-- 1 jour avant et 4 jours après le lancement du run. Au 06/11/2026 : 250 matchs sur 778 ont exactement une heure candidate, 0 sont ambigus,
-- 528 restent sans solution (principalement les runs 1 à 250, collectes anciennes sans heure).
-- Aperçu (lecture seule) à lancer d'abord :
--   with sans as (...)  -- identique à la sous-requête ci-dessous, avec select au lieu de update.
begin;
with sans as (
  select m.id, m.domicile, m.exterieur, r.lance_le from matchs m join runs r on r.id = m.run_id where m.coup_envoi is null),
candidats as (
  select s.id, min(t.coup_envoi) as heure, count(distinct t.coup_envoi) as n
  from sans s join matchs t on t.domicile = s.domicile and t.exterieur = s.exterieur and t.coup_envoi is not null and t.id <> s.id
   and t.coup_envoi between s.lance_le - interval '1 day' and s.lance_le + interval '4 days'
  group by s.id)
update matchs set coup_envoi = c.heure from candidats c where matchs.id = c.id and c.n = 1 and matchs.coup_envoi is null;
-- Vérifier le nombre de lignes modifiées (attendu : 250) puis : commit;   (sinon : rollback;)
rollback;
