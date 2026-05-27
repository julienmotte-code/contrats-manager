"""
Diagnostic / nettoyage des prestations parasites rattachées à des lignes
d'intitulé Karlia.

Deux critères :
  STRICT     : commande_lignes.section_karlia = 1
               → garanti, c'est la sémantique officielle.
  HEURISTIQUE : commande_lignes.section_karlia IS NULL ET la ligne ressemble
               à un intitulé (commandes historiques pré-migration intitulés,
               cf. D26-0547, D26-0472, D26-0498). Les signes utilisés :
                 - karlia_product_id IS NULL / '' / '0'
                 - prix_unitaire_ht IS NULL ou = 0
                 - id_product_category IS NULL
                 - designation matche un motif d'intitulé connu
                   (TOTAL …, Gamme COLORIS …, "Prestations de …" en tête de
                   bloc, "ABONNEMENT ANNUEL …", etc.)

Pour chaque prestation détectée, séparation en :
  GROUPE SÛR     : statut = 'a_planifier' ET aucune date posée
                   (date_planifiee NULL ET date_prevue NULL) ET pas
                   d'événement agenda (google_event_id NULL,
                   google_calendar_id NULL).
                   → suppression sans risque.
  GROUPE À RISQUE : tout le reste (statut planifiee/realisee, ou date,
                    ou agenda). NE PAS supprimer automatiquement.

Modes :
  BACKFILL_MODE=dry-run (défaut)   → liste les deux groupes, n'écrit rien.
  BACKFILL_MODE=apply-strict       → supprime SEULEMENT le GROUPE SÛR du
                                     critère STRICT (section_karlia=1).
  BACKFILL_MODE=apply-heuristic    → supprime SEULEMENT le GROUPE SÛR du
                                     critère HEURISTIQUE. Réservé : nécessite
                                     un OK explicite après revue du dry-run.

Usage :
  docker compose cp /tmp/clean_prestations_intitule.py \
                    backend:/tmp/clean_prestations_intitule.py
  docker compose exec -T -e PYTHONPATH=/app backend \
                    python3 /tmp/clean_prestations_intitule.py
  # puis (après validation user) :
  docker compose exec -T -e PYTHONPATH=/app -e BACKFILL_MODE=apply-strict \
                    backend python3 /tmp/clean_prestations_intitule.py
"""
import os
import re
import sys
from typing import List

from sqlalchemy import or_, and_
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.models import Commande, CommandeLigne, Prestation


MODE = os.environ.get("BACKFILL_MODE", "dry-run").lower()
VALID_MODES = ("dry-run", "apply-strict", "apply-heuristic")
if MODE not in VALID_MODES:
    print(f"ERREUR : BACKFILL_MODE='{MODE}' invalide (valides : {VALID_MODES})")
    sys.exit(2)


# Motifs de désignation d'intitulé Karlia rencontrés (cf. diag section_universel).
# On reste conservateur — les motifs ci-dessous correspondent à des intitulés
# manifestes ; tout faux positif ne supprimera RIEN tant qu'on est en mode
# heuristique (les suppressions heuristiques exigent un OK explicite + le mode
# apply-heuristic, et n'attaquent que les prestations SÛRES).
PATTERNS_INTITULE = [
    re.compile(r"^TOTAL\s", re.IGNORECASE),
    re.compile(r"^Gamme\s+COLORIS", re.IGNORECASE),
    re.compile(r"^Prestations\s+(de|et)\s", re.IGNORECASE),
    re.compile(r"^ABONNEMENT\s+ANNUEL\b", re.IGNORECASE),
    re.compile(r"^Logiciel\s+", re.IGNORECASE),     # ex "Logiciel Cantine de France"
    re.compile(r"^PRESTATIONS\s+ET\s+FORMATIONS", re.IGNORECASE),
]


def est_intitule_heuristique(ligne: CommandeLigne) -> bool:
    """Retourne True si la ligne (section_karlia NULL) ressemble à un intitulé."""
    if ligne.section_karlia == 1:
        # déjà couvert par le critère STRICT
        return False
    designation = (ligne.designation or "").strip()
    # Trois signaux faibles : karlia_product_id vide, prix unitaire 0,
    # absence de catégorie. À eux seuls non concluants ; on combine avec
    # un match designation.
    pid = (ligne.karlia_product_id or "").strip()
    pid_vide = pid in ("", "0")
    prix_zero = (ligne.prix_unitaire_ht is None) or (float(ligne.prix_unitaire_ht or 0) == 0)
    cat_vide = ligne.id_product_category is None
    designation_match = any(p.search(designation) for p in PATTERNS_INTITULE)
    # Critère final : designation match + au moins un signe faible.
    # Réduit drastiquement les faux positifs : un "Logiciel Cantine de France"
    # qui serait une vraie prestation (rare) aurait normalement un prix > 0
    # ET un id_product_category, donc ne passerait pas le filtre.
    return designation_match and (pid_vide or prix_zero or cat_vide)


def prestation_sure(p: Prestation) -> bool:
    """Une prestation est SÛRE à supprimer si rien de concret n'y est rattaché."""
    return (
        p.statut == "a_planifier"
        and p.date_planifiee is None
        and p.date_prevue is None
        and p.google_event_id in (None, "")
        and (getattr(p, "google_calendar_id", None) in (None, ""))
    )


def afficher_groupe(titre: str, items: List[dict]) -> None:
    print()
    print("─" * 78)
    print(titre)
    print("─" * 78)
    if not items:
        print("  (vide)")
        return
    print(
        f"  {'prest_id':>9}  {'cmd_ref':<12}  {'statut':<11}  "
        f"{'formateur':>9}  {'date':<10}  {'agenda':<6}  designation"
    )
    for it in items:
        agenda = "OUI" if it["agenda"] else ""
        date_str = str(it["date_planifiee"] or it["date_prevue"] or "")
        print(
            f"  {it['prest_id']:>9}  {it['cmd_ref']:<12}  {it['statut']:<11}  "
            f"{str(it['formateur_id'] or ''):>9}  {date_str:<10}  {agenda:<6}  "
            f"{it['designation'][:60]}"
        )


def main():
    db: Session = SessionLocal()
    try:
        print("=" * 78)
        print(f"clean_prestations_intitule — mode = {MODE}")
        print("=" * 78)

        # ── CRITÈRE STRICT : section_karlia = 1 ──────────────────────────
        rows_strict = (
            db.query(Prestation, CommandeLigne, Commande)
              .join(CommandeLigne, CommandeLigne.id == Prestation.commande_ligne_id)
              .join(Commande, Commande.id == Prestation.commande_id)
              .filter(CommandeLigne.section_karlia == 1)
              .order_by(Prestation.commande_id, Prestation.id)
              .all()
        )
        strict_sur, strict_risque = [], []
        for p, cl, c in rows_strict:
            item = {
                "prest_id": p.id,
                "cmd_ref": c.reference_devis or f"id={c.id}",
                "statut": p.statut,
                "formateur_id": p.formateur_id,
                "date_planifiee": p.date_planifiee,
                "date_prevue": p.date_prevue,
                "agenda": bool(p.google_event_id) or bool(getattr(p, "google_calendar_id", None)),
                "designation": cl.designation or "",
            }
            if prestation_sure(p):
                strict_sur.append(item)
            else:
                strict_risque.append(item)

        print(f"\n[STRICT — section_karlia = 1]")
        print(f"  total : {len(rows_strict)}  "
              f"(SÛR : {len(strict_sur)}, À RISQUE : {len(strict_risque)})")
        afficher_groupe("STRICT — GROUPE SÛR (a_planifier vierge)", strict_sur)
        afficher_groupe("STRICT — GROUPE À RISQUE (planifiee / date / agenda)", strict_risque)

        # ── CRITÈRE HEURISTIQUE : section_karlia NULL + signe d'intitulé ──
        rows_null = (
            db.query(Prestation, CommandeLigne, Commande)
              .join(CommandeLigne, CommandeLigne.id == Prestation.commande_ligne_id)
              .join(Commande, Commande.id == Prestation.commande_id)
              .filter(CommandeLigne.section_karlia.is_(None))
              .order_by(Prestation.commande_id, Prestation.id)
              .all()
        )
        heur_sur, heur_risque = [], []
        for p, cl, c in rows_null:
            if not est_intitule_heuristique(cl):
                continue
            item = {
                "prest_id": p.id,
                "cmd_ref": c.reference_devis or f"id={c.id}",
                "statut": p.statut,
                "formateur_id": p.formateur_id,
                "date_planifiee": p.date_planifiee,
                "date_prevue": p.date_prevue,
                "agenda": bool(p.google_event_id) or bool(getattr(p, "google_calendar_id", None)),
                "designation": cl.designation or "",
            }
            if prestation_sure(p):
                heur_sur.append(item)
            else:
                heur_risque.append(item)

        print()
        print("=" * 78)
        print(f"\n[HEURISTIQUE — section_karlia NULL + match motif d'intitulé]")
        print(f"  total : {len(heur_sur) + len(heur_risque)}  "
              f"(SÛR : {len(heur_sur)}, À RISQUE : {len(heur_risque)})")
        afficher_groupe("HEURISTIQUE — GROUPE SÛR (a_planifier vierge)", heur_sur)
        afficher_groupe("HEURISTIQUE — GROUPE À RISQUE (planifiee / date / agenda)", heur_risque)

        # ── APPLY ─────────────────────────────────────────────────────────
        if MODE == "dry-run":
            print()
            print("=" * 78)
            print(">>> DRY-RUN : aucune suppression effectuée.")
            print("    Pour appliquer le critère STRICT (sûr uniquement) :")
            print("      BACKFILL_MODE=apply-strict")
            print("    Pour appliquer le critère HEURISTIQUE (sûr uniquement) :")
            print("      BACKFILL_MODE=apply-heuristic  (revue manuelle conseillée)")
            print("=" * 78)
            return

        cible = strict_sur if MODE == "apply-strict" else heur_sur
        cible_label = "STRICT" if MODE == "apply-strict" else "HEURISTIQUE"
        if not cible:
            print(f"\n>>> {MODE} : aucune prestation à supprimer ({cible_label} SÛR vide).")
            return

        ids = [it["prest_id"] for it in cible]
        commandes_touchees = sorted({it["cmd_ref"] for it in cible})
        print()
        print("=" * 78)
        print(f"APPLY {cible_label} — suppression de {len(ids)} prestation(s) :")
        print(f"  ids = {ids}")
        print(f"  commandes touchées : {commandes_touchees}")

        try:
            db.query(Prestation).filter(Prestation.id.in_(ids)).delete(synchronize_session=False)
            # Recalcul de commande.formateur_id sur les commandes touchées.
            cmd_ids = (
                db.query(Commande.id)
                  .filter(Commande.reference_devis.in_(commandes_touchees))
                  .all()
            )
            for (cid,) in cmd_ids:
                cmd = db.query(Commande).filter(Commande.id == cid).first()
                if not cmd:
                    continue
                # Cohérence avec POST /affecter-formateurs : 1 formateur distinct
                # sur les prestations actives → ce formateur ; 0 ou ≥2 → NULL.
                formateurs = {
                    pr.formateur_id
                    for pr in cmd.prestations
                    if pr.formateur_id is not None
                    and pr.statut in ("a_planifier", "planifiee")
                }
                cmd.formateur_id = next(iter(formateurs)) if len(formateurs) == 1 else None
            db.commit()
            print(f">>> Suppression committée : {len(ids)} prestation(s).")
            print(f">>> commande.formateur_id recalculé sur {len(cmd_ids)} commande(s).")
        except Exception as e:
            db.rollback()
            print(f"ERREUR pendant la suppression : {e!r}")
            raise

    finally:
        db.close()


if __name__ == "__main__":
    main()
