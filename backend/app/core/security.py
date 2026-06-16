"""
Helpers RBAC pour le contrôle des rôles côté API.

Source de vérité de la matrice des droits : `app/api/utilisateurs.py:DROITS`
(elle-même alignée sur `contrats-ui-src/src/context/AuthContext.js`).

Utilisation type :

    from fastapi import Depends
    from app.core.security import require_role, require_authenticated

    @router.post("/contrats")
    def creer_contrat(
        ...,
        current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
    ):
        ...

    @router.get("/contrats")
    def lister_contrats(
        ...,
        current_user = Depends(require_authenticated),
    ):
        ...
"""
from fastapi import Depends, HTTPException, status

from app.api.auth import get_current_user
from app.models.models import Utilisateur


ROLES = ("ADMIN", "GESTIONNAIRE", "FORMATEUR", "TECHNICIEN", "DIRECTION")


def require_authenticated(
    current_user: Utilisateur = Depends(get_current_user),
) -> Utilisateur:
    """Exige simplement un utilisateur authentifié, sans contrainte de rôle."""
    return current_user


def require_role(*roles: str):
    """Factory : retourne une dépendance FastAPI qui exige un des rôles passés.

    Lève 403 si le rôle de l'utilisateur n'est pas dans la liste autorisée.
    Lève 401 (via get_current_user) si le token est absent/invalide.
    """
    roles_autorises = set(roles)
    if not roles_autorises:
        raise ValueError("require_role() doit recevoir au moins un rôle")
    for r in roles_autorises:
        if r not in ROLES:
            raise ValueError(f"Rôle inconnu : {r!r}. Valeurs acceptées : {ROLES}")

    def _check(current_user: Utilisateur = Depends(get_current_user)) -> Utilisateur:
        if current_user.role not in roles_autorises:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Accès refusé : rôle requis parmi {sorted(roles_autorises)}",
            )
        return current_user

    return _check


def check_prestation_ownership(prestation, current_user: Utilisateur) -> None:
    """Vérifie qu'un utilisateur a le droit d'agir sur une prestation.

    ADMIN et GESTIONNAIRE : accès total.
    TECHNICIEN et FORMATEUR : ownership obligatoire — la prestation doit lui être
    assignée via `formateur_id` ou `agenda_formateur_id`.

    Lève HTTPException 403 si non autorisé.
    """
    if current_user.role in ("ADMIN", "GESTIONNAIRE"):
        return

    if not current_user.formateur_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Aucun formateur_id associé à votre compte",
        )

    owns = (
        prestation.formateur_id == current_user.formateur_id
        or prestation.agenda_formateur_id == current_user.formateur_id
    )
    if not owns:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cette prestation ne vous est pas attribuée",
        )


def filter_prestations_for_user(query, current_user: Utilisateur):
    """Applique le filtre métier de visibilité des prestations selon le rôle.

    ADMIN et GESTIONNAIRE : query inchangée (visibilité totale).
    TECHNICIEN et FORMATEUR : filtre sur `formateur_id` ou `agenda_formateur_id`.
    TECHNICIEN/FORMATEUR sans `formateur_id` : query vide.
    """
    from sqlalchemy import or_
    from app.models.models import Prestation

    if current_user.role in ("ADMIN", "GESTIONNAIRE"):
        return query

    if not current_user.formateur_id:
        return query.filter(False)

    return query.filter(
        or_(
            Prestation.formateur_id == current_user.formateur_id,
            Prestation.agenda_formateur_id == current_user.formateur_id,
        )
    )
