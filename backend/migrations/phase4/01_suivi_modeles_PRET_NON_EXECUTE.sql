-- PHASE 4.2/4.3 — Suivi individuel des modèles IA. PRÊT, NON EXÉCUTÉ : nécessite une autorisation Supabase spécifique.
-- Principe : tables SÉPARÉES du vote collectif et des coupons réels (coupons/jambes) ; aucune ligne existante n'est modifiée.
create table if not exists suivi_modeles_coupons (
  id bigserial primary key,
  protocole text not null,                 -- ex. 'P4-2026-11'
  jour date not null,                      -- jour des matchs du protocole
  modele text not null,                    -- identifiant canonique (voir suivi_modeles.MODELES)
  source text not null check (source in ('individuel')),   -- 'vote_collectif' est refusé par construction
  run_id integer,
  profil text not null,
  cle_unique text not null,                -- empreinte des sélections : anti-doublon
  cote_totale double precision,
  proba_combinee_pct double precision,     -- produit des probabilités du catalogue Python (jamais une probabilité propre au modèle)
  statut text not null default 'en_attente' check (statut in ('en_attente','gagne','perdu','annule')),
  tokens_entree integer, tokens_sortie integer, cout_usd double precision,
  cree_le timestamptz not null default now(),
  unique (protocole, jour, modele, profil, cle_unique)
);
create table if not exists suivi_modeles_jambes (
  id bigserial primary key,
  coupon_id bigint not null references suivi_modeles_coupons(id) on delete cascade,
  match_id integer not null,
  marche text not null, selection text not null, handicap double precision,
  cote double precision not null, proba_pct double precision,
  resultat text not null default 'en_attente' check (resultat in ('en_attente','gagne','perdu','push','demi_gagne','demi_perdu','non_verifiable')),
  unique (coupon_id, match_id, marche, selection, handicap)
);
alter table suivi_modeles_coupons enable row level security;
alter table suivi_modeles_jambes enable row level security;
