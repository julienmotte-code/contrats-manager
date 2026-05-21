/**
 * pdfFetch.js — Helper pour ouvrir un PDF protégé par JWT dans un nouvel onglet.
 *
 * Pourquoi : window.open(url, '_blank') n'envoie PAS le header Authorization.
 * Tous les endpoints sont gatés par require_role / require_authenticated côté backend
 * depuis le chantier 2.1, donc l'ouverture directe d'un PDF protégé renvoie 401.
 *
 * Solution : récupérer le blob via fetch (avec le Bearer token), créer une URL
 * temporaire en mémoire (URL.createObjectURL), l'ouvrir dans un nouvel onglet,
 * puis révoquer cette URL après un délai pour libérer la mémoire.
 *
 * Usage :
 *   import { openPdfWithAuth } from '../services/pdfFetch';
 *   openPdfWithAuth(`/api/commandes/${id}/pdf`);
 *
 * Le helper gère les erreurs 401/403/404 et lève une exception explicite
 * que l'appelant peut catch'er pour afficher un toast.
 */

const REVOKE_DELAY_MS = 60_000;

export async function openPdfWithAuth(url) {
    const token = localStorage.getItem('token');
    if (!token) {
        throw new Error('PDF : non authentifié (token manquant)');
    }

    let response;
    try {
        response = await fetch(url, {
            method: 'GET',
            headers: { Authorization: `Bearer ${token}` },
            // L'endpoint /pdf renvoie souvent un 307 vers Karlia : suivre la redirection.
            redirect: 'follow',
        });
    } catch (e) {
        throw new Error(`PDF : erreur réseau (${e.message})`);
    }

    if (!response.ok) {
        if (response.status === 401) {
            throw new Error('PDF : session expirée, veuillez vous reconnecter');
        }
        if (response.status === 403) {
            throw new Error('PDF : accès refusé pour votre rôle');
        }
        if (response.status === 404) {
            throw new Error('PDF : document introuvable');
        }
        throw new Error(`PDF : erreur ${response.status}`);
    }

    const blob = await response.blob();
    const blobUrl = URL.createObjectURL(blob);
    window.open(blobUrl, '_blank');
    setTimeout(() => URL.revokeObjectURL(blobUrl), REVOKE_DELAY_MS);
}
