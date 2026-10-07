"""Schéma HISTORIQUE pour le moteur d'analyse (moteur/) : séparé du schéma du pipeline
quotidien (models.py) — même base, tables distinctes (préfixe hist_), pour ne jamais risquer
le pipeline en production pendant que le moteur se construit et se backteste à côté.

hist_matchs   : un match par ligne (clé = fixture_id API-Football), score + statistiques
                finales une fois terminé. Alimenté par le backfill (services/historique.py).
hist_cotes    : relevés de cotes HORODATÉS (plusieurs lignes par match possibles, une par
                passage de collecte) — contrairement à la table cotes existante, jamais
                écrasée : c'est la mémoire des cotes réellement vues avant chaque match.
hist_predictions : journal de chaque prédiction produite (format moteur.contrat), pour
                   l'audit ("pourquoi ce pari a été choisi ?") et pour mesurer en continu
                   la calibration réelle une fois les résultats connus.
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
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

    cotes: Mapped[list["HistCote"]] = relationship(back_populates="match", cascade="all, delete-orphan")
    predictions: Mapped[list["HistPrediction"]] = relationship(back_populates="match", cascade="all, delete-orphan")

    def vers_dict(self):
        """Format attendu par moteur.features.Historique / moteur.backtest."""
        return {"match_id": self.match_id, "date": self.date, "competition_id": self.competition_id,
                "competition": self.competition, "saison": self.saison, "home_id": self.home_id,
                "home": self.home, "away_id": self.away_id, "away": self.away, "arbitre": self.arbitre,
                "home_score": self.home_score, "away_score": self.away_score, "stats": self.stats}


class HistCote(Base):
    __tablename__ = "hist_cotes"
    __table_args__ = (UniqueConstraint("match_id", "marche", "ligne", "selection", "bookmaker", "horodatage",
                                       name="uq_hist_cote_releve"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("hist_matchs.match_id", ondelete="CASCADE"), index=True)
    marche: Mapped[str] = mapped_column(String(40))  # vocabulaire moteur.modeles.marches (resultat, buts_total...)
    ligne: Mapped[float | None] = mapped_column(Float)
    selection: Mapped[str] = mapped_column(String(10))
    cote: Mapped[float] = mapped_column(Float)
    bookmaker: Mapped[str | None] = mapped_column(String(40))
    horodatage: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    match: Mapped[HistMatch] = relationship(back_populates="cotes")

    def vers_releve(self):
        return {"marche": self.marche, "ligne": self.ligne, "selection": self.selection,
                "cote": self.cote, "horodatage": self.horodatage}


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
