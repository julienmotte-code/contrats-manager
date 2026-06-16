"""État de la dernière synchro clients, conservé EN MÉMOIRE (perdu au redémarrage).
Réécrit à chaque synchro. Valable en backend mono-process uniquement.
"""
import threading
from datetime import datetime

_lock = threading.Lock()
_state = {
    "siret_errors": [],       # liste de {"nom": str, "siret": str, "type": 'malformed'|'missing'}
    "derniere_synchro": None, # iso str
}


def reset_synchro():
    """À appeler au tout début de chaque synchro clients."""
    with _lock:
        _state["siret_errors"] = []
        _state["derniere_synchro"] = datetime.utcnow().isoformat()


def ajouter_siret_errone(nom, siret, type_erreur="malformed"):
    with _lock:
        _state["siret_errors"].append({
            "nom": nom or "(sans nom)",
            "siret": siret or "",
            "type": type_erreur,   # 'malformed' = present mais invalide ; 'missing' = vide/absent
        })


def get_synchro_state():
    with _lock:
        return {
            "siret_errors": list(_state["siret_errors"]),
            "derniere_synchro": _state["derniere_synchro"],
        }
