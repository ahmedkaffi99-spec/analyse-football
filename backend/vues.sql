-- Vues de consultation (pas générées par app/models.py — les vues ne sont pas des tables ORM,
-- à appliquer manuellement dans Supabase si la base est recréée ailleurs). Déjà en place sur
-- le projet analyse-football (fpwsitpdkruoknwmgjzr) depuis le 30/09/2026 : demande explicite
-- de l'utilisateur, "une table/vue par match plus claire" — la table `cotes` stocke déjà TOUS
-- les marchés bruts collectés (200-300+ par match), ces vues évitent de les rejoindre à la
-- main à chaque consultation.

-- Une ligne = un match, avec le nombre de cotes/marchés distincts collectés et le contexte
-- (stats, head-to-head, blessures, prédictions API-Football) déjà groupé dans "donnees".
CREATE OR REPLACE VIEW public.vue_matchs_complets AS
SELECT
    m.id AS match_id,
    m.run_id,
    r.statut AS run_statut,
    m.domicile,
    m.exterieur,
    m.ligue,
    m.coup_envoi,
    m.fixture_id_oddspapi,
    m.fixture_id_api_football,
    m.score_domicile,
    m.score_exterieur,
    COUNT(c.id) AS nb_cotes,
    COUNT(DISTINCT c.marche_id) AS nb_marches_distincts,
    m.donnees
FROM public.matchs m
JOIN public.runs r ON r.id = m.run_id
LEFT JOIN public.cotes c ON c.match_id = m.id
GROUP BY m.id, r.statut;

REVOKE ALL ON public.vue_matchs_complets FROM anon, authenticated;

-- Une ligne = une cote, avec le contexte du match déjà joint (équipes, ligue) — pour parcourir
-- les 200-300 marchés d'UN match sans jointure manuelle.
CREATE OR REPLACE VIEW public.vue_cotes_par_match AS
SELECT
    c.id AS cote_id,
    m.id AS match_id,
    m.run_id,
    m.domicile,
    m.exterieur,
    m.ligue,
    m.coup_envoi,
    c.marche_id,
    c.marche,
    c.handicap,
    c.periode,
    c.selection,
    c.cote
FROM public.cotes c
JOIN public.matchs m ON m.id = c.match_id;

REVOKE ALL ON public.vue_cotes_par_match FROM anon, authenticated;
