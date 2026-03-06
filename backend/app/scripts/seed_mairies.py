#!/usr/bin/env python3
"""
seed_mairies.py — Jeu de données mairies pour tests
- Vide toutes les tables (clients, contrats, factures)
- Crée 1000 mairies dans Karlia (par lots de 60/min)
- Génère contrats variés avec vrais articles Karlia
- Couvre tous les statuts et cas de figure

Usage :
  docker compose exec backend python3 -m app.scripts.seed_mairies
  docker compose exec backend python3 -m app.scripts.seed_mairies --purge-only
"""
import asyncio
import random
import sys
import uuid
import logging
from datetime import date, timedelta
from decimal import Decimal

import psycopg2
import psycopg2.extras
from dateutil.relativedelta import relativedelta

from app.core import config
from app.core.database import SessionLocal
from app.models.models import Parametre
from app.services.karlia_service import KarliaService, KarliaError

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

DSN = "host=db dbname=contrats user=contrats password=Contrats2024!"
TODAY = date(2026, 3, 6)

# ── Vrais articles Karlia ─────────────────────────────────────
ARTICLES_KARLIA = [
    {"id": "549947", "designation": "Pack Premium Cosoluce",        "prix": 2400.00, "familles": ["COSOLUCE"]},
    {"id": "549948", "designation": "Pack Optima Cosoluce",         "prix": 1200.00, "familles": ["COSOLUCE"]},
    {"id": "549949", "designation": "I-CONNECT TDT",                "prix":  800.00, "familles": ["CANTINE", "MAINTENANCE"]},
    {"id": "549950", "designation": "I-CONNECT PACK CONFORT DEMAT", "prix": 1500.00, "familles": ["CANTINE", "DIGITECH"]},
    {"id": "549951", "designation": "Tangara",                      "prix":  600.00, "familles": ["ASSISTANCE_TEL", "KIWI_BACKUP"]},
    {"id": "549952", "designation": "Tangara +",                    "prix":  900.00, "familles": ["ASSISTANCE_TEL", "KIWI_BACKUP", "MAINTENANCE"]},
    {"id": "549713", "designation": "Produit 1",                    "prix":  500.00, "familles": ["DIGITECH", "MAINTENANCE"]},
    {"id": "549714", "designation": "Service",                      "prix":  300.00, "familles": ["COSOLUCE", "CANTINE", "DIGITECH", "MAINTENANCE", "ASSISTANCE_TEL", "KIWI_BACKUP"]},
]

FAMILLES = ["COSOLUCE", "CANTINE", "DIGITECH", "MAINTENANCE", "ASSISTANCE_TEL", "KIWI_BACKUP"]

# 1000 noms de communes françaises variées
COMMUNES = [
    "Abancourt","Abbans-Dessous","Abbeville","Ablis","Ablon","Abondance","Abreschviller","Abrest",
    "Accolans","Accolay","Acheres","Achicourt","Achiet-le-Grand","Acon","Acquigny","Acy",
    "Adainville","Adamswiller","Adelange","Adissan","Agde","Agen","Ageville","Agincourt",
    "Agneaux","Agnetz","Agnin","Agny","Agon-Coutainville","Agonnay","Agoult","Agris",
    "Aguessac","Ahaxe","Ahetze","Ahun","Ahuy","Aiglemont","Aignan","Aigne",
    "Aignes","Aigonnay","Aigre","Aigrefeuille","Aigremont","Aiguebelle","Aigues-Mortes","Aigues-Vives",
    "Aiguilles","Aiguillon","Aigurande","Ailhon","Aillant-sur-Tholon","Aillas","Aillas","Aillevillers",
    "Aillon-le-Jeune","Aillon-le-Vieux","Aimargues","Aime","Ainay-le-Chateau","Aingeray","Airaines","Airon",
    "Airvault","Aisy-sur-Armancon","Aiton","Aix-en-Othe","Aix-en-Provence","Aix-les-Bains","Aizac","Aizenay",
    "Ajain","Ajat","Ajoux","Alairac","Alamans","Alando","Alata","Alba-la-Romaine",
    "Albas","Albefeuille-Lagarde","Albepierre-Bredons","Albi","Albiac","Albias","Albigny","Albine",
    "Albiosc","Albitreccia","Albussac","Alcay","Alechamps","Alençon","Alencon","Aleria",
    "Alette","Alevrac","Alexain","Alfortville","Algajola","Algans","Alger","Algolsheim",
    "Alincourt","Alix","Allain","Allaines","Allainville","Alland-Huy","Allanche","Allassac",
    "Allègre","Alleins","Allemagne","Allemans","Alles","Allevard","Allex","Allichamps",
    "Allinges","Allogny","Allonnes","Allonville","Allouagne","Alloue","Allouis","Alluyes",
    "Ally","Almenèches","Aloxe-Corton","Alpuech","Alrance","Alsting","Althen","Altiani",
    "Altillac","Altkirch","Altorf","Altviller","Alvimare","Alzonne","Amage","Amancey",
    "Amancy","Amange","Amarens","Amayé","Ambares","Ambax","Amberieux","Ambert",
    "Ambeyrac","Ambialet","Ambiegna","Ambierle","Ambillou","Ambilly","Amblainville","Amblans",
    "Ambleny","Ambleteuse","Ambleville","Ambon","Ambonnay","Ambres","Ambricourt","Ambrief",
    "Ambrières","Ambrugeat","Ambutrix","Amelie-les-Bains","Amfreville","Amifontaine","Amigny","Amillis",
    "Amions","Amou","Amphion","Amplepuis","Ampus","Amure","Ancenis","Ancerville",
    "Ancemont","Anchamps","Anchenoncourt","Ancinnes","Ancourteville","Andelot","Andelys","Andernos",
    "Andeville","Andigne","Andilly","Andlau","Andolsheim","Andon","Andornay","Andouille",
    "Andresy","Andrezieux","Anduze","Anet","Anetz","Angerville","Angevillers","Angicourt",
    "Angiens","Anglade","Anglards","Angles","Anglet","Anglure","Angoisse","Angouleme",
    "Angous","Angoville","Angrie","Anguerny","Aniane","Anisy","Anjou","Ankerville",
    "Annay","Annebault","Annelles","Annemasse","Annepont","Annequin","Annesse","Anneux",
    "Anneville","Anney","Annezin","Annoeullin","Annoire","Annonay","Annot","Annoux",
    "Annoville","Anor","Anould","Anquetierville","Ansac","Ansauville","Ansauvillers","Ansouis",
    "Anterrieux","Anteuil","Anthes","Anthon","Anthy","Antibes","Antignac","Antigny",
    "Antilly","Antist","Antogny","Antonne","Antrain","Antras","Antrezieux","Antully",
    "Anvin","Anzy-le-Duc","Aoste","Apchon","Apinac","Appilly","Appoigny","Apprieu",
    "Appy","Apt","Arabaux","Aragnouet","Aramon","Arbanats","Arberats","Arbon",
    "Arboras","Arboucave","Arbus","Arcachon","Arcais","Arcambal","Arcay","Arcenant",
    "Arces","Arcey","Archamps","Arche","Archiac","Archignac","Archingeay","Arcis",
    "Arcizac","Arcizans","Arcon","Arconcey","Arconsat","Arcouest","Arcueil","Arcy",
    "Ardenais","Ardentes","Ardes","Ardeuil","Ardillieres","Ardin","Ardoise","Ardres",
    "Arette","Arev","Arfeuilles","Arfons","Argancy","Argeles","Argelliers","Argens",
    "Argent","Argentan","Argentat","Argenteuil","Argenton","Argenvieres","Arginy","Argis",
    "Argœuves","Argueil","Arguenos","Argut","Arholz","Arifat","Arignac","Arinthod",
    "Arith","Arjuzanx","Arlay","Arles","Arlet","Arleuf","Arleux","Arlos",
    "Armaucourt","Armeau","Armbouts","Armentières","Armissan","Armix","Armonville","Arnac",
    "Arnage","Arnay-le-Duc","Arneke","Arnieres","Arnos","Aromas","Arpajon","Arpavon",
    "Arphy","Arques","Arquettes","Arracourt","Arradon","Arrancy","Arras","Arrast",
    "Arraye","Arreau","Arrens","Arricau","Arrigas","Arronnes","Arros","Arrou",
    "Ars","Arsac","Arsague","Artenay","Artigat","Artignosc","Artigue","Artigues",
    "Artins","Artonges","Artres","Artzenheim","Arudy","Arvert","Arveyres","Arvieu",
    "Arvigna","Arvillard","Arvillers","Arx","Arzacq","Arzal","Arzano","Arzon",
    "Asasp","Ascain","Ascarat","Aschbach","Ascou","Aslonnes","Asnans","Asnieres",
    "Asnois","Aspach","Asperes","Aspet","Aspin","Aspiran","Aspres","Aspremont",
    "Asprières","Assas","Assay","Assieu","Assignan","Assigny","Asson","Assou",
    "Asswiller","Astafort","Astaffort","Astaillac","Aston","Astugue","Athos","Attancourt",
    "Attenschwiller","Attichy","Attignat","Attigny","Attin","Aubagne","Aubais","Aubarède",
    "Aubas","Aubazat","Aubazines","Aube","Aubenas","Aubencheul","Auberchicourt","Aubergenville",
    "Auberive","Aubermesnil","Aubers","Auberville","Aubeterre","Aubiat","Aubiere","Aubignan",
    "Aubigne","Aubigney","Aubigny","Aubin","Aubinges","Aubord","Auboue","Aubrac",
    "Aubres","Aubrieres","Aubrives","Aubusson","Auby","Aucamville","Auch","Aucun",
    "Audaux","Aude","Audenge","Audeuve","Audierne","Audignies","Audincourt","Audincthun",
    "Audinghen","Audruicq","Audun-le-Roman","Audun-le-Tiche","Auffargis","Auffay","Auffreville","Auflance",
    "Augea","Augerolles","Augicourt","Augnax","Augne","Augny","Aulhat","Aulnay",
    "Aulnois","Aulnoye","Ault","Aumagne","Aumale","Aumont","Aumur","Aunay",
    "Auneau","Aunou","Auradou","Aurec","Aureil","Aureille","Aureilhan","Auriac",
    "Auribeau","Aurignac","Aurillac","Auriol","Auris","Auroit","Aurons","Auroux",
    "Aussac","Ausseing","Aussevielle","Aussillon","Aussois","Ausson","Aussonce","Aussurucq",
    "Autechaux","Auterive","Auteuil","Autevielle","Authezat","Authie","Authieux","Authon",
    "Authou","Autichamp","Autignac","Autigny","Autoreille","Autouillet","Autrans","Autreche",
    "Autrecourt","Autremencourt","Autreppes","Autretot","Autreville","Autrey","Autricourt","Autruche",
]

# S'assurer d'avoir 1000 communes (compléter si besoin)
while len(COMMUNES) < 1000:
    COMMUNES.append(f"Commune-{len(COMMUNES)+1}")
COMMUNES = COMMUNES[:1000]
random.shuffle(COMMUNES)


def articles_pour_famille(famille: str, nb: int = 1):
    """Retourne nb articles compatibles avec la famille."""
    compatibles = [a for a in ARTICLES_KARLIA if famille in a["familles"]]
    if not compatibles:
        compatibles = ARTICLES_KARLIA  # fallback
    return random.sample(compatibles, min(nb, len(compatibles)))


def purge(conn):
    """Vide toutes les tables dans le bon ordre."""
    cur = conn.cursor()
    logger.info("Purge des tables...")
    cur.execute("DELETE FROM documents_generes")
    cur.execute("DELETE FROM plan_facturation")
    cur.execute("DELETE FROM contrat_articles")
    cur.execute("DELETE FROM contrats")
    cur.execute("DELETE FROM clients_cache")
    conn.commit()
    logger.info("Tables vidées.")
    cur.close()


async def creer_clients_karlia(karlia: KarliaService) -> list:
    """Crée 1000 mairies dans Karlia par lots de 50 avec délai."""
    clients = []
    dernier_num = await karlia.dernier_numero_client()
    logger.info(f"Dernier numéro client Karlia : {dernier_num}")

    for i, commune in enumerate(COMMUNES):
        nom = f"MAIRIE DE {commune.upper()}"
        numero = f"MAI{str(dernier_num + i + 1).zfill(4)}"
        payload = {
            "name": nom,
            "individual": 0,
            "prospect": 0,
            "client_number": numero,
            "langId": 1,
            "main_country": "FR",
            "invoice_country": "FR",
        }
        try:
            await asyncio.sleep(1.2)  # ~50 req/min, très sûr, sous le quota de 100
            result = await karlia.creer_client(payload)
            karlia_id = str(result["id"])
            clients.append({"karlia_id": karlia_id, "numero": numero, "nom": nom})
            if (i + 1) % 50 == 0:
                logger.info(f"  {i+1}/1000 clients créés...")
        except KarliaError as e:
            logger.error(f"Erreur création {nom} : {e}")
            # On continue avec un ID fictif pour ne pas bloquer
            clients.append({"karlia_id": f"ERR{i}", "numero": numero, "nom": nom})

    logger.info(f"{len(clients)} clients créés dans Karlia")
    return clients


def inserer_clients(conn, clients: list):
    """Insère les clients dans clients_cache."""
    cur = conn.cursor()
    for c in clients:
        cur.execute("""
            INSERT INTO clients_cache (id, karlia_id, numero_client, nom, pays, created_at)
            VALUES (%s, %s, %s, %s, 'FR', now())
            ON CONFLICT (karlia_id) DO UPDATE SET numero_client = EXCLUDED.numero_client
        """, (str(uuid.uuid4()), c["karlia_id"], c["numero"], c["nom"]))
    conn.commit()
    logger.info(f"{len(clients)} clients insérés en cache local")
    cur.close()


def generer_contrats(conn, clients: list):
    """Génère des contrats variés pour chaque client."""
    cur = conn.cursor()
    nb_contrats = 0
    nb_articles = 0
    nb_plans = 0

    for i, client in enumerate(clients):
        # Chaque mairie a entre 1 et 4 contrats
        nb_contrats_client = random.choices([1, 2, 3, 4], weights=[40, 35, 15, 10])[0]

        for j in range(nb_contrats_client):
            famille = random.choice(FAMILLES)
            contrat_id = str(uuid.uuid4())

            # Statut avec répartition réaliste
            statut = random.choices(
                ["EN_COURS", "A_RENOUVELER", "TERMINE", "BROUILLON"],
                weights=[55, 20, 20, 5]
            )[0]

            # Dates selon statut
            if statut == "TERMINE":
                annee_debut = random.randint(2020, 2023)
                date_debut = date(annee_debut, random.randint(1, 12), 1)
                nb_annees = random.randint(1, 3)
                date_fin = date_debut + relativedelta(years=nb_annees) - timedelta(days=1)
            elif statut == "A_RENOUVELER":
                nb_annees = random.randint(1, 3)
                # Échéance dans les 3 prochains mois
                date_fin = TODAY + timedelta(days=random.randint(0, 90))
                date_debut = date_fin - relativedelta(years=nb_annees) + timedelta(days=1)
            elif statut == "BROUILLON":
                date_debut = TODAY + timedelta(days=random.randint(1, 30))
                nb_annees = random.randint(1, 3)
                date_fin = date_debut + relativedelta(years=nb_annees) - timedelta(days=1)
            else:  # EN_COURS
                annee_debut = random.randint(2022, 2025)
                date_debut = date(annee_debut, random.randint(1, 12), 1)
                nb_annees = random.randint(1, 5)
                date_fin = date_debut + relativedelta(years=nb_annees) - timedelta(days=1)
                if date_fin < TODAY:
                    date_fin = date(TODAY.year + random.randint(1, 3), 12, 31)
                    nb_annees = date_fin.year - date_debut.year + 1

            # Articles (1 à 3 par contrat)
            nb_art = random.choices([1, 2, 3], weights=[60, 30, 10])[0]
            articles = articles_pour_famille(famille, nb_art)
            montant_annuel = sum(
                a["prix"] * random.uniform(0.8, 1.5)
                for a in articles
            )
            montant_annuel = round(montant_annuel, 2)

            prefix = famille[:3]
            numero_contrat = f"{prefix}-{str(i+1).zfill(4)}-{j+1:02d}"

            # Prorata première année
            prorate = date_debut.day > 1 or date_debut.month > 1
            nb_mois_prorate = 12 - date_debut.month + 1 if prorate else 12
            montant_prorate = round(montant_annuel * nb_mois_prorate / 12, 2) if prorate else montant_annuel

            cur.execute("""
                INSERT INTO contrats (
                    id, numero_contrat, client_karlia_id, client_nom,
                    date_debut, date_fin, nombre_annees, montant_annuel_ht,
                    famille_contrat, type_contrat, statut, date_statut_change,
                    prorate_annee1, prorate_nb_mois, prorate_montant_ht, prorate_validated,
                    created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, 'CONTRAT', %s, %s,
                    %s, %s, %s, %s,
                    now(), now()
                )
            """, (
                contrat_id, numero_contrat, client["karlia_id"], client["nom"],
                date_debut, date_fin, nb_annees, montant_annuel,
                famille, statut, TODAY,
                prorate, nb_mois_prorate, montant_prorate, not prorate,
            ))
            nb_contrats += 1

            # Insérer les articles
            for rang, art in enumerate(articles):
                prix = round(art["prix"] * random.uniform(0.8, 1.5), 2)
                cur.execute("""
                    INSERT INTO contrat_articles (
                        id, contrat_id, rang, article_karlia_id,
                        designation, prix_unitaire_ht, quantite, taux_tva
                    ) VALUES (%s, %s, %s, %s, %s, %s, 1.0, 20.0)
                """, (
                    str(uuid.uuid4()), contrat_id, rang,
                    art["id"], art["designation"], prix
                ))
                nb_articles += 1

            # Plan de facturation pour contrats non-brouillon
            if statut != "BROUILLON":
                for annee in range(date_debut.year, date_fin.year + 1):
                    plan_id = str(uuid.uuid4())
                    num_facture = annee - date_debut.year + 1
                    date_echeance = date(annee, 1, 1)
                    montant_plan = montant_prorate if annee == date_debut.year and prorate else montant_annuel

                    # Statut plan selon statut contrat et année
                    if statut == "TERMINE":
                        plan_statut = "EMISE"
                        karlia_id_facture = f"KTEST{random.randint(100000,999999)}"
                        karlia_ref = f"F{annee}-{random.randint(1000,9999)}"
                    elif annee < TODAY.year:
                        plan_statut = "EMISE"
                        karlia_id_facture = f"KTEST{random.randint(100000,999999)}"
                        karlia_ref = f"F{annee}-{random.randint(1000,9999)}"
                    elif annee == TODAY.year:
                        plan_statut = random.choices(
                            ["PLANIFIEE", "CALCULEE"],
                            weights=[70, 30]
                        )[0]
                        karlia_id_facture = None
                        karlia_ref = None
                    else:
                        plan_statut = "PLANIFIEE"
                        karlia_id_facture = None
                        karlia_ref = None

                    cur.execute("""
                        INSERT INTO plan_facturation (
                            id, contrat_id, numero_facture, annee_facturation,
                            date_echeance, type_facture, montant_ht_prevu,
                            facture_karlia_id, facture_karlia_ref, statut,
                            created_at, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
                    """, (
                        plan_id, contrat_id, num_facture, annee,
                        date_echeance,
                        "PRORATE" if annee == date_debut.year and prorate else "ANNUELLE",
                        montant_plan,
                        karlia_id_facture, karlia_ref, plan_statut,
                    ))
                    nb_plans += 1

        if (i + 1) % 100 == 0:
            conn.commit()
            logger.info(f"  {i+1}/1000 clients traités ({nb_contrats} contrats)")

    conn.commit()
    logger.info(f"Contrats : {nb_contrats} | Articles : {nb_articles} | Plans : {nb_plans}")
    cur.close()


async def main():
    purge_only = "--purge-only" in sys.argv

    # Charger clé Karlia
    db = SessionLocal()
    p = db.query(Parametre).filter(Parametre.cle == "karlia_api_key").first()
    config.settings.KARLIA_API_KEY = p.valeur if p and p.valeur else ""
    db.close()

    if not config.settings.KARLIA_API_KEY:
        logger.error("Clé Karlia introuvable")
        return

    conn = psycopg2.connect(DSN)

    # 1. Purge
    purge(conn)

    if purge_only:
        logger.info("Purge seule effectuée.")
        conn.close()
        return

    # 2. Créer les clients dans Karlia
    logger.info("Création de 1000 mairies dans Karlia (~12 minutes)...")
    karlia = KarliaService()
    clients = await creer_clients_karlia(karlia)

    # 3. Insérer en cache local
    inserer_clients(conn, clients)

    # 4. Générer les contrats
    logger.info("Génération des contrats...")
    generer_contrats(conn, clients)

    conn.close()

    # 5. Rapport final
    db = SessionLocal()
    from sqlalchemy import text
    stats = db.execute(text("""
        SELECT
          (SELECT COUNT(*) FROM clients_cache) as clients,
          (SELECT COUNT(*) FROM contrats) as contrats,
          (SELECT COUNT(*) FROM contrats WHERE statut='EN_COURS') as en_cours,
          (SELECT COUNT(*) FROM contrats WHERE statut='A_RENOUVELER') as a_renouveler,
          (SELECT COUNT(*) FROM contrats WHERE statut='TERMINE') as termines,
          (SELECT COUNT(*) FROM contrats WHERE statut='BROUILLON') as brouillons,
          (SELECT COUNT(*) FROM plan_facturation) as plans,
          (SELECT COUNT(*) FROM plan_facturation WHERE statut='PLANIFIEE') as planifiees,
          (SELECT COUNT(*) FROM plan_facturation WHERE statut='CALCULEE') as calculees
    """)).fetchone()
    db.close()

    logger.info("=" * 50)
    logger.info(f"✅ Clients        : {stats[0]}")
    logger.info(f"✅ Contrats       : {stats[1]}")
    logger.info(f"   EN_COURS       : {stats[2]}")
    logger.info(f"   A_RENOUVELER   : {stats[3]}")
    logger.info(f"   TERMINE        : {stats[4]}")
    logger.info(f"   BROUILLON      : {stats[5]}")
    logger.info(f"✅ Plans fact.    : {stats[6]}")
    logger.info(f"   PLANIFIEE      : {stats[7]}")
    logger.info(f"   CALCULEE       : {stats[8]}")


if __name__ == "__main__":
    asyncio.run(main())
