import csv
import sys
from decimal import Decimal
from datetime import date

from app.core.database import SessionLocal
from app.models.models import FactureHistorique

CSV_PATH = sys.argv[1] if len(sys.argv) > 1 else "/tmp/factures_historiques.csv"
SOURCE = "export_factura"


def main():
    db = SessionLocal()
    try:
        with open(CSV_PATH, newline="", encoding="utf-8") as f:
            records = list(csv.DictReader(f))
        print(f"CSV : {len(records)} lignes lues depuis {CSV_PATH}")

        deleted = db.query(FactureHistorique).filter(
            FactureHistorique.source == SOURCE
        ).delete(synchronize_session=False)
        print(f"Purge idempotente : {deleted} ligne(s) source='{SOURCE}' supprimée(s)")

        objs = []
        for r in records:
            objs.append(FactureHistorique(
                numero_facture=int(r["numero_facture"]),
                date_facture=date.fromisoformat(r["date_facture"]),
                exercice=int(r["exercice"]),
                client_nom=r["client_nom"],
                adresse=(r["adresse"] or None),
                code_postal=(r["code_postal"] or None),
                ville=(r["ville"] or None),
                montant_ht=Decimal(r["montant_ht"]),
                montant_tva=Decimal(r["montant_tva"]),
                montant_ttc=Decimal(r["montant_ttc"]),
                taux_tva=Decimal("20.00"),
                source=SOURCE,
            ))
        db.bulk_save_objects(objs)
        db.commit()
        print(f"Insérées : {len(objs)} factures")

        from sqlalchemy import func as F
        n, ca = db.query(F.count(FactureHistorique.id), F.sum(FactureHistorique.montant_ht)).filter(
            FactureHistorique.source == SOURCE
        ).one()
        print(f"\nCONTRÔLE DB : {n} lignes | CA HT total = {ca}")
        print("(attendu : 8838 lignes | 16122432.21)")
        rows = db.query(
            FactureHistorique.exercice, F.count(FactureHistorique.id), F.sum(FactureHistorique.montant_ht)
        ).filter(FactureHistorique.source == SOURCE).group_by(
            FactureHistorique.exercice
        ).order_by(FactureHistorique.exercice).all()
        for ex, c, s in rows:
            print(f"  {ex} : {c:>4} factures | CA HT {s}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
