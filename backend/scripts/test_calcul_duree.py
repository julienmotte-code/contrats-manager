"""
Test unitaire — calculer_nombre_annees (famille-aware).
    docker compose exec -T -e PYTHONPATH=/app backend python /tmp/test_calcul_duree.py
"""
import sys
from datetime import date
from app.services.contrat_service import calculer_nombre_annees

ok = 0
ko = 0


def check(label, got, attendu):
    global ok, ko
    if got == attendu:
        ok += 1
        print(f"  [OK] {label} → {got}")
    else:
        ko += 1
        print(f"  [KO] {label} → got {got}, attendu {attendu}")


# AUTRE : durée réelle anniversaire
check("AUTRE 01/03/2026→28/02/2027", calculer_nombre_annees(date(2026, 3, 1), date(2027, 2, 28), "AUTRE"), 1)
check("AUTRE 04/03/2026→03/03/2030", calculer_nombre_annees(date(2026, 3, 4), date(2030, 3, 3), "AUTRE"), 4)
check("AUTRE 19/01/2024→18/01/2027", calculer_nombre_annees(date(2024, 1, 19), date(2027, 1, 18), "AUTRE"), 3)
check("AUTRE même année 01/03/2026→31/03/2026 (<1 an)", calculer_nombre_annees(date(2026, 3, 1), date(2026, 3, 31), "AUTRE"), 0)

# Autres familles : Syntec (années civiles couvertes), INCHANGÉ
check("COSOLUCE 04/03/2026→31/12/2027", calculer_nombre_annees(date(2026, 3, 4), date(2027, 12, 31), "COSOLUCE"), 2)
check("MAINTENANCE 01/01/2026→31/12/2026", calculer_nombre_annees(date(2026, 1, 1), date(2026, 12, 31), "MAINTENANCE"), 1)

# Contrôle : une AUTRE alignée calendaire 01/01→31/12 = 1 an (réel), Syntec aurait dit 1 aussi ici
check("AUTRE 01/01/2026→31/12/2026", calculer_nombre_annees(date(2026, 1, 1), date(2026, 12, 31), "AUTRE"), 1)
# Contre-preuve : la MÊME période en COSOLUCE = 1 (identique ici, mais 2 pour 01/03→28/02 ci-dessous)
check("COSOLUCE 01/03/2026→28/02/2027 (Syntec compte 2)", calculer_nombre_annees(date(2026, 3, 1), date(2027, 2, 28), "COSOLUCE"), 2)

print(f"\n===== RÉSULTAT : {ok} OK / {ko} KO =====")
sys.exit(1 if ko else 0)
