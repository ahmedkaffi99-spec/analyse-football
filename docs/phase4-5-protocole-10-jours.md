# Phase 4.5 — Protocole comparatif de 10 jours (préparé, NON exécuté)

**Statut : non effectué.** Il exige 10 jours calendaires réels et des appels IA payants pour 4 modèles ; la mission interdit les appels payants, le pipeline, le cron, Telegram et l'écriture Supabase. Aucune donnée n'a été fabriquée.

Procédure (code : `protocole_comparatif.plan`, `empreinte_catalogue`, `controle_equite`, `couverture`) :
1. Chaque jour, figer le catalogue de matchs (empreinte enregistrée) ; les quatre modèles reçoivent exactement le même catalogue, les mêmes profils, les mêmes règles de Python, le même prompt et le même effort de raisonnement.
2. Un tirage par modèle et par jour ; un re-tirage n'est jamais additionné.
3. Coupons de suivi uniquement : aucun Telegram, aucun vrai coupon.
4. Règlement après les matchs avec la vérification existante ; seuls les coupons réglés comptent.
5. Objectif : 30 coupons réglés par modèle. Avec 3 profils par jour, 10 jours donnent au plus 30 coupons par modèle **si chaque modèle produit les 3 coupons chaque jour** : aucune marge (Claude en a produit 0/3 et Gemini 1/3 lors du seul essai). Il est donc probable qu'il faille plus de 10 jours ou plus de coupons par jour ; la couverture le dira.
6. Coût indicatif : environ 0,25 à 0,32 $ par modèle et par jour d'après le run 269, soit ~1 $ par jour et ~10 $ pour 10 jours, **à autoriser explicitement**.

Pour lancer : autorisation de (a) la migration SQL, (b) les appels payants du budget, (c) un déclenchement manuel dédié aux coupons de suivi sans envoi Telegram. Le cron de production reste en pause.
