// Edge Function Supabase « api » — API privée en ligne du projet analyse-football.
//
// Lecture des runs, coupons, matchs, cotes et statistiques + archives (bucket Storage privé
// « archives »). Toutes les routes exigent l'en-tête X-API-Key, vérifié côté base contre le
// jeton rangé dans le Vault (fonction public.api_jeton_valide). Le JWT Supabase n'est pas
// utilisé (verify_jwt = false) : c'est ce jeton qui protège l'API.
//
// URL : https://fpwsitpdkruoknwmgjzr.supabase.co/functions/v1/api/<route>
// Déploiement : outil Supabase MCP « deploy_edge_function » ou
//   supabase functions deploy api --no-verify-jwt --project-ref fpwsitpdkruoknwmgjzr

import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "npm:@supabase/supabase-js@2";

const supabase = createClient(
  Deno.env.get("SUPABASE_URL")!,
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
  { auth: { persistSession: false } },
);

const BUCKET = "archives";
const JAMBES = "jambes(id, match_id, libelle_match, categorie, marche, handicap, selection, cote, " +
  "proba_modele_pct, edge_pct, guide, onglet, resultat)";
const COUPON = `id, run_id, jour, profil, nom, cote_min, cote_max, cote_totale, proba_combinee_pct, statut, texte, ${JAMBES}`;
const RUN = "id, lance_le, termine_le, source, statut, detail, nb_matchs, nb_matchs_avec_marches, nb_marches, envoye_telegram";
const MATCH = "id, run_id, domicile, exterieur, ligue, coup_envoi, fixture_id_oddspapi, score_domicile, score_exterieur";

class ErreurApi extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function reponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
  });
}

function verifier(resultat: { data: unknown; error: { message: string } | null }) {
  if (resultat.error) throw new Error(resultat.error.message);
  return resultat.data;
}

function entier(valeur: string | null, defaut: number, min: number, max: number): number {
  if (valeur === null || valeur === "") return defaut;
  const n = Number(valeur);
  if (!Number.isInteger(n) || n < min || n > max) {
    throw new ErreurApi(422, `Paramètre entier attendu entre ${min} et ${max}`);
  }
  return n;
}

function jour(valeur: string | null): string | null {
  if (!valeur) return null;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(valeur) || Number.isNaN(Date.parse(valeur))) {
    throw new ErreurApi(422, "Paramètre jour attendu au format AAAA-MM-JJ");
  }
  return valeur;
}

function trouve<T>(data: T | null, quoi: string): T {
  if (!data) throw new ErreurApi(404, `${quoi} introuvable`);
  return data;
}

async function jetonValide(req: Request): Promise<boolean> {
  const jeton = req.headers.get("x-api-key");
  if (!jeton || jeton.length > 200) return false;
  return verifier(await supabase.rpc("api_jeton_valide", { jeton })) === true;
}

// Chemins d'archive : AAAA-MM-JJ/nom.json uniquement (pas de "..", pas de sous-dossiers libres).
const CHEMIN_ARCHIVE = /^\d{4}-\d{2}-\d{2}\/[A-Za-z0-9_.-]{1,120}\.json$/;

async function router(req: Request, chemin: string, params: URLSearchParams): Promise<unknown> {
  const [ressource, id, sous] = chemin.split("/").filter(Boolean);
  const methode = req.method;

  if (methode === "GET" && ressource === "sante" && !id) {
    verifier(await supabase.from("runs").select("id", { head: true, count: "exact" }));
    return { statut: "ok", base: "postgresql", stockage: BUCKET };
  }

  if (methode === "GET" && ressource === "runs") {
    if (!id) {
      const limite = entier(params.get("limite"), 20, 1, 200);
      return verifier(await supabase.from("runs").select(RUN).order("id", { ascending: false }).limit(limite));
    }
    const runId = entier(id, 0, 1, 2_000_000_000);
    const run = verifier(await supabase.from("runs").select(`${RUN}, coupons(${COUPON})`)
      .eq("id", runId).order("profil", { referencedTable: "coupons" }).maybeSingle());
    return trouve(run, "Run");
  }

  if (methode === "GET" && ressource === "coupons") {
    if (!id) {
      let requete = supabase.from("coupons").select(COUPON)
        .order("jour", { ascending: false }).order("run_id", { ascending: false }).order("profil")
        .limit(entier(params.get("limite"), 50, 1, 500));
      const j = jour(params.get("jour"));
      if (j) requete = requete.eq("jour", j);
      if (params.get("profil")) requete = requete.eq("profil", params.get("profil")!);
      if (params.get("statut")) requete = requete.eq("statut", params.get("statut")!);
      return verifier(await requete);
    }
    const coupon = verifier(await supabase.from("coupons").select(COUPON)
      .eq("id", entier(id, 0, 1, 2_000_000_000)).maybeSingle());
    return trouve(coupon, "Coupon");
  }

  if (methode === "GET" && ressource === "matchs") {
    if (!id) {
      let requete = supabase.from("matchs").select(MATCH)
        .order("coup_envoi", { ascending: false, nullsFirst: false }).order("id", { ascending: false })
        .limit(entier(params.get("limite"), 100, 1, 1000));
      const j = jour(params.get("jour"));
      if (j) {
        const lendemain = new Date(Date.parse(j) + 86_400_000).toISOString().slice(0, 10);
        requete = requete.gte("coup_envoi", j).lt("coup_envoi", lendemain);
      }
      if (params.get("run_id")) requete = requete.eq("run_id", entier(params.get("run_id"), 0, 1, 2_000_000_000));
      return verifier(await requete);
    }
    const match = verifier(await supabase.from("matchs")
      .select(`${MATCH}, donnees, cotes(marche_id, marche, handicap, periode, selection, cote)`)
      .eq("id", entier(id, 0, 1, 2_000_000_000)).maybeSingle());
    return trouve(match, "Match");
  }

  if (methode === "GET" && ressource === "statistiques" && !id) {
    return verifier(await supabase.rpc("api_statistiques"));
  }

  if (ressource === "archives") {
    if (methode === "GET" && !id) {
      const prefixe = params.get("prefixe") ?? "";
      if (prefixe && !/^\d{4}-\d{2}-\d{2}$/.test(prefixe)) {
        throw new ErreurApi(422, "prefixe attendu au format AAAA-MM-JJ (ou vide pour la liste des jours)");
      }
      return verifier(await supabase.storage.from(BUCKET).list(prefixe, {
        limit: 200, sortBy: { column: "name", order: "desc" },
      }));
    }
    if (methode === "GET" && id === "lien" && !sous) {
      const fichier = params.get("chemin") ?? "";
      if (!CHEMIN_ARCHIVE.test(fichier)) throw new ErreurApi(422, "chemin invalide (AAAA-MM-JJ/nom.json)");
      const lien = verifier(await supabase.storage.from(BUCKET).createSignedUrl(fichier, 3600)) as { signedUrl: string };
      return { chemin: fichier, url: lien.signedUrl, expire_dans_secondes: 3600 };
    }
    if (methode === "POST" && !id) {
      let corps: { chemin?: unknown; contenu?: unknown };
      try {
        corps = await req.json();
      } catch {
        throw new ErreurApi(422, "Corps JSON invalide");
      }
      if (typeof corps.chemin !== "string" || !CHEMIN_ARCHIVE.test(corps.chemin)) {
        throw new ErreurApi(422, "chemin invalide (AAAA-MM-JJ/nom.json)");
      }
      if (corps.contenu === undefined) throw new ErreurApi(422, "contenu manquant");
      const blob = new Blob([JSON.stringify(corps.contenu)], { type: "application/json" });
      verifier(await supabase.storage.from(BUCKET).upload(corps.chemin, blob, {
        contentType: "application/json", upsert: true,
      }));
      return { archive: corps.chemin, octets: blob.size };
    }
  }

  throw new ErreurApi(404, "Route inconnue");
}

Deno.serve(async (req: Request) => {
  const url = new URL(req.url);
  // L'URL publique est /functions/v1/api/<route> ; la fonction reçoit /api/<route>.
  const chemin = url.pathname.replace(/^.*?\/api(?=\/|$)/, "") || "/";
  try {
    if (!(await jetonValide(req))) return reponse({ detail: "En-tête X-API-Key manquant ou invalide." }, 401);
    const data = await router(req, chemin, url.searchParams);
    return reponse(data, req.method === "POST" ? 201 : 200);
  } catch (e) {
    if (e instanceof ErreurApi) return reponse({ detail: e.message }, e.status);
    console.error("Erreur API :", e);
    return reponse({ detail: "Erreur interne" }, 500);
  }
});
