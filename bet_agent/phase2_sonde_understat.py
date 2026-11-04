"""Phase 2 — SONDE DE LICENCE Understat (une seule passe, lecture seule, aucune collecte de données de match).
Lit robots.txt et la page d'accueil pour vérifier : accessibilité, règles pour les robots, présence de conditions
d'utilisation / mentions légales. Aucune écriture, aucune boucle, un seul appel par URL, User-Agent déclaré."""
import re
import urllib.request

UA = "analyse-football-feasibility/1.0 (single-pass licence check; contact: repo owner)"


def lire(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return getattr(e, "code", None), f"ERREUR {e}"


def main():
    for url in ("https://understat.com/robots.txt", "https://understat.com/"):
        statut, texte = lire(url)
        print(f"\n=== {url} -> {statut} ({len(texte)} car.)")
        if url.endswith("robots.txt"):
            print(texte[:2000])
            continue
        liens = sorted(set(re.findall(r'href="([^"]+)"', texte)))
        print("Liens légaux/contact :", [l for l in liens if re.search(r"term|privacy|legal|licen|about|contact|api", l, re.I)])
        print("Mentions dans la page :", [m for m in re.findall(r"[^.<>]{0,80}(?:terms|licen[cs]e|scrap|non-commercial|copyright)[^.<>]{0,80}", texte, re.I)][:10])
        print("Ligues listées :", sorted(set(re.findall(r'href="/league/([A-Za-z_]+)', texte))))


if __name__ == "__main__":
    main()
