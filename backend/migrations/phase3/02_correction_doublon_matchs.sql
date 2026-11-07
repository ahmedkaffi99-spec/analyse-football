-- Phase 3 — supprime le match en double du run 2 (Slovenia - Scotland : ids 9 et 21, aucune cote, aucune jambe). On garde le plus ancien (9).
-- Garde-fou : ne supprime rien si l'un des deux porte des cotes ou des jambes, ou si le doublon a changé depuis l'examen.
begin;
do $$
begin
  if (select count(*) from matchs where run_id = 2 and domicile = 'Slovenia' and exterieur = 'Scotland') <> 2 then
    raise exception 'état inattendu : doublon différent de celui examiné le 06/11/2026';
  end if;
  if exists (select 1 from cotes where match_id = 21) or exists (select 1 from jambes where match_id = 21) then
    raise exception 'le match 21 porte des cotes ou des jambes : suppression refusée';
  end if;
end $$;
delete from matchs where id = 21 and run_id = 2 and domicile = 'Slovenia' and exterieur = 'Scotland';
commit;
-- EXÉCUTÉ le 07/11/2026 par l'utilisateur (éditeur SQL Supabase), avec la requête gardée équivalente : 1 ligne supprimée (match 21, run 2), 2 959 matchs restants, empreinte inchangée.
