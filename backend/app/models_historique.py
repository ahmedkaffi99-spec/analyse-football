"""Schéma HISTORIQUE pour le moteur d'analyse (moteur/) : séparé du schéma du pipeline
quotidien (models.py) — même base, tables distinctes (préfixe hist_), pour ne jamais risquer
le pipeline en production pendant que le moteur se construit et se backteste à côté.

hist_matchs   : un match par ligne (clé = fixture_id API-Football), score + statistiques
                finales une fois terminé. Alimenté par le backfill (services/historique.py).
hist_cotes    : capture PROSPECTIVE (demande explicite du 10/10/2026 : "rendre possible une
                vraie mesure future du ROI" — jamais de cote historique fabriquée ni simulée,
                uniquement ce qu'OddsPapi a réellement renvoyé au moment du run) de chaque
                candidat vu par bet_agent (et, si disponible, par moteur/) à l'instant exact de
                la prédiction. Autonome : PAS de clé étrangère vers hist_matchs (qui ne couvre
                aujourd'hui que le backfill Premier League, alors que la production voit tous
                les championnats) — toute l'identité du match est dupliquée ici pour pouvoir
                retrouver exactement la prédiction d'origine même si le match n'est jamais
                backfillé. Alimentée par app.services.capture_historique.capturer_predictions,
                appelée depuis chaque run réel (services/runs.py). resultat/juge_le restent NULL
                jusqu'à ce que app.services.capture_historique.juger_cotes_en_attente associe le
                résultat réel une fois le match terminé.
hist_predictions : journal de chaque prédiction produite (format moteur.contrat), pour
                   l'audit ("pourquoi ce pari a été choisi ?") et pour mesurer en continu
                   la calibration réelle une fois les résultats connus.
"""

from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def maintenant():
    return datetime.now(timezone.utc)


class HistMatch(Base):
    __tablename__ = "hist_matchs"

    # fixture_id API-Football : identifiant stable et déjà unique par match, pas d'auto-incrément.
    match_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    competition_id: Mapped[int | None] = mapped_column(Integer, index=True)
    competition: Mapped[str | None] = mapped_column(String(120))
    saison: Mapped[int | None] = mapped_column(Integer, index=True)
    home_id: Mapped[int] = mapped_column(Integer, index=True)
    home: Mapped[str] = mapped_column(String(120))
    away_id: Mapped[int] = mapped_column(Integer, index=True)
    away: Mapped[str] = mapped_column(String(120))
    arbitre: Mapped[str | None] = mapped_column(String(120))
    statut: Mapped[str | None] = mapped_column(String(10))  # code API-Football : NS, FT, PST...
    home_score: Mapped[int | None] = mapped_column(Integer)
    away_score: Mapped[int | None] = mapped_column(Integer)
    # {"home": {"corners":.., "yellow_cards":.., "shots":.., "shots_on_target":.., "fouls":..,
    #           "possession":.., "xg":..}, "away": {...}} — clés manquantes si non suivies par
    # API-Football pour cette ligue/ce match (jamais inventées, voir moteur/features.py).
    stats: Mapped[dict | None] = mapped_column(JSON)
    maj_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=maintenant, onupdate=maintenant)

    predictions: Mapped[list["HistPrediction"]] = relationship(back_populates="match", cascade="all, delete-orphan")

    def vers_dict(self):
        """Format attendu par moteur.features.Historique / moteur.backtest."""
        return {"match_id": self.match_id, "date": self.date, "competition_id": self.competition_id,
                "competition": self.competition, "saison": self.saison, "home_id": self.home_id,
                "home": self.home, "away_id": self.away_id, "away": self.away, "arbitre": self.arbitre,
                "home_score": self.home_score, "away_score": self.away_score, "stats": self.stats}


class HistCote(Base):
    """Une capture prospective = un (run, match, marché brut, ligne, sélection) vu par
    bet_agent lors d'un run réel. jour+fixture_id_oddspapi+marche+ligne+selection est UNIQUE :
    le même candidat revu plusieurs fois dans la même journée (le cron tourne plusieurs fois
    par jour) n'est capturé qu'une seule fois — premier vu, jamais écrasé (voir
    capture_historique.capturer_predictions, insertion ON CONFLICT DO NOTHING)."""

    __tablename__ = "hist_cotes"
    __table_args__ = (UniqueConstraint("jour", "fixture_id_oddspapi", "marche", "ligne", "selection",
                                       name="uq_hist_cote_capture_jour"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    jour: Mapped[date] = mapped_column(Date, index=True)  # date (UTC) de la capture, clé de dédoublonnage

    # Identité du match dupliquée ici (pas de FK vers hist_matchs : la production voit tous les
    # championnats, pas seulement ceux backfillés) — assez pour retrouver exactement le match.
    fixture_id_oddspapi: Mapped[str | None] = mapped_column(String(64), index=True)
    fixture_id_api_football: Mapped[int | None] = mapped_column(Integer, index=True)
    competition_id: Mapped[int | None] = mapped_column(Integer)
    competition: Mapped[str | None] = mapped_column(String(120))
    domicile: Mapped[str] = mapped_column(String(120))
    exterieur: Mapped[str] = mapped_column(String(120))
    coup_envoi: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Marché brut OddsPapi ("marché brut" demandé explicitement) + vocabulaire court bet_agent
    # (categorie) nécessaire pour réutiliser bet_agent.verifier_resultats.grader_pick_stat.
    marche: Mapped[str] = mapped_column(String(120))
    categorie: Mapped[str | None] = mapped_column(String(60))
    ligne: Mapped[float | None] = mapped_column(Float)
    selection: Mapped[str] = mapped_column(String(64))
    cote: Mapped[float] = mapped_column(Float)  # cote réellement récupérée auprès d'OddsPapi au moment du run

    proba_bet_agent_pct: Mapped[float | None] = mapped_column(Float)
    edge_bet_agent_pct: Mapped[float | None] = mapped_column(Float)
    proba_moteur_pct: Mapped[float | None] = mapped_column(Float)
    edge_moteur_pct: Mapped[float | None] = mapped_column(Float)
    modele_moteur: Mapped[str | None] = mapped_column(String(40))

    horodatage: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=maintenant, index=True)

    # Rempli plus tard par capture_historique.juger_cotes_en_attente, une fois le match terminé.
    resultat: Mapped[str | None] = mapped_column(String(20), index=True)  # gagne|perdu|push|non_verifiable
    juge_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def vers_dict(self):
        return {"id": self.id, "run_id": self.run_id, "jour": self.jour,
                "fixture_id_oddspapi": self.fixture_id_oddspapi,
                "fixture_id_api_football": self.fixture_id_api_football,
                "competition_id": self.competition_id, "competition": self.competition,
                "domicile": self.domicile, "exterieur": self.exterieur, "coup_envoi": self.coup_envoi,
                "marche": self.marche, "categorie": self.categorie, "ligne": self.ligne,
                "selection": self.selection, "cote": self.cote,
                "proba_bet_agent_pct": self.proba_bet_agent_pct, "edge_bet_agent_pct": self.edge_bet_agent_pct,
                "proba_moteur_pct": self.proba_moteur_pct, "edge_moteur_pct": self.edge_moteur_pct,
                "modele_moteur": self.modele_moteur, "horodatage": self.horodatage,
                "resultat": self.resultat, "juge_le": self.juge_le}


class HistPrediction(Base):
    __tablename__ = "hist_predictions"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("hist_matchs.match_id", ondelete="CASCADE"), index=True)
    model: Mapped[int] = mapped_column(Integer, index=True)
    model_name: Mapped[str] = mapped_column(String(40))
    marche: Mapped[str] = mapped_column(String(40), index=True)
    ligne: Mapped[float | None] = mapped_column(Float)
    selection: Mapped[str] = mapped_column(String(10))
    raw_probability: Mapped[float] = mapped_column(Float)
    probability: Mapped[float] = mapped_column(Float)
    calibrated: Mapped[bool] = mapped_column(Boolean, default=False)
    calibration_n: Mapped[int] = mapped_column(Integer, default=0)
    odds: Mapped[float | None] = mapped_column(Float)
    implied_probability: Mapped[float | None] = mapped_column(Float)
    edge: Mapped[float | None] = mapped_column(Float)
    decision: Mapped[str | None] = mapped_column(String(10))
    reasons: Mapped[list | None] = mapped_column(JSON)
    model_version: Mapped[str] = mapped_column(String(20))
    features_version: Mapped[str | None] = mapped_column(String(20))
    horodatage: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=maintenant, index=True)

    match: Mapped[HistMatch] = relationship(back_populates="predictions")
