-- Objets Supabase de l'API en ligne et de l'archivage — appliqués sur le projet
-- fpwsitpdkruoknwmgjzr (migrations "storage_archives_et_api" et "api_lecture_service_role").
-- Rejouable : chaque instruction est idempotente. À exécuter APRÈS schema.sql.

-- 1) Bucket PRIVÉ pour archiver chaque run (collecte brute + coupons). Aucune policy sur
--    storage.objects : seuls le service_role (Edge Function) et postgres y accèdent.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('archives', 'archives', false, 20971520, array['application/json', 'text/plain'])
on conflict (id) do nothing;

-- 2) Jeton de l'API privée, généré aléatoirement (256 bits) et rangé chiffré dans le Vault.
do $$
begin
  if not exists (select 1 from vault.secrets where name = 'api_token') then
    perform vault.create_secret(encode(extensions.gen_random_bytes(32), 'hex'), 'api_token',
                                'Jeton X-API-Key de l''API privée analyse-football (Edge Function api)');
  end if;
end $$;

-- 3) Vérification du jeton, côté base (comparaison des empreintes), réservée au service_role.
create or replace function public.api_jeton_valide(jeton text)
returns boolean
language sql
security definer
set search_path = ''
as $$
  select coalesce(
    (select extensions.digest(jeton, 'sha256') = extensions.digest(decrypted_secret, 'sha256')
       from vault.decrypted_secrets where name = 'api_token' limit 1),
    false);
$$;
revoke all on function public.api_jeton_valide(text) from public, anon, authenticated;
grant execute on function public.api_jeton_valide(text) to service_role;

-- 4) Statistiques de performance (même calcul que app/services/statistiques.py).
create or replace function public.api_statistiques()
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
  with coupons_clos as (
    select c.profil, c.nom, c.statut,
      case
        when c.statut = 'perdu' then -1.0
        when c.statut = 'gagne' then coalesce(
          (select exp(sum(ln(j.cote))) from public.jambes j where j.coupon_id = c.id and j.resultat <> 'push'), 1.0) - 1.0
      end as gain
    from public.coupons c
  ),
  par_profil as (
    select profil, max(nom) as nom, count(*) as coupons,
      count(gain) as clos,
      count(*) filter (where statut = 'gagne') as gagnes,
      round(coalesce(sum(gain), 0)::numeric, 2) as gain_net_unites
    from coupons_clos group by profil
  ),
  par_categorie as (
    select categorie, count(*) as jugees, count(*) filter (where resultat = 'gagne') as gagnees
    from public.jambes where resultat in ('gagne', 'perdu') group by categorie
  )
  select jsonb_build_object(
    'profils', coalesce((select jsonb_agg(jsonb_build_object(
        'profil', profil, 'nom', nom, 'coupons', coupons, 'clos', clos, 'gagnes', gagnes,
        'taux_reussite_pct', case when clos > 0 then round(100.0 * gagnes / clos, 1) end,
        'gain_net_unites', gain_net_unites,
        'rendement_pct', case when clos > 0 then round(100.0 * gain_net_unites / clos, 1) end
      ) order by profil) from par_profil), '[]'::jsonb),
    'categories', coalesce((select jsonb_agg(jsonb_build_object(
        'categorie', categorie, 'jugees', jugees, 'gagnees', gagnees,
        'taux_reussite_pct', round(100.0 * gagnees / jugees, 1)
      ) order by categorie) from par_categorie), '[]'::jsonb)
  );
$$;
revoke all on function public.api_statistiques() from public, anon, authenticated;
grant execute on function public.api_statistiques() to service_role;

-- 5) L'Edge Function "api" lit les tables avec la clé service_role : lecture seule.
grant usage on schema public to service_role;
grant select on table public.runs, public.matchs, public.cotes, public.coupons, public.jambes to service_role;
