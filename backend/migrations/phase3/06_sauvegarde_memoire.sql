-- Phase 3 — sauvegarde exacte de la mémoire AVANT toute régénération (à lancer sur autorisation ; crée une table de copie, ne modifie rien d'autre).
-- Alternative sans écriture en base : python -m app.taches apprendre --exporter sauvegarde_memoire.json (copie JSON, lecture seule).
create table if not exists memoire_agent_sauvegarde_20261107 as select * from memoire_agent;
alter table public.memoire_agent_sauvegarde_20261107 enable row level security;   -- toujours protéger une table créée à la main
revoke all on table public.memoire_agent_sauvegarde_20261107 from anon, authenticated;
select count(*) as lignes_sauvegardees from memoire_agent_sauvegarde_20261107;   -- attendu : 8
-- Restauration d'une étude : insert ... select depuis cette table, après suppression de la version régénérée.
-- Nettoyage final (plus tard, sur demande) : drop table memoire_agent_sauvegarde_20261107;
-- EXÉCUTÉ le 07/11/2026 : 8 lignes, empreinte a509b8a390bb2aea24065a4be59b7ee4 identique à memoire_agent ; restauration testée.
