#!/usr/bin/env python3
"""
seed_charge.py — Complément charge pour tests de performance
Ajoute :
  - Suffisamment de lignes plan PLANIFIEE pour avoir 500 factures émettables
  - Suffisamment de contrats A_RENOUVELER pour avoir 600 renouvelables
Suppression : python3 seed_charge.py --purge
"""
import uuid, random, sys
from datetime import date, timedelta
import psycopg2
import psycopg2.extras

DSN = "host=db dbname=contrats user=contrats password=Contrats2024!"
TODAY = date(2026, 3, 6)

FAMILLES = ["COSOLUCE","CANTINE","DIGITECH","MAINTENANCE","ASSISTANCE_TEL","KIWI_BACKUP"]
FORMES   = ["SAS","SARL","SA","EURL","SCI","EI","ASSOCIATION","GIE"]
VILLES   = ["Paris","Lyon","Marseille","Bordeaux","Toulouse","Nantes","Lille",
            "Strasbourg","Rennes","Montpellier","Grenoble","Nice","Toulon",
            "Rouen","Reims","Dijon","Angers","Caen","Metz","Nancy"]
DESIG = {
    "COSOLUCE":       ["Maintenance logiciel Cosoluce — Licence annuelle","Support Cosoluce — Assistance utilisateurs"],
    "CANTINE":        ["Logiciel gestion cantine — Licence annuelle","Abonnement Cantine de France"],
    "DIGITECH":       ["Maintenance système Digitech","Support Digitech — Contrat annuel"],
    "MAINTENANCE":    ["Contrat de maintenance préventive et curative","Maintenance matérielle — Parc informatique"],
    "ASSISTANCE_TEL": ["Assistance téléphonique — Cityweb","Support téléphonique — Contrat annuel"],
    "KIWI_BACKUP":    ["Sauvegarde externalisée Kiwi Backup","Abonnement Kiwi Backup — Stockage cloud"],
}
MONTANTS = {
    "COSOLUCE":(800,5000),"CANTINE":(600,3000),"DIGITECH":(1200,8000),
    "MAINTENANCE":(500,4000),"ASSISTANCE_TEL":(400,2500),"KIWI_BACKUP":(300,1800),
}
PREFIXES = {"COSOLUCE":"COS","CANTINE":"CAN","DIGITECH":"DIG",
            "MAINTENANCE":"MAI","ASSISTANCE_TEL":"ASS","KIWI_BACKUP":"KIW"}

def purge(cur):
    print("Suppression données seed_charge (karlia_id LIKE '98%')...")
    cur.execute("DELETE FROM plan_facturation WHERE contrat_id IN (SELECT id FROM contrats WHERE client_karlia_id LIKE '98%')")
    cur.execute("DELETE FROM contrat_articles WHERE contrat_id IN (SELECT id FROM contrats WHERE client_karlia_id LIKE '98%')")
    cur.execute("DELETE FROM contrats WHERE client_karlia_id LIKE '98%'")
    cur.execute("DELETE FROM clients_cache WHERE karlia_id LIKE '98%'")
    print("  OK")

def get_indice(cur):
    cur.execute("SELECT id FROM indices_revision ORDER BY annee DESC, mois LIMIT 1")
    row = cur.fetchone()
    if row: return str(row["id"])
    iid = str(uuid.uuid4())
    cur.execute("INSERT INTO indices_revision (id,date_publication,annee,mois,famille,valeur,commentaire,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (iid, date(2025,8,1), 2025, "AOUT", "SYNTEC", 285.10, "Indice test charge", "seed_charge"))
    return iid

def add_client(idx):
    return {
        "id": str(uuid.uuid4()),
        "karlia_id": f"98{idx:06d}",
        "numero_client": f"CHRG{idx:05d}",
        "nom": f"Société Charge Test {idx:04d}",
        "adresse_ligne1": f"{random.randint(1,150)} rue de la Charge",
        "code_postal": f"{random.randint(10000,99999)}",
        "ville": random.choice(VILLES),
        "pays": "France",
        "email": f"contact{idx}@charge-test.fr",
        "telephone": f"0{random.randint(1,9)}{random.randint(10000000,99999999)}",
        "siret": "".join([str(random.randint(0,9)) for _ in range(14)]),
        "forme_juridique": random.choice(FORMES),
        "contact_nom": f"Contact{idx}",
        "contact_prenom": "Test",
        "contact_fonction": "Responsable informatique",
    }

def add_contrat(cur, client, indice_id, statut, date_debut, date_fin, fam, ctr_idx):
    m = float(random.randrange(*MONTANTS[fam], 50))
    cid = str(uuid.uuid4())
    num = f"{PREFIXES[fam]}-CHRG-{ctr_idx:05d}"
    prorate = date_debut.month != 1
    nbm = None; mpr = None
    if prorate:
        nbm = 12 - date_debut.month + 1 - (0.5 if date_debut.day > 15 else 0)
        mpr = round(m * nbm / 12, 2)
    nba = date_fin.year - date_debut.year + 1

    cur.execute("""INSERT INTO contrats
        (id,numero_contrat,client_karlia_id,client_numero,client_nom,
         date_debut,date_fin,nombre_annees,montant_annuel_ht,indice_reference_id,
         prorate_annee1,prorate_nb_mois,prorate_montant_ht,prorate_validated,prorate_demi_mois,
         notes_internes,famille_contrat,type_contrat,statut,date_statut_change,created_by,validated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (numero_contrat) DO NOTHING""",
        (cid, num, client["karlia_id"], client["numero_client"], client["nom"],
         date_debut, date_fin, nba, m, indice_id,
         prorate, nbm, mpr, prorate, date_debut.day > 15 if prorate else False,
         f"Contrat charge test — {fam}", fam, "CONTRAT",
         statut, TODAY if statut=="A_RENOUVELER" else date_debut,
         "seed_charge", None if statut=="BROUILLON" else date_debut))

    cur.execute("""INSERT INTO contrat_articles
        (id,contrat_id,rang,article_karlia_id,designation,reference,prix_unitaire_ht,quantite,unite,taux_tva)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (contrat_id,rang) DO NOTHING""",
        (str(uuid.uuid4()), cid, 0, f"549{random.randint(700,799)}",
         random.choice(DESIG[fam]), f"REF-{fam[:3]}-{random.randint(100,999)}",
         m, 1.0, "Forfait", 20.00))

    return cid, m, prorate, nbm, mpr, nba, date_debut

def add_plan_planifiee(cur, cid, date_debut, date_fin, m, prorate, nbm, mpr, indice_id):
    """Ajoute les lignes PLANIFIEE année courante et future."""
    num = 1
    for annee in range(date_debut.year, date_fin.year + 1):
        isp = (annee == date_debut.year and prorate)
        mp = float(mpr) if isp else float(m)
        ech = date(annee, date_debut.month, date_debut.day) if isp else date(annee, 1, 1)
        # On ne met PLANIFIEE que sur 2026 et au-delà (factures émettables)
        if ech < date(2026, 1, 1):
            fs = "EMISE"
            kid = f"KTEST{random.randint(100000,999999)}"
            kref = f"F{annee}-{random.randint(1000,9999)}"
            mhf = mp
        else:
            fs = "PLANIFIEE"
            kid = None; kref = None; mhf = None
        cur.execute("""INSERT INTO plan_facturation
            (id,contrat_id,numero_facture,annee_facturation,date_echeance,type_facture,
             montant_ht_prevu,montant_ht_facture,facture_karlia_id,facture_karlia_ref,statut)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (contrat_id,numero_facture) DO NOTHING""",
            (str(uuid.uuid4()), cid, num, annee, ech,
             "PRORATE" if isp else "ANNUELLE", mp, mhf, kid, kref, fs))
        num += 1

def main():
    purge_mode = "--purge" in sys.argv
    print("=== Seed Charge ===")
    conn = psycopg2.connect(DSN); conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        if purge_mode:
            purge(cur); conn.commit(); print("Purge OK"); return

        cur.execute("SELECT COUNT(*) as n FROM clients_cache WHERE karlia_id LIKE '98%'")
        if cur.fetchone()["n"] > 0:
            print("WARN: données charge déjà présentes — ON CONFLICT DO NOTHING actif")

        indice_id = get_indice(cur)

        # Objectifs
        cur.execute("SELECT COUNT(*) as n FROM plan_facturation WHERE statut IN ('PLANIFIEE','CALCULEE') AND contrat_id IN (SELECT id FROM contrats WHERE client_karlia_id LIKE '99%')")
        fac_existantes = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) as n FROM contrats WHERE statut='A_RENOUVELER' AND client_karlia_id LIKE '99%'")
        renouv_existants = cur.fetchone()["n"]

        fac_a_ajouter = max(0, 500 - fac_existantes)
        renouv_a_ajouter = max(0, 600 - renouv_existants)

        print(f"Factures PLANIFIEE existantes : {fac_existantes} → besoin de {fac_a_ajouter} de plus")
        print(f"Contrats A_RENOUVELER existants : {renouv_existants} → besoin de {renouv_a_ajouter} de plus")

        clients = []
        ctr_idx = 1

        # Contrats EN_COURS avec factures PLANIFIEE 2026
        # ~2 factures PLANIFIEE par contrat (année courante + 1 future si multi-an)
        nb_contrats_fac = (fac_a_ajouter // 2) + 10
        print(f"\nCréation {nb_contrats_fac} contrats EN_COURS pour factures...")
        for i in range(nb_contrats_fac):
            cl = add_client(i + 1)
            clients.append(cl)
            fam = random.choice(FAMILLES)
            dd = date(random.randint(2023,2025), random.randint(1,6), 1)
            df = date(2027, 12, 31)
            cid, m, prorate, nbm, mpr, nba, dd2 = add_contrat(cur, cl, indice_id, "EN_COURS", dd, df, fam, ctr_idx)
            add_plan_planifiee(cur, cid, dd, df, m, prorate, nbm, mpr, indice_id)
            ctr_idx += 1

        # Contrats A_RENOUVELER supplémentaires
        print(f"Création {renouv_a_ajouter} contrats A_RENOUVELER...")
        for i in range(renouv_a_ajouter):
            cl = add_client(nb_contrats_fac + i + 1)
            clients.append(cl)
            fam = random.choice(FAMILLES)
            nba = random.choice([1,2,3])
            df = date(2026, 3, random.randint(1,28))
            dd = date(df.year - nba + 1, 1, 1)
            cid, m, prorate, nbm, mpr, nba2, dd2 = add_contrat(cur, cl, indice_id, "A_RENOUVELER", dd, df, fam, ctr_idx)
            add_plan_planifiee(cur, cid, dd, df, m, prorate, nbm, mpr, indice_id)
            ctr_idx += 1

        # Insertion clients en batch
        print(f"Insertion {len(clients)} clients charge...")
        psycopg2.extras.execute_batch(cur, """INSERT INTO clients_cache
            (id,karlia_id,numero_client,nom,adresse_ligne1,code_postal,ville,pays,
             email,telephone,siret,forme_juridique,contact_nom,contact_prenom,contact_fonction,synchro_at)
            VALUES (%(id)s,%(karlia_id)s,%(numero_client)s,%(nom)s,%(adresse_ligne1)s,%(code_postal)s,%(ville)s,%(pays)s,
             %(email)s,%(telephone)s,%(siret)s,%(forme_juridique)s,%(contact_nom)s,%(contact_prenom)s,%(contact_fonction)s,NOW())
            ON CONFLICT (karlia_id) DO NOTHING""", clients, page_size=100)

        conn.commit()

        # Résumé final toutes données test confondues
        print("\n=== Résumé global (99% + 98%) ===")
        cur.execute("""SELECT COUNT(*) as n FROM plan_facturation
            WHERE statut IN ('PLANIFIEE','CALCULEE')
            AND contrat_id IN (SELECT id FROM contrats WHERE client_karlia_id LIKE '99%' OR client_karlia_id LIKE '98%')""")
        print(f"Factures émettables total     : {cur.fetchone()['n']} (objectif 500+)")
        cur.execute("""SELECT COUNT(*) as n FROM contrats
            WHERE statut='A_RENOUVELER'
            AND (client_karlia_id LIKE '99%' OR client_karlia_id LIKE '98%')""")
        print(f"Contrats A_RENOUVELER total   : {cur.fetchone()['n']} (objectif 600+)")
        print("\nOK — Pour supprimer : python3 seed_charge.py --purge")

    except Exception as e:
        conn.rollback(); import traceback; traceback.print_exc(); sys.exit(1)
    finally:
        cur.close(); conn.close()

if __name__ == "__main__":
    main()
