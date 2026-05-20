"""
Rattrapage one-shot des pdf_url manquants sur la table `commandes`.

Contexte : la synchro Karlia du 2026-05-20 a importé 108 commandes en rafale,
au-delà du quota Karlia (~100 req/min). Les appels `/documents/{id}` ont été
rate-limités (429), l'erreur a été avalée silencieusement par
`KarliaDevisService.get_devis_detail` (return None), et 106 commandes ont
été créées avec `pdf_url = NULL`. L'écran "Nouvelles Commandes" affiche un
PDF non cliquable pour ces commandes.

Diagnostic complet : docs/DIAGNOSTIC_PDF_COMMANDES.md.

Ce script appelle à nouveau `/documents/{karlia_document_id}` pour chaque
commande sans pdf_url, à cadence maîtrisée (~50 req/min, bien sous quota),
récupère `download_url` et met à jour la colonne `pdf_url`. Il ne touche
JAMAIS au code de sync — patch séparé après validation.

Sécurités :
- Filtre SQL `pdf_url IS NULL` ET re-check Python juste avant chaque UPDATE
  (jamais d'écrasement d'un pdf_url déjà rempli).
- Commit après chaque update (résilience si interruption mid-run).
- Retry automatique sur 429 (3 tentatives, backoff 5/15/30 s).
- Mode --dry-run : aucune écriture en base.
- Clé API lue depuis la table `parametres` (cle = 'karlia_api_key'),
  jamais depuis l'environnement.

Usage (dans le container backend) :
    PYTHONPATH=/app python3 /tmp/rattrapage.py --dry-run
    PYTHONPATH=/app python3 /tmp/rattrapage.py
"""
import argparse
import sys
import time

import httpx
from sqlalchemy import text

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.models import Commande, Parametre


SLEEP_BETWEEN_CALLS = 1.2          # ~50 req/min, bien sous quota Karlia (100)
RETRY_BACKOFFS_SEC = [5, 15, 30]   # backoff sur 429 : 3 tentatives
HTTP_TIMEOUT = 30.0


def get_karlia_key(db) -> str:
    param = db.query(Parametre).filter(Parametre.cle == "karlia_api_key").first()
    if not param or not param.valeur:
        print("[ABORT] Clé API Karlia introuvable dans la table parametres.", file=sys.stderr)
        sys.exit(2)
    return param.valeur


def fetch_detail(client: httpx.Client, base_url: str, headers: dict, karlia_doc_id: int):
    """
    Renvoie un tuple (kind, payload) :
      ("ok", json_dict)       : 200 + JSON
      ("not_found", None)     : 404
      ("rate_limited", None)  : 429 après tous les retries
      ("error", str)          : autre erreur HTTP/réseau, message en str
    """
    url = f"{base_url}/documents/{karlia_doc_id}"
    last_error = None
    for attempt in range(len(RETRY_BACKOFFS_SEC) + 1):
        try:
            r = client.get(url, headers=headers, timeout=HTTP_TIMEOUT)
            if r.status_code == 200:
                return ("ok", r.json())
            if r.status_code == 404:
                return ("not_found", None)
            if r.status_code == 429:
                if attempt < len(RETRY_BACKOFFS_SEC):
                    wait = RETRY_BACKOFFS_SEC[attempt]
                    print(f"    -> 429 reçu, retry dans {wait}s (tentative {attempt + 1}/{len(RETRY_BACKOFFS_SEC)})")
                    time.sleep(wait)
                    continue
                return ("rate_limited", None)
            last_error = f"HTTP {r.status_code}: {r.text[:200]}"
            return ("error", last_error)
        except httpx.HTTPError as e:
            last_error = f"network: {e!r}"
            if attempt < len(RETRY_BACKOFFS_SEC):
                wait = RETRY_BACKOFFS_SEC[attempt]
                print(f"    -> erreur réseau {e!r}, retry dans {wait}s")
                time.sleep(wait)
                continue
            return ("error", last_error)
    return ("error", last_error or "épuisé sans réponse")


def main():
    parser = argparse.ArgumentParser(description="Rattrapage pdf_url manquants depuis Karlia.")
    parser.add_argument("--dry-run", action="store_true", help="Ne rien écrire en base, juste afficher.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        api_key = get_karlia_key(db)
        base_url = settings.KARLIA_API_URL.rstrip("/")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        }

        commandes = (
            db.query(Commande)
            .filter(Commande.pdf_url.is_(None))
            .order_by(Commande.id)
            .all()
        )
        total = len(commandes)
        if total == 0:
            print("Aucune commande sans pdf_url. Rien à faire.")
            return 0

        mode = "DRY-RUN" if args.dry_run else "ÉCRITURE"
        print(f"=== Rattrapage pdf_url — mode {mode} ===")
        print(f"Commandes à traiter : {total}")
        print(f"Cadence : {SLEEP_BETWEEN_CALLS}s entre appels (~{int(60 / SLEEP_BETWEEN_CALLS)} req/min)")
        print(f"Durée estimée : ~{int(total * SLEEP_BETWEEN_CALLS / 60) + 1} min")
        print()

        stats = {
            "ok": 0,
            "not_found": 0,
            "no_download_url": 0,
            "rate_limited": 0,
            "error": 0,
            "skipped_already_filled": 0,
        }

        with httpx.Client() as client:
            for idx, cmd in enumerate(commandes, start=1):
                kdoc = cmd.karlia_document_id
                ref = cmd.reference_devis or "?"
                tag = f"[{idx}/{total}] id={cmd.id} kdoc={kdoc} ref={ref}"

                kind, payload = fetch_detail(client, base_url, headers, kdoc)

                if kind == "ok":
                    download_url = payload.get("download_url") if isinstance(payload, dict) else None
                    if not download_url:
                        print(f"{tag} WARN pas de download_url dans la réponse")
                        stats["no_download_url"] += 1
                    else:
                        # Re-check côté Python pour ne jamais écraser une URL existante
                        # (un autre process aurait pu la remplir entre-temps)
                        db.refresh(cmd)
                        if cmd.pdf_url:
                            print(f"{tag} SKIP pdf_url déjà rempli entre-temps")
                            stats["skipped_already_filled"] += 1
                        else:
                            nom_pdf = f"{cmd.reference_devis or 'devis'}.pdf"
                            if args.dry_run:
                                print(f"{tag} OK (dry-run, url={download_url[:80]}...)")
                            else:
                                db.execute(
                                    text(
                                        "UPDATE commandes "
                                        "SET pdf_url = :url, pdf_devis_nom = :nom "
                                        "WHERE id = :id AND pdf_url IS NULL"
                                    ),
                                    {"url": download_url, "nom": nom_pdf, "id": cmd.id},
                                )
                                db.commit()
                                print(f"{tag} OK")
                            stats["ok"] += 1
                elif kind == "not_found":
                    print(f"{tag} WARN document supprimé côté Karlia (404)")
                    stats["not_found"] += 1
                elif kind == "rate_limited":
                    print(f"{tag} ERROR 429 après retries — à rejouer plus tard")
                    stats["rate_limited"] += 1
                else:  # "error"
                    print(f"{tag} ERROR {payload}")
                    stats["error"] += 1

                if idx % 10 == 0:
                    treated = stats["ok"] + stats["not_found"] + stats["no_download_url"] + stats["rate_limited"] + stats["error"] + stats["skipped_already_filled"]
                    print(f"    --- progression : {treated}/{total} (ok={stats['ok']}, 404={stats['not_found']}, warn={stats['no_download_url']}, err={stats['error'] + stats['rate_limited']}) ---")

                time.sleep(SLEEP_BETWEEN_CALLS)

        print()
        print("=== Récap ===")
        print(f"  Total traité                 : {total}")
        print(f"  Succès (pdf_url renseigné)   : {stats['ok']}")
        print(f"  404 (document Karlia absent) : {stats['not_found']}")
        print(f"  Pas de download_url          : {stats['no_download_url']}")
        print(f"  429 après retries (à rejouer): {stats['rate_limited']}")
        print(f"  Autres erreurs               : {stats['error']}")
        print(f"  Skip (déjà rempli)           : {stats['skipped_already_filled']}")
        if args.dry_run:
            print("  Mode DRY-RUN : aucune écriture effectuée.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
