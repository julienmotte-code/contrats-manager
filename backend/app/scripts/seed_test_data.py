#!/usr/bin/env python3
"""
seed_test_data.py — Jeu de données de test — Module Gestion Contrats
300 clients fictifs, ~410 contrats variés, plan de facturation complet.
Suppression : python3 seed_test_data.py --purge
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
            "Rouen","Reims","Saint-Étienne","Dijon","Angers","Caen","Metz",
            "Nancy","Orléans","Tours","Clermont-Ferrand","Brest","Amiens",
            "Limoges","Besançon","Perpignan","Aix-en-Provence"]
PRENOMS  = ["Jean","Marie","Pierre","Sophie","Paul","Claire","Nicolas","Isabelle",
            "François","Nathalie","Laurent","Céline","Michel","Valérie","Patrick",
            "Christine","Thierry","Sandrine","Olivier","Stéphanie"]
NOMS_FAM = ["Martin","Bernard","Dubois","Thomas","Robert","Richard","Petit",
            "Durand","Leroy","Moreau","Simon","Laurent","Lefebvre","Michel",
            "Garcia","David","Bertrand","Roux","Vincent","Fournier"]
NOMS_SOC = [
    "Acacia Conseils","Agora Solutions","Albatros Tech","Alcyone Services",
    "Aldébaran Digital","Alliance Numérique","Alpha Connect","Altaïr Systèmes",
    "Ambre Consulting","Andromède IT","Antarès Développement","Apex Réseaux",
    "Aquila Data","Arcturus Formations","Ariane Logiciels","Arkos Informatique",
    "Armor Digital","Arrow Systems","Artémis Cloud","Ascella Services",
    "Askell Consulting","Astre Numérique","Atlas Informatique","Atrium Tech",
    "Aube Digitale","Aura Solutions","Aurore Systèmes","Auxerre Networks",
    "Avalon Software","Avenir Digital","Axel Informatique","Axiome Tech",
    "Axis Consulting","Azur Connect","Azurite Solutions","Babilone Systems",
    "Balise Numérique","Boreale IT","Boussole Digital","Brume Consulting",
    "Cadre Systèmes","Caldera Tech","Callisto Services","Canopée Logiciels",
    "Cap Digital","Capella Conseil","Capricorne IT","Cascade Réseaux",
    "Cassiopée Solutions","Catena Systems","Centaure Digital","Centre Numérique",
    "Chêne Informatique","Chroma Systems","Chronos IT","Cinabre Tech",
    "Clair Numérique","Clarté Solutions","Cobalt Systèmes","Colibri Digital",
    "Comet Informatique","Compass Tech","Confluence IT","Connexion Plus",
    "Constel Solutions","Copernique Systems","Corail Digital","Coronis Tech",
    "Cosmos Informatique","Courant Numérique","Crest Systems","Cristal IT",
    "Dalton Informatique","Dauphin Digital","Decibel Systems","Delta Numérique",
    "Deneb Solutions","Déviation IT","Diamant Tech","Dione Consulting",
    "Dominance Systems","Dorsal Digital","Draco IT","Dune Numérique",
    "Dynamo Solutions","Éclat Tech","Éclair Systèmes","Éclipse Digital",
    "Elara Systems","Electron Digital","Ellipse IT","Elsinore Tech",
    "Embruns Solutions","Émergence Numérique","Enclave Systems","Epsilon Digital",
    "Equinox Tech","Eridanus Systèmes","Eskimo Solutions","Étoile Polaire IT",
    "Facette IT","Falaise Digital","Falco Systems","Fanal Numérique",
    "Faro Solutions","Faucon Tech","Firmament IT","Flambeau Systèmes",
    "Flèche Digital","Flux Numérique","Fokus Solutions","Force IT",
    "Futur IT","Gaïa Solutions","Galactique Tech","Galaxie IT",
    "Garnet Systems","Gecko Digital","Génèse Numérique","Géo Solutions",
    "Girouette IT","Glacis Digital","Globule Solutions","Gnomon Tech",
    "Gorge IT","Gracilis Systems","Grain Digital","Graphe Numérique",
    "Gravité Solutions","Grille Tech","Guide Digital","Guilde Numérique",
    "Hasard Tech","Havre IT","Hermes Digital","Horizon Systems",
    "Hydre Numérique","Hymne Solutions","Hyperbole Tech","Icare Digital",
    "Iceberg Numérique","Icône Solutions","Idéal Tech","Igloo Systems",
    "Île Digital","Image Numérique","Immersion Solutions","Impact Tech",
    "Impulsion IT","Indigo Digital","Inertie Numérique","Infini Solutions",
    "Influx Tech","Ingénium IT","Initium Systems","Innovation Digital",
    "Iris Numérique","Isola Solutions","Ivoire Tech","Jade IT",
    "Jaunet Digital","Kairos Solutions","Karma IT","Kayak Numérique",
    "Kestrel Tech","Kinesis Systems","Kite Digital","Kolibri Numérique",
    "Lacune Tech","Lagon IT","Lance Numérique","Lapis Solutions",
    "Latitude Systems","Lazurite Digital","Légume Solutions","Lentille IT",
    "Lien Digital","Ligne Solutions","Limbe Tech","Lisible Systems",
    "Logis Numérique","Lore Tech","Losange IT","Lotus Digital",
    "Lumén Solutions","Lunette Tech","Lustre IT","Maille Digital",
    "Maïs Solutions","Manège IT","Mangrove Digital","Marée IT",
    "Margelle Digital","Masse Numérique","Matrice Tech","Méandre IT",
    "Mercure Numérique","Météore Tech","Midi Systems","Miel Digital",
    "Miroir Solutions","Mobile Tech","Moelle Digital","Monolithe Numérique",
    "Moteur Tech","Moulin IT","Nuage IT","Nuance Systems",
    "Nucleus Digital","Oblik Solutions","Onde IT","Onyx Digital",
    "Opale Numérique","Optique Tech","Orbite IT","Origine Systems",
    "Oxyde Numérique","Palme Tech","Passerelle Digital","Pivot Tech",
    "Planète Digital","Pôle IT","Polygone Digital","Portail Numérique",
    "Profil Solutions","Quadrant Tech","Quartz IT","Quasar Digital",
    "Racine Numérique","Radar Solutions","Radon Tech","Rafale IT",
    "Rameau Digital","Réflexe Numérique","Relief Solutions","Réseau Tech",
    "Roche IT","Rosette Digital","Rotation Numérique","Route Solutions",
    "Rubis Tech","Safran IT","Saphir Digital","Satellite Numérique",
    "Schéma Solutions","Selva Tech","Sentier IT","Signal Digital",
    "Sillon Numérique","Sinus Solutions","Sirius Tech","Socle IT",
    "Soleil Digital","Sonde Numérique","Sorbier Solutions","Source Tech",
    "Spectre IT","Sphère Digital","Spica Numérique","Spiral Solutions",
    "Strate Tech","Structure IT","Style Digital","Symbiose Numérique",
    "Synthèse Solutions","Système Tech","Table IT","Tangente Digital",
    "Tapis Numérique","Tecton Solutions","Tige Tech","Tissu IT",
    "Toile Digital","Toit Numérique","Torrent Solutions","Touche Tech",
    "Trame IT","Transit Digital","Treillis Numérique","Trident Solutions",
    "Tronc Tech","Tropique IT","Tunnel Digital","Turbine Numérique",
    "Unité Solutions","Univers Tech","Uranie IT","Vague Digital",
    "Valeur Numérique","Vecteur Solutions","Velum Tech","Veine IT",
    "Vent Digital","Verdure Numérique","Verre Solutions","Vertex Tech",
    "Vigie IT","Vigueur Digital","Vison Numérique","Voile Solutions",
    "Volta Tech","Volume IT","Vortex Digital","Voûte Numérique",
    "Zénith Solutions","Zone Tech","Zoom IT","Zora Digital",
]

DESIG = {
    "COSOLUCE":       ["Maintenance logiciel Cosoluce — Licence annuelle","Support Cosoluce — Assistance utilisateurs","Abonnement Cosoluce Premium","Maintenance corrective et évolutive Cosoluce"],
    "CANTINE":        ["Logiciel gestion cantine — Licence annuelle","Abonnement Cantine de France","Support technique Cantine de France","Maintenance Cantine de France — Établissement scolaire"],
    "DIGITECH":       ["Maintenance système Digitech","Support Digitech — Contrat annuel","Abonnement Digitech Cloud","Licence Digitech — Gestion documentaire"],
    "MAINTENANCE":    ["Contrat de maintenance préventive et curative","Maintenance matérielle — Parc informatique","Contrat de télémaintenance","Maintenance réseau et infrastructure"],
    "ASSISTANCE_TEL": ["Assistance téléphonique — Cityweb","Support téléphonique — Contrat annuel","Hotline technique — Abonnement","Assistance utilisateurs par téléphone"],
    "KIWI_BACKUP":    ["Sauvegarde externalisée Kiwi Backup","Abonnement Kiwi Backup — Stockage cloud","Solution de sauvegarde Kiwi — Contrat annuel","Kiwi Backup PRO — Restauration garantie"],
}
MONTANTS = {
    "COSOLUCE":(800,5000),"CANTINE":(600,3000),"DIGITECH":(1200,8000),
    "MAINTENANCE":(500,4000),"ASSISTANCE_TEL":(400,2500),"KIWI_BACKUP":(300,1800),
}
PREFIXES = {"COSOLUCE":"COS","CANTINE":"CAN","DIGITECH":"DIG","MAINTENANCE":"MAI","ASSISTANCE_TEL":"ASS","KIWI_BACKUP":"KIW"}

def rdate(s,e):
    return s + timedelta(days=random.randint(0,(e-s).days))

def gen_clients(n):
    noms = (NOMS_SOC*2)[:n]
    random.shuffle(noms)
    out=[]
    for i in range(n):
        idx=i+1; v=random.choice(VILLES); pr=random.choice(PRENOMS); nm=random.choice(NOMS_FAM)
        out.append({"id":str(uuid.uuid4()),"karlia_id":f"99{idx:06d}","numero_client":f"TEST{idx:05d}",
            "nom":noms[i],"adresse_ligne1":f"{random.randint(1,150)} rue {random.choice(['de la Paix','Victor Hugo','de la République','du Commerce','Jean Jaurès','de Gaulle','Nationale'])}",
            "code_postal":f"{random.randint(10000,99999)}","ville":v,"pays":"France",
            "email":f"{pr.lower()}.{nm.lower()}@test-contrats.fr","telephone":f"0{random.randint(1,9)}{random.randint(10000000,99999999)}",
            "siret":"".join([str(random.randint(0,9)) for _ in range(14)]),
            "forme_juridique":random.choice(FORMES),"contact_nom":nm,"contact_prenom":pr,
            "contact_fonction":random.choice(["Directeur","DSI","Responsable informatique","Gérant","DAF"])})
    return out

def gen_all(clients, indice_id):
    contrats=[]; articles=[]; plans=[]; idx=1

    def add(client, statut, dd, df, fam, nba, parent=None, ttype="CONTRAT", nava=None):
        nonlocal idx
        m=float(random.randrange(*MONTANTS[fam],50)); cid=str(uuid.uuid4())
        num=f"{PREFIXES[fam]}-TEST-{idx:04d}"
        prorate=dd.month!=1
        nbm=None; mpr=None
        if prorate:
            nbm=12-dd.month+1-(0.5 if dd.day>15 else 0); mpr=round(m*nbm/12,2)
        c={"id":cid,"numero_contrat":num,"client_karlia_id":client["karlia_id"],
           "client_numero":client["numero_client"],"client_nom":client["nom"],
           "date_debut":dd,"date_fin":df,"nombre_annees":nba,"montant_annuel_ht":m,
           "indice_reference_id":indice_id,"prorate_annee1":prorate,"prorate_nb_mois":nbm,
           "prorate_montant_ht":mpr,"prorate_validated":prorate,"prorate_demi_mois":dd.day>15 if prorate else False,
           "notes_internes":f"Contrat test — {fam} — {client['ville']}","famille_contrat":fam,
           "contrat_parent_id":parent,"type_contrat":ttype,"numero_avenant":nava,
           "statut":statut,"date_statut_change":TODAY if statut=="A_RENOUVELER" else dd,
           "created_by":"seed_test_data","validated_at":None if statut=="BROUILLON" else dd}
        contrats.append(c)
        articles.append({"id":str(uuid.uuid4()),"contrat_id":cid,"rang":0,
            "article_karlia_id":f"549{random.randint(700,799)}","designation":random.choice(DESIG[fam]),
            "reference":f"REF-{fam[:3]}-{random.randint(100,999)}","prix_unitaire_ht":m,
            "quantite":1.0,"unite":"Forfait","taux_tva":20.00})
        if random.random()<0.35:
            articles.append({"id":str(uuid.uuid4()),"contrat_id":cid,"rang":1,
                "article_karlia_id":f"549{random.randint(800,899)}","designation":"Formation et accompagnement utilisateurs",
                "reference":f"REF-FORM-{random.randint(100,999)}","prix_unitaire_ht":round(m*0.1,2),
                "quantite":1.0,"unite":"Jour","taux_tva":20.00})
        if statut!="BROUILLON":
            _plan(cid,dd,df,m,mpr,prorate,statut)
        idx+=1
        return cid

    def _plan(cid,dd,df,m,mpr,prorate,statut):
        num=1
        for annee in range(dd.year,df.year+1):
            isp=(annee==dd.year and prorate)
            mp=float(mpr) if isp else float(m)
            ech=date(annee,dd.month,dd.day) if isp else date(annee,1,1)
            if statut=="TERMINE":
                fs="EMISE"; kid=f"KTEST{random.randint(100000,999999)}"; kref=f"F{annee}-{random.randint(1000,9999)}"
            elif ech<date(2025,1,1):
                fs="EMISE"; kid=f"KTEST{random.randint(100000,999999)}"; kref=f"F{annee}-{random.randint(1000,9999)}"
            elif ech.year==TODAY.year:
                r=random.random()
                if r<0.50: fs="EMISE";kid=f"KTEST{random.randint(100000,999999)}";kref=f"F{annee}-{random.randint(1000,9999)}"
                elif r<0.65: fs="CALCULEE";kid=None;kref=None
                elif r<0.85: fs="PLANIFIEE";kid=None;kref=None
                else: fs="ERREUR";kid=None;kref=None
            else:
                fs="PLANIFIEE";kid=None;kref=None
            trev=None; mrev=None
            if annee>dd.year and fs in ("CALCULEE","EMISE"):
                trev=round(random.uniform(0.02,0.06),6); mrev=round(m*(1+trev),2)
            plans.append({"id":str(uuid.uuid4()),"contrat_id":cid,"numero_facture":num,
                "annee_facturation":annee,"date_echeance":ech,"type_facture":"PRORATE" if isp else "ANNUELLE",
                "montant_ht_prevu":mp,"montant_annuel_precedent":float(m) if annee>dd.year else None,
                "taux_revision":trev,"montant_revise_ht":float(mrev) if mrev else None,
                "montant_ht_facture":float(mrev or mp) if fs=="EMISE" else None,
                "facture_karlia_id":kid,"facture_karlia_ref":kref,"statut":fs,
                "erreur_message":"Timeout API Karlia — à réémettre" if fs=="ERREUR" else None})
            num+=1

    random.shuffle(clients)

    # 200 A_RENOUVELER — date_fin mars 2026
    for cl in clients[:200]:
        fam=random.choice(FAMILLES); nba=random.choice([1,2,3])
        df=date(2026,3,random.randint(1,31) if False else 31)-timedelta(days=random.randint(0,20))
        dd=date(df.year-nba+1,1,1)
        if random.random()<0.3:
            m=random.randint(2,6)
            if date(dd.year,m,1)<df: dd=date(dd.year,m,1)
        add(cl,"A_RENOUVELER",dd,df,fam,nba)

    # 80 EN_COURS classiques
    for cl in clients[200:280]:
        fam=random.choice(FAMILLES); nba=random.choice([1,2,3,5])
        dd=rdate(date(2023,1,1),date(2025,6,30))
        df=date(dd.year+nba-1,12,31)
        if df<=TODAY: df=date(TODAY.year+1,12,31)
        add(cl,"EN_COURS",dd,df,fam,nba)

    # 20 EN_COURS multi-annuels 3-5 ans
    for cl in clients[280:300]:
        fam=random.choice(FAMILLES); nba=random.choice([3,4,5])
        dd=rdate(date(2022,1,1),date(2024,6,30))
        df=date(dd.year+nba-1,12,31)
        add(cl,"EN_COURS",dd,df,fam,nba)

    # 50 TERMINE
    for cl in random.sample(clients,50):
        fam=random.choice(FAMILLES); nba=random.choice([1,2,3])
        dd=rdate(date(2020,1,1),date(2023,12,31))
        df=date(dd.year+nba-1,12,31)
        if df>=TODAY: df=date(TODAY.year-1,12,31)
        add(cl,"TERMINE",dd,df,fam,nba)

    # 20 BROUILLON
    for cl in random.sample(clients,20):
        fam=random.choice(FAMILLES); nba=random.choice([1,2,3])
        dd=date(TODAY.year,random.randint(1,12),1)
        df=date(dd.year+nba-1,12,31)
        add(cl,"BROUILLON",dd,df,fam,nba)

    # 30 RENOUVELLEMENT liés aux A_RENOUVELER
    for cl in random.sample(clients[:200],30):
        fam=random.choice(FAMILLES); nba=random.choice([1,2,3])
        dd=date(2026,4,1); df=date(dd.year+nba-1,12,31)
        parent=next((c["id"] for c in contrats if c["client_karlia_id"]==cl["karlia_id"] and c["statut"]=="A_RENOUVELER"),None)
        add(cl,"BROUILLON",dd,df,fam,nba,parent=parent,ttype="RENOUVELLEMENT")

    # 10 AVENANTS sur EN_COURS
    en_cours=[c for c in contrats if c["statut"]=="EN_COURS"][:10]
    for parent in en_cours:
        cl=next(c for c in clients if c["karlia_id"]==parent["client_karlia_id"])
        fam=parent["famille_contrat"]
        dd=rdate(parent["date_debut"],parent["date_fin"]-timedelta(days=30))
        add(cl,"EN_COURS",dd,parent["date_fin"],fam,parent["nombre_annees"],parent=parent["id"],ttype="AVENANT",nava=1)

    print(f"  {len(contrats)} contrats, {len(articles)} articles, {len(plans)} lignes plan")
    return contrats, articles, plans

def purge(cur):
    print("Suppression des données de test (karlia_id LIKE '99%')...")
    cur.execute("DELETE FROM plan_facturation WHERE contrat_id IN (SELECT id FROM contrats WHERE client_karlia_id LIKE '99%')")
    cur.execute("DELETE FROM contrat_articles WHERE contrat_id IN (SELECT id FROM contrats WHERE client_karlia_id LIKE '99%')")
    cur.execute("DELETE FROM contrats WHERE client_karlia_id LIKE '99%'")
    cur.execute("DELETE FROM clients_cache WHERE karlia_id LIKE '99%'")
    print("  OK")

def get_or_create_indice(cur):
    cur.execute("SELECT id FROM indices_revision ORDER BY annee DESC, mois LIMIT 1")
    row=cur.fetchone()
    if row: return str(row["id"])
    iid=str(uuid.uuid4())
    cur.execute("INSERT INTO indices_revision (id,date_publication,annee,mois,famille,valeur,commentaire,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (iid,date(2025,8,1),2025,"AOUT","SYNTEC",285.10,"Indice test seed","seed_test_data"))
    print("  Indice SYNTEC 2025/AOUT créé")
    return iid

def main():
    purge_mode="--purge" in sys.argv
    print("=== Seed Test Data ===")
    conn=psycopg2.connect(DSN); conn.autocommit=False
    cur=conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        if purge_mode:
            purge(cur); conn.commit(); print("Purge OK"); return

        cur.execute("SELECT COUNT(*) as n FROM clients_cache WHERE karlia_id LIKE '99%'")
        n=cur.fetchone()["n"]
        if n>0: print(f"WARN: {n} clients test déjà présents — ON CONFLICT DO NOTHING actif")

        indice_id=get_or_create_indice(cur)
        print("Génération clients..."); clients=gen_clients(300)
        print("Génération contrats..."); contrats,articles,plans=gen_all(clients,indice_id)

        print("Insertion clients...")
        psycopg2.extras.execute_batch(cur,"""INSERT INTO clients_cache
            (id,karlia_id,numero_client,nom,adresse_ligne1,code_postal,ville,pays,email,telephone,siret,forme_juridique,contact_nom,contact_prenom,contact_fonction,synchro_at)
            VALUES (%(id)s,%(karlia_id)s,%(numero_client)s,%(nom)s,%(adresse_ligne1)s,%(code_postal)s,%(ville)s,%(pays)s,%(email)s,%(telephone)s,%(siret)s,%(forme_juridique)s,%(contact_nom)s,%(contact_prenom)s,%(contact_fonction)s,NOW())
            ON CONFLICT (karlia_id) DO NOTHING""",clients,page_size=100)

        print("Insertion contrats...")
        psycopg2.extras.execute_batch(cur,"""INSERT INTO contrats
            (id,numero_contrat,client_karlia_id,client_numero,client_nom,date_debut,date_fin,nombre_annees,montant_annuel_ht,
             indice_reference_id,prorate_annee1,prorate_nb_mois,prorate_montant_ht,prorate_validated,prorate_demi_mois,notes_internes,
             famille_contrat,contrat_parent_id,type_contrat,numero_avenant,statut,date_statut_change,created_by,validated_at)
            VALUES (%(id)s,%(numero_contrat)s,%(client_karlia_id)s,%(client_numero)s,%(client_nom)s,%(date_debut)s,%(date_fin)s,%(nombre_annees)s,%(montant_annuel_ht)s,
             %(indice_reference_id)s,%(prorate_annee1)s,%(prorate_nb_mois)s,%(prorate_montant_ht)s,%(prorate_validated)s,%(prorate_demi_mois)s,%(notes_internes)s,
             %(famille_contrat)s,%(contrat_parent_id)s,%(type_contrat)s,%(numero_avenant)s,%(statut)s,%(date_statut_change)s,%(created_by)s,%(validated_at)s)
            ON CONFLICT (numero_contrat) DO NOTHING""",contrats,page_size=100)

        print("Insertion articles...")
        psycopg2.extras.execute_batch(cur,"""INSERT INTO contrat_articles
            (id,contrat_id,rang,article_karlia_id,designation,reference,prix_unitaire_ht,quantite,unite,taux_tva)
            VALUES (%(id)s,%(contrat_id)s,%(rang)s,%(article_karlia_id)s,%(designation)s,%(reference)s,%(prix_unitaire_ht)s,%(quantite)s,%(unite)s,%(taux_tva)s)
            ON CONFLICT (contrat_id,rang) DO NOTHING""",articles,page_size=200)

        print("Insertion plan de facturation...")
        psycopg2.extras.execute_batch(cur,"""INSERT INTO plan_facturation
            (id,contrat_id,numero_facture,annee_facturation,date_echeance,type_facture,montant_ht_prevu,
             montant_annuel_precedent,taux_revision,montant_revise_ht,montant_ht_facture,
             facture_karlia_id,facture_karlia_ref,statut,erreur_message)
            VALUES (%(id)s,%(contrat_id)s,%(numero_facture)s,%(annee_facturation)s,%(date_echeance)s,%(type_facture)s,%(montant_ht_prevu)s,
             %(montant_annuel_precedent)s,%(taux_revision)s,%(montant_revise_ht)s,%(montant_ht_facture)s,
             %(facture_karlia_id)s,%(facture_karlia_ref)s,%(statut)s,%(erreur_message)s)
            ON CONFLICT (contrat_id,numero_facture) DO NOTHING""",plans,page_size=200)

        conn.commit()

        print("\n=== Résumé ===")
        cur.execute("SELECT COUNT(*) as n FROM clients_cache WHERE karlia_id LIKE '99%'"); print(f"Clients test      : {cur.fetchone()['n']}")
        cur.execute("SELECT statut,COUNT(*) as n FROM contrats WHERE client_karlia_id LIKE '99%' GROUP BY statut ORDER BY statut")
        for r in cur.fetchall(): print(f"Contrats {r['statut']:15s}: {r['n']}")
        cur.execute("SELECT type_contrat,COUNT(*) as n FROM contrats WHERE client_karlia_id LIKE '99%' GROUP BY type_contrat ORDER BY type_contrat")
        for r in cur.fetchall(): print(f"Type {r['type_contrat']:18s}: {r['n']}")
        cur.execute("SELECT statut,COUNT(*) as n FROM plan_facturation WHERE contrat_id IN (SELECT id FROM contrats WHERE client_karlia_id LIKE '99%') GROUP BY statut ORDER BY statut")
        for r in cur.fetchall(): print(f"Factures {r['statut']:13s}: {r['n']}")
        cur.execute("SELECT COUNT(*) as n FROM contrats WHERE client_karlia_id LIKE '99%' AND statut='A_RENOUVELER' AND date_fin BETWEEN '2026-03-01' AND '2026-03-31'")
        print(f"Renouvellements mars 2026 : {cur.fetchone()['n']}")
        print("\nOK — Pour supprimer : python3 seed_test_data.py --purge")
    except Exception as e:
        conn.rollback(); import traceback; traceback.print_exc(); sys.exit(1)
    finally:
        cur.close(); conn.close()

if __name__=="__main__":
    main()
