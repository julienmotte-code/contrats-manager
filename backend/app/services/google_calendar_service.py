from typing import Optional, Dict, Any

class GoogleCalendarService:
    def create_or_update_event(
        self,
        *,
        prestation_id: int,
        title: str,
        agenda_email: str,
        date_planifiee: str,
        heure_debut: Optional[str],
        heure_fin: Optional[str],
        lieu: Optional[str],
        notes: Optional[str],
        existing_event_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Squelette provisoire.
        À remplacer par l'appel réel Google Calendar API.
        """
        return {
            "success": False,
            "event_id": existing_event_id,
            "calendar_id": agenda_email,
            "status": "pending_google_integration",
            "error": "Google Calendar non encore branché"
        }

    def delete_event(
        self,
        *,
        agenda_email: str,
        event_id: str,
    ) -> Dict[str, Any]:
        """
        Squelette provisoire.
        """
        return {
            "success": False,
            "status": "pending_google_integration",
            "error": "Google Calendar non encore branché"
        }

google_calendar_service = GoogleCalendarService()
