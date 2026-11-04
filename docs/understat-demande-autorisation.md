# Brouillon de demande d'autorisation à Understat (NON ENVOYÉ — à valider et envoyer par l'utilisateur)

Objet : Demande de confirmation écrite — conditions d'utilisation et droits sur les données Understat

Bonjour,

Je développe un projet personnel d'analyse statistique du football (modèles de probabilités, évaluation de la qualité des
prédictions, backtests). J'aimerais utiliser les données publiées sur understat.com (xG, xGA, tirs, statistiques d'équipes et de
joueurs, 5 championnats européens, saisons passées et en cours) et je souhaite le faire dans le respect de vos conditions.

Pourriez-vous me confirmer par écrit :
1. Si l'utilisation des données est autorisée pour un usage **personnel / de recherche non commercial**, et sous quelles conditions
   (attribution, fréquence de requêtes, volume) ;
2. Si une **collecte automatisée** (HTML/JSON de vos pages) est tolérée, avec quelle limite de débit ;
3. Si une **utilisation commerciale** (par exemple l'aide à la décision liée à des paris sportifs) est possible, et à quelles conditions ;
4. S'il existe une **API officielle**, une licence ou des conditions d'utilisation publiées auxquelles je peux me référer ;
5. Si le stockage des données dans une base privée avec mention de la source est acceptable.

Je m'engage à citer Understat comme source, à ne pas redistribuer les données et à respecter toute limite que vous indiquerez.

Cordialement,
[Nom]

---
Mode d'emploi : tant que la réponse écrite n'est pas reçue et validée, rien n'est collecté (verrou `UNDERSTAT_AUTORISATION_ECRITE`
dans l'outil Termux et registre `sources_donnees` côté base, statut « inconnue / non autorisée »). À réception, enregistrer la
référence via `app.services.sources.autoriser(db, 'understat', '<référence de l'e-mail>')`.
