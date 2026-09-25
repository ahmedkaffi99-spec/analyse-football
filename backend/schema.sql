-- Généré depuis app/models.py par `python -m app.generer_schema_sql` — ne pas éditer à la main.
-- À exécuter dans Supabase (SQL Editor) ; le backend crée aussi les tables au démarrage.

CREATE SCHEMA IF NOT EXISTS "analyse_football";
-- Le schéma n'est pas exposé par l'API REST de Supabase ; on retire en plus tout accès
-- aux rôles publics (anon / authenticated) : seul le backend (rôle postgres) y accède.
REVOKE ALL ON SCHEMA "analyse_football" FROM anon, authenticated;

CREATE TABLE IF NOT EXISTS analyse_football.runs (
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
CREATE INDEX IF NOT EXISTS ix_analyse_football_runs_statut ON analyse_football.runs (statut);
ALTER TABLE analyse_football.runs ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS analyse_football.coupons (
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
	FOREIGN KEY(run_id) REFERENCES analyse_football.runs (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_analyse_football_coupons_jour ON analyse_football.coupons (jour);
CREATE INDEX IF NOT EXISTS ix_analyse_football_coupons_run_id ON analyse_football.coupons (run_id);
CREATE INDEX IF NOT EXISTS ix_analyse_football_coupons_statut ON analyse_football.coupons (statut);
ALTER TABLE analyse_football.coupons ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS analyse_football.matchs (
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
	FOREIGN KEY(run_id) REFERENCES analyse_football.runs (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_analyse_football_matchs_coup_envoi ON analyse_football.matchs (coup_envoi);
CREATE INDEX IF NOT EXISTS ix_analyse_football_matchs_fixture_id_oddspapi ON analyse_football.matchs (fixture_id_oddspapi);
CREATE INDEX IF NOT EXISTS ix_analyse_football_matchs_run_id ON analyse_football.matchs (run_id);
ALTER TABLE analyse_football.matchs ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS analyse_football.cotes (
	id SERIAL NOT NULL, 
	match_id INTEGER NOT NULL, 
	marche_id VARCHAR(32) NOT NULL, 
	marche VARCHAR(120) NOT NULL, 
	handicap FLOAT, 
	periode VARCHAR(32), 
	selection VARCHAR(64) NOT NULL, 
	cote FLOAT NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(match_id) REFERENCES analyse_football.matchs (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_analyse_football_cotes_match_id ON analyse_football.cotes (match_id);
ALTER TABLE analyse_football.cotes ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS analyse_football.jambes (
	id SERIAL NOT NULL, 
	coupon_id INTEGER NOT NULL, 
	match_id INTEGER, 
	libelle_match VARCHAR(250) NOT NULL, 
	domicile VARCHAR(120), 
	fixture_id_oddspapi VARCHAR(64), 
	categorie VARCHAR(40) NOT NULL, 
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
	FOREIGN KEY(match_id) REFERENCES analyse_football.matchs (id) ON DELETE SET NULL, 
	FOREIGN KEY(coupon_id) REFERENCES analyse_football.coupons (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_analyse_football_jambes_coupon_id ON analyse_football.jambes (coupon_id);
CREATE INDEX IF NOT EXISTS ix_analyse_football_jambes_fixture_id_oddspapi ON analyse_football.jambes (fixture_id_oddspapi);
CREATE INDEX IF NOT EXISTS ix_analyse_football_jambes_match_id ON analyse_football.jambes (match_id);
CREATE INDEX IF NOT EXISTS ix_analyse_football_jambes_resultat ON analyse_football.jambes (resultat);
ALTER TABLE analyse_football.jambes ENABLE ROW LEVEL SECURITY;
