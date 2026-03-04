"""
Service de validation métier — Autovalidation du logiciel
Niveaux : ERREUR (bloque) / WARNING (alerte) / INFO (ok)
"""
from decimal import Decimal
from typing import Dict, Optional
from sqlalchemy.orm import Session

from app.models.models import Contrat, PlanFacturation, IndiceRevision
from app.services.revision_service import get_regle_revision, get_indice, verifier_indices_disponibles


def _alerte(niveau: str, code: str, message: str, detail: Optional[str] = None) -> Dict:
    return {"niveau": niveau, "code": code, "message": message, "detail": detail}

def _ok(code: str, message: str) -> Dict:
    return {"niveau": "INFO", "code": code, "message": message, "detail": None}


def valider_contrat(db: Session, contrat: Contrat) -> Dict:
    alertes = []

    # Article principal rang 0 + id_product Karlia
    article_principal = next((a for a in contrat.articles if a.rang == 0), None)
    if not article_principal:
        alertes.append(_alerte("ERREUR", "ARTICLE_PRINCIPAL_MANQUANT",
            "Aucun article de rang 0 — la facturation Karlia sera sans montant",
            "L'article rang 0 est obligatoire (id_product requis par Karlia)"))
    elif not article_principal.article_karlia_id:
        alertes.append(_alerte("ERREUR", "ID_PRODUCT_MANQUANT",
            f"Article principal '{article_principal.designation}' sans id_product Karlia",
            "Sans id_product, Karlia enregistre la facture avec montant 0"))

    # Plan de facturation cohérent avec les dates
    nb_annees_attendu = contrat.date_fin.year - contrat.date_debut.year + 1
    nb_lignes_plan = len(contrat.plan_facturation)
    if nb_lignes_plan == 0:
        alertes.append(_alerte("ERREUR", "PLAN_VIDE",
            "Aucune ligne dans le plan de facturation",
            "Le plan doit être généré à la validation du contrat"))
    elif nb_lignes_plan != nb_annees_attendu:
        alertes.append(_alerte("WARNING", "PLAN_INCOMPLET",
            f"Plan : {nb_lignes_plan} ligne(s) pour {nb_annees_attendu} année(s) attendue(s)",
            f"Dates contrat : {contrat.date_debut} → {contrat.date_fin}"))

    # Doublons d'année dans le plan
    annees_plan = [p.annee_facturation for p in contrat.plan_facturation]
    if len(annees_plan) != len(set(annees_plan)):
        doublons = list(set(a for a in annees_plan if annees_plan.count(a) > 1))
        alertes.append(_alerte("ERREUR", "DOUBLON_ANNEE_PLAN",
            f"Doublons dans le plan pour les années : {doublons}",
            "Risque de double facturation"))

    # Facture EMISE sans karlia_id
    for p in contrat.plan_facturation:
        if p.statut == "EMISE" and not p.facture_karlia_id:
            alertes.append(_alerte("ERREUR", "EMISE_SANS_KARLIA_ID",
                f"Année {p.annee_facturation} : statut EMISE mais aucun ID Karlia enregistré",
                "Facture peut-être créée dans Karlia mais non tracée en base"))

    # Facture EMISE sans montant
    for p in contrat.plan_facturation:
        if p.statut == "EMISE" and not p.montant_revise_ht and not p.montant_ht_facture:
            alertes.append(_alerte("WARNING", "EMISE_SANS_MONTANT_REVISE",
                f"Année {p.annee_facturation} : facture émise sans montant révisé enregistré",
                "montant_revise_ht et montant_ht_facture sont tous les deux NULL"))

    # Cohérence taux de révision vs indices
    for p in contrat.plan_facturation:
        if p.statut == "EMISE" and p.taux_revision and p.indice_calcul_id:
            indice_new = db.query(IndiceRevision).filter(IndiceRevision.id == p.indice_calcul_id).first()
            if indice_new:
                annee_ref = p.annee_facturation - 2
                regle = get_regle_revision(contrat.famille_contrat or "COSOLUCE")
                mois = "AOUT" if regle == "SYNTEC_AOUT" else "OCTOBRE"
                indice_ref = get_indice(db, annee_ref, mois)
                if indice_ref and indice_new.valeur and indice_ref.valeur:
                    taux_attendu = (indice_new.valeur / indice_ref.valeur).quantize(Decimal("0.000001"))
                    taux_stocke = Decimal(str(p.taux_revision)).quantize(Decimal("0.000001"))
                    if abs(taux_attendu - taux_stocke) > Decimal("0.000010"):
                        alertes.append(_alerte("WARNING", "TAUX_REVISION_INCOHERENT",
                            f"Année {p.annee_facturation} : taux stocké {taux_stocke} ≠ taux recalculé {taux_attendu}",
                            f"Indices : {indice_ref.valeur} ({annee_ref}) → {indice_new.valeur} ({p.annee_facturation - 1})"))

    # Propagation montant_annuel_precedent entre années
    plans_tries = sorted(contrat.plan_facturation, key=lambda p: p.annee_facturation)
    for i in range(1, len(plans_tries)):
        pp = plans_tries[i - 1]
        pc = plans_tries[i]
        if pp.statut == "EMISE" and pc.statut in ("CALCULEE", "EMISE"):
            montant_emis = pp.montant_revise_ht or pp.montant_ht_prevu
            montant_ref = pc.montant_annuel_precedent
            if montant_emis and montant_ref:
                ecart = abs(Decimal(str(montant_emis)) - Decimal(str(montant_ref)))
                if ecart > Decimal("0.01"):
                    alertes.append(_alerte("WARNING", "MONTANT_PRECEDENT_INCOHERENT",
                        f"Année {pc.annee_facturation} : montant_annuel_precedent ({montant_ref}) "
                        f"≠ montant émis année précédente ({montant_emis})",
                        "La base de calcul de la révision est peut-être incorrecte"))

    sain = not any(a["niveau"] == "ERREUR" for a in alertes)
    if not alertes:
        alertes.append(_ok("CONTRAT_SAIN", "Toutes les validations sont passées"))

    return {
        "sain": sain,
        "contrat_id": str(contrat.id),
        "numero_contrat": contrat.numero_contrat,
        "client_nom": contrat.client_nom,
        "alertes": alertes,
    }


def valider_pre_calcul(db: Session, plan: PlanFacturation, nouveau_montant_manuel: Optional[Decimal] = None) -> Dict:
    alertes = []
    contrat = plan.contrat
    annee = plan.annee_facturation
    famille = contrat.famille_contrat or "COSOLUCE"
    regle = get_regle_revision(famille)

    if plan.statut == "EMISE":
        alertes.append(_alerte("ERREUR", "DEJA_EMISE",
            f"La facture {annee} est déjà émise (karlia_id: {plan.facture_karlia_id})",
            "Impossible de recalculer une facture déjà émise dans Karlia"))

    if annee == contrat.date_debut.year:
        alertes.append(_ok("PREMIERE_ANNEE", "Première année — pas de révision Syntec"))
        return {"ok": not any(a["niveau"] == "ERREUR" for a in alertes), "alertes": alertes}

    if regle in ("SYNTEC_AOUT", "SYNTEC_OCTOBRE"):
        verif = verifier_indices_disponibles(db, famille, annee)
        if not verif["ok"]:
            alertes.append(_alerte("ERREUR", "INDICES_MANQUANTS", verif["message"],
                f"Pour facturer {annee}, il faut les indices des années {annee - 2} et {annee - 1}"))
        else:
            ir = verif["indice_ref"]
            iw = verif["indice_new"]
            alertes.append(_ok("INDICES_OK", f"Indices OK : {ir.annee}={ir.valeur} → {iw.annee}={iw.valeur}"))

    if regle == "MANUELLE" and nouveau_montant_manuel is None:
        alertes.append(_alerte("ERREUR", "MONTANT_MANUEL_REQUIS",
            "Contrat Digitech : montant manuel requis",
            "Passer nouveau_montant dans le body de /calculer"))

    montant_ref = plan.montant_annuel_precedent or contrat.montant_annuel_ht
    if not montant_ref or Decimal(str(montant_ref)) <= 0:
        alertes.append(_alerte("ERREUR", "MONTANT_REFERENCE_NUL",
            f"Montant de référence nul ou absent pour l'année {annee}", None))

    return {"ok": not any(a["niveau"] == "ERREUR" for a in alertes), "alertes": alertes}


def valider_pre_emission(db: Session, plan: PlanFacturation) -> Dict:
    alertes = []
    contrat = plan.contrat

    if plan.statut == "EMISE":
        alertes.append(_alerte("ERREUR", "DEJA_EMISE",
            f"Facture {plan.annee_facturation} déjà émise (Karlia ID: {plan.facture_karlia_id})",
            "Double émission bloquée"))
    elif plan.statut == "PLANIFIEE":
        alertes.append(_alerte("ERREUR", "NON_CALCULEE",
            f"Facture {plan.annee_facturation} non calculée (statut PLANIFIEE)",
            "Lancer /calculer avant /lancer"))

    montant = plan.montant_revise_ht or plan.montant_ht_prevu
    if not montant or Decimal(str(montant)) <= 0:
        alertes.append(_alerte("ERREUR", "MONTANT_NUL",
            f"Montant nul ou absent pour l'année {plan.annee_facturation}", None))

    article_principal = next((a for a in contrat.articles if a.rang == 0), None)
    if not article_principal:
        alertes.append(_alerte("ERREUR", "ARTICLE_PRINCIPAL_MANQUANT",
            "Aucun article rang 0", "La facture Karlia nécessite au moins une ligne produit"))
    elif not article_principal.article_karlia_id:
        alertes.append(_alerte("ERREUR", "ID_PRODUCT_MANQUANT",
            f"Article '{article_principal.designation}' sans id_product Karlia",
            "Sans id_product, Karlia enregistre le montant à 0"))

    if not contrat.client_karlia_id:
        alertes.append(_alerte("ERREUR", "CLIENT_KARLIA_MANQUANT",
            "Contrat sans client_karlia_id", "Vérifier la synchronisation client"))

    if plan.taux_revision:
        taux = Decimal(str(plan.taux_revision))
        if taux < Decimal("0.5") or taux > Decimal("2.0"):
            alertes.append(_alerte("WARNING", "TAUX_REVISION_ANORMAL",
                f"Taux de révision anormal : {taux} (attendu entre 0.5 et 2.0)",
                "Vérifier les indices saisis"))

    return {"ok": not any(a["niveau"] == "ERREUR" for a in alertes), "alertes": alertes}


def valider_post_emission(plan: PlanFacturation, resultat_karlia: Dict) -> Dict:
    alertes = []

    if not resultat_karlia.get("succes"):
        alertes.append(_alerte("ERREUR", "KARLIA_ECHEC",
            f"Échec Karlia : {resultat_karlia.get('erreur', 'erreur inconnue')}", None))
        return {"ok": False, "alertes": alertes}

    karlia_id = resultat_karlia.get("karlia_doc_id")
    if not karlia_id:
        alertes.append(_alerte("ERREUR", "KARLIA_ID_ABSENT",
            "Karlia a répondu succès mais sans ID document",
            "Facture peut-être créée dans Karlia mais non traçable"))

    if not resultat_karlia.get("karlia_doc_ref"):
        alertes.append(_alerte("WARNING", "KARLIA_REF_ABSENTE",
            "Karlia n'a pas retourné de référence document", None))

    if plan.statut != "EMISE":
        alertes.append(_alerte("ERREUR", "STATUT_NON_MIS_A_JOUR",
            f"Facture créée dans Karlia (ID: {karlia_id}) mais statut en base = {plan.statut}",
            "Risque de double facturation"))

    if karlia_id and plan.facture_karlia_id != str(karlia_id):
        alertes.append(_alerte("ERREUR", "KARLIA_ID_NON_PERSISTE",
            f"ID Karlia retourné ({karlia_id}) ≠ ID stocké en base ({plan.facture_karlia_id})",
            "Le commit a peut-être échoué silencieusement"))

    ok = not any(a["niveau"] == "ERREUR" for a in alertes)
    if ok and not alertes:
        alertes.append(_ok("EMISSION_COHERENTE", f"Facture émise et tracée — Karlia ID: {karlia_id}"))

    return {"ok": ok, "alertes": alertes}


def auditer_annee_facturation(db: Session, annee: int) -> Dict:
    plans = db.query(PlanFacturation).filter(PlanFacturation.annee_facturation == annee).all()
    rapport = {"annee": annee, "total_contrats": len(plans), "erreurs": 0, "warnings": 0, "sains": 0, "contrats": []}

    for plan in plans:
        contrat = plan.contrat
        alertes = []

        if plan.statut in ("PLANIFIEE", "CALCULEE"):
            alertes.extend(valider_pre_emission(db, plan)["alertes"])

        if plan.statut == "EMISE":
            if not plan.facture_karlia_id:
                alertes.append(_alerte("ERREUR", "EMISE_SANS_KARLIA_ID",
                    "Statut EMISE mais aucun ID Karlia en base", "Vérifier dans Karlia"))
            if not plan.montant_revise_ht:
                alertes.append(_alerte("WARNING", "EMISE_SANS_MONTANT_REVISE",
                    "Facture émise sans montant_revise_ht", "Traçabilité incomplète"))

        nb_e = sum(1 for a in alertes if a["niveau"] == "ERREUR")
        nb_w = sum(1 for a in alertes if a["niveau"] == "WARNING")
        rapport["erreurs"] += nb_e
        rapport["warnings"] += nb_w
        if nb_e == 0:
            rapport["sains"] += 1

        rapport["contrats"].append({
            "plan_id": str(plan.id),
            "numero_contrat": contrat.numero_contrat,
            "client_nom": contrat.client_nom,
            "famille": contrat.famille_contrat,
            "statut": plan.statut,
            "montant_prevu": float(plan.montant_ht_prevu or 0),
            "montant_revise": float(plan.montant_revise_ht) if plan.montant_revise_ht else None,
            "karlia_id": plan.facture_karlia_id,
            "sain": nb_e == 0,
            "alertes": alertes,
        })

    return rapport
