-- Généré depuis app/models.py par `python -m app.generer_schema_sql` — ne pas éditer à la main.
-- À exécuter dans Supabase (SQL Editor) ; le backend crée aussi les tables au démarrage.
-- Sécurité : RLS sans policy + aucun droit pour les rôles publics (anon / authenticated) :
-- seul le backend (rôle postgres) lit et écrit ces tables.

CREATE TABLE IF NOT EXISTS runs (
	id SERIAL NOT NULL, 
	lance_le TIMESTAMP WITH TIME ZONE NOT NULL, 
	termine_le TIMESTAMP WITH TIME ZONE, 
	source VARCHAR(20) NOT NULL, 
	statut VARCHAR(20) NOT NULL, 
	detail TEXT, 
	nb_matchs INTEGER NOT NULL, 
	nb_matchs_avec_marches INTEGER NOT NULL, 
	nb_marches INTEGER NOT NULL, 
	envoye_telegram BOOLEAN NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS ix_runs_statut ON runs (statut);
ALTER TABLE public.runs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.runs FROM anon, authenticated;

CREATE TABLE IF NOT EXISTS coupons (
	id SERIAL NOT NULL, 
	run_id INTEGER NOT NULL, 
	jour DATE NOT NULL, 
	profil VARCHAR(20) NOT NULL, 
	nom VARCHAR(80) NOT NULL, 
	cote_min FLOAT, 
	cote_max FLOAT, 
	cote_totale FLOAT, 
	proba_combinee_pct FLOAT, 
	texte TEXT, 
	statut VARCHAR(20) NOT NULL, 
	bilan_envoye BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(run_id) REFERENCES runs (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_coupons_jour ON coupons (jour);
CREATE INDEX IF NOT EXISTS ix_coupons_run_id ON coupons (run_id);
CREATE INDEX IF NOT EXISTS ix_coupons_statut ON coupons (statut);
ALTER TABLE public.coupons ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.coupons FROM anon, authenticated;

CREATE TABLE IF NOT EXISTS matchs (
	id SERIAL NOT NULL, 
	run_id INTEGER NOT NULL, 
	domicile VARCHAR(120) NOT NULL, 
	exterieur VARCHAR(120) NOT NULL, 
	ligue VARCHAR(120), 
	coup_envoi TIMESTAMP WITH TIME ZONE, 
	fixture_id_oddspapi VARCHAR(64), 
	fixture_id_api_football INTEGER, 
	score_domicile INTEGER, 
	score_exterieur INTEGER, 
	donnees JSON, 
	PRIMARY KEY (id), 
	FOREIGN KEY(run_id) REFERENCES runs (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_matchs_coup_envoi ON matchs (coup_envoi);
CREATE INDEX IF NOT EXISTS ix_matchs_fixture_id_oddspapi ON matchs (fixture_id_oddspapi);
CREATE INDEX IF NOT EXISTS ix_matchs_run_id ON matchs (run_id);
ALTER TABLE public.matchs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.matchs FROM anon, authenticated;

CREATE TABLE IF NOT EXISTS cotes (
	id SERIAL NOT NULL, 
	match_id INTEGER NOT NULL, 
	marche_id VARCHAR(32) NOT NULL, 
	marche VARCHAR(120) NOT NULL, 
	handicap FLOAT, 
	periode VARCHAR(32), 
	selection VARCHAR(64) NOT NULL, 
	cote FLOAT NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(match_id) REFERENCES matchs (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_cotes_match_id ON cotes (match_id);
ALTER TABLE public.cotes ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.cotes FROM anon, authenticated;

CREATE TABLE IF NOT EXISTS jambes (
	id SERIAL NOT NULL, 
	coupon_id INTEGER NOT NULL, 
	match_id INTEGER, 
	libelle_match VARCHAR(250) NOT NULL, 
	domicile VARCHAR(120), 
	fixture_id_oddspapi VARCHAR(64), 
	categorie VARCHAR(160) NOT NULL, 
	marche VARCHAR(160) NOT NULL, 
	handicap FLOAT, 
	selection VARCHAR(64) NOT NULL, 
	cote FLOAT NOT NULL, 
	proba_modele_pct FLOAT, 
	edge_pct FLOAT, 
	guide TEXT, 
	onglet VARCHAR(160), 
	resultat VARCHAR(20) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(coupon_id) REFERENCES coupons (id) ON DELETE CASCADE, 
	FOREIGN KEY(match_id) REFERENCES matchs (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_jambes_coupon_id ON jambes (coupon_id);
CREATE INDEX IF NOT EXISTS ix_jambes_fixture_id_oddspapi ON jambes (fixture_id_oddspapi);
CREATE INDEX IF NOT EXISTS ix_jambes_match_id ON jambes (match_id);
CREATE INDEX IF NOT EXISTS ix_jambes_resultat ON jambes (resultat);
ALTER TABLE public.jambes ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.jambes FROM anon, authenticated;
