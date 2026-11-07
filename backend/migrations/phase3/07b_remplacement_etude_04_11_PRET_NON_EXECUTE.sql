-- Phase 4 — REMPLACEMENT de l'étude du 04/11 SEULE (id 15). PRÊT, NON EXÉCUTÉ. Texte validé par l'utilisateur le 07/11/2026 ; le remplacement en base
-- n'a PAS encore été autorisé. Garde md5 sur le texte et les stats d'origine ; exactement 1 ligne modifiée, sinon annulation. Retour arrière :
-- memoire_agent_sauvegarde_20261107. Pour exécuter après autorisation expresse : supprimer le bloc « garde de validation ».
do $$ begin raise exception 'NON AUTORISÉ : remplacement interdit tant que l''utilisateur ne l''a pas autorisé'; end $$; -- garde de validation
do $$
declare nb integer := 0; n1 integer;
begin
  update memoire_agent set contenu = $e15c$Bilan du jour : 0 coupon(s) gagné(s), 3 perdu(s) sur 3.
1 coupon(s) perdu(s) par UNE seule jambe (1 jambe(s) différente(s)) : Bristol City vs Wolves — Over Under Full Time (2.5) Under @1.85 (annoncé probabilité non enregistrée). Une jambe de plus dans un coupon est une chance de plus de perdre.
Match piège : Cardiff vs West Ham — 2 jambes DIFFÉRENTES perdues (Double Chance Full Time 12; Over Under Full Time (4.5) Under) : plusieurs paris sur un même match partagent le même scénario ; un résultat inattendu les fait tomber ensemble.
Jambe annoncée à 77.4 % perdue : Viking vs Sabah FA — Asian Handicap (-2.5) 2 (dans 1 coupon(s)).
Jambe annoncée à 77.2 % perdue : Cardiff vs West Ham — Double Chance Full Time 12 (dans 1 coupon(s)).
LEÇONS : 1) Les 3 coupons ont perdu : 🟢 sur 2 jambes (Viking AH -2,5 ; Cardiff DC 12), 🟠 sur 3 (Porto, PSV corners, Cardiff Under 4,5), 🔴 sur 1 (Bristol City Under 2,5). Cardiff-West Ham a fait perdre 2 paris différents. 2) Sur 17 jambes jugées, 14 ont une probabilité enregistrée : tranche 70-80 % = 9/14 réussies, 64,3 % pour 74,5 % annoncé (n=14) ; les compter vers 65 % dans la probabilité d'un coupon ; aucune règle tirée des 3 jambes sans probabilité. 3) Question : pourquoi les 5 jambes du coupon 🔴 n'ont ni probabilité ni edge enregistrés ?$e15c$, stats = $e15s${"par_proba": {"70-80 %": {"n": 14, "gagnees": 9, "reussite_pct": 64.3, "annoncee_pct": 74.5}}, "par_cote": {"cote < 1,30": {"n": 6, "gagnees": 4, "reussite_pct": 66.7, "annoncee_pct": 76.4}, "cote 1,30-1,50": {"n": 7, "gagnees": 4, "reussite_pct": 57.1, "annoncee_pct": 73.4}, "cote 1,50-2,00": {"n": 4, "gagnees": 3, "reussite_pct": 75.0, "annoncee_pct": 70.9, "sans_proba": 3}}, "par_categorie": {"Total": {"n": 8, "gagnees": 6, "reussite_pct": 75.0, "annoncee_pct": 75.6, "sans_proba": 3}, "Total Corners": {"n": 2, "gagnees": 1, "reussite_pct": 50.0, "annoncee_pct": 72.9}, "Total \u00c9quipe 2": {"n": 2, "gagnees": 2, "reussite_pct": 100.0, "annoncee_pct": 74.2}, "Total \u00c9quipe 1": {"n": 2, "gagnees": 1, "reussite_pct": 50.0, "annoncee_pct": 72.8}, "Handicap": {"n": 2, "gagnees": 1, "reussite_pct": 50.0, "annoncee_pct": 74.2}, "Double Chance": {"n": 1, "gagnees": 0, "reussite_pct": 0.0, "annoncee_pct": 77.2}}, "jambes_jugees": 17, "jambes_sans_proba": 3}$e15s$::json
   where id = 15 and jour = '2026-11-04' and md5(contenu) = '0e6c7ae951e899cbcb3fa42c6e35d2dd' and md5(stats::text) = 'db93ac69f8efaf0c40dc60585cde73bf';
  get diagnostics n1 = row_count; nb := nb + n1;
  if nb <> 1 then raise exception 'ANNULATION : % études modifiées au lieu de 1', nb; end if;
end $$;
