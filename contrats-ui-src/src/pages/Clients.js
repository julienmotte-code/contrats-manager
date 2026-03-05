import { useState, useCallback, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../services/api';
import { format } from 'date-fns';
import { fr } from 'date-fns/locale';

const formatDate = (d) => {
  if (!d) return '—';
  try { return format(new Date(d + 'T12:00:00'), 'd MMM yyyy', { locale: fr }); }
  catch { return d; }
};

const formatMontant = (m) =>
  m != null ? new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR' }).format(m) : '—';

const FAMILLE_LABELS = {
  COSOLUCE: 'Cosoluce', CANTINE: 'Cantine de France', DIGITECH: 'Digitech',
  MAINTENANCE: 'Maintenance', ASSISTANCE_TEL: 'Assistance Tél.', KIWI_BACKUP: 'Kiwi Backup',
};

const STATUT_COLORS = {
  ACTIF: 'bg-green-100 text-green-800', EN_COURS: 'bg-blue-100 text-blue-800',
  VALIDE: 'bg-green-100 text-green-800', A_RENOUVELER: 'bg-yellow-100 text-yellow-800',
  TERMINE: 'bg-gray-100 text-gray-600', RESILIE: 'bg-red-100 text-red-700',
  EXPIRE: 'bg-orange-100 text-orange-700',
};

function StatutBadge({ statut }) {
  const cls = STATUT_COLORS[statut] || 'bg-gray-100 text-gray-600';
  return <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${cls}`}>{statut?.replace(/_/g, ' ')}</span>;
}

function LigneContrat({ contrat, onClick }) {
  return (
    <tr className="hover:bg-blue-50 cursor-pointer transition-colors" onClick={() => onClick(contrat.id)}>
      <td className="px-4 py-3 text-sm font-mono font-medium text-blue-700">{contrat.numero_contrat}</td>
      <td className="px-4 py-3 text-sm text-gray-700">{FAMILLE_LABELS[contrat.famille_contrat] || contrat.famille_contrat}</td>
      <td className="px-4 py-3 text-sm text-gray-500">{formatDate(contrat.date_debut)} → {formatDate(contrat.date_fin)}</td>
      <td className="px-4 py-3 text-sm text-right font-medium text-gray-800">{formatMontant(contrat.montant_annuel_ht)} <span className="text-xs font-normal text-gray-400">/an</span></td>
      <td className="px-4 py-3 text-sm text-center"><StatutBadge statut={contrat.statut} /></td>
    </tr>
  );
}

function FicheClient({ karlia_id, onClose }) {
  const navigate = useNavigate();
  const [fiche, setFiche] = useState(null);
  const [loading, setLoading] = useState(true);
  const [onglet, setOnglet] = useState('actifs');
  const [erreur, setErreur] = useState(null);

  useEffect(() => {
    setLoading(true); setErreur(null);
    api.get(`/api/clients/${karlia_id}/fiche`)
      .then(r => setFiche(r.data))
      .catch(e => setErreur(e.response?.data?.detail || 'Erreur lors du chargement'))
      .finally(() => setLoading(false));
  }, [karlia_id]);

  const handleContratClick = (id) => { onClose(); navigate(`/contrats/${id}`); };

  if (loading) return (
    <div className="fixed inset-0 bg-black bg-opacity-40 z-50 flex items-center justify-center">
      <div className="bg-white rounded-xl shadow-2xl p-10 flex flex-col items-center gap-3">
        <div className="w-8 h-8 border-4 border-blue-600 border-t-transparent rounded-full animate-spin" />
        <p className="text-sm text-gray-500">Chargement de la fiche…</p>
      </div>
    </div>
  );

  if (erreur) return (
    <div className="fixed inset-0 bg-black bg-opacity-40 z-50 flex items-center justify-center">
      <div className="bg-white rounded-xl shadow-2xl p-8 max-w-sm w-full mx-4 text-center">
        <p className="text-red-600 font-medium mb-4">{erreur}</p>
        <button onClick={onClose} className="px-4 py-2 border rounded-lg text-sm">Fermer</button>
      </div>
    </div>
  );

  const { client, contrats_actifs, contrats_termines, stats } = fiche;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-40 z-50 flex items-start justify-center overflow-y-auto py-8 px-4" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-4xl">

        <div className="bg-gradient-to-r from-blue-700 to-blue-600 rounded-t-xl px-6 py-5 flex items-start justify-between">
          <div>
            <p className="text-blue-100 text-xs font-medium uppercase tracking-wide">Fiche client</p>
            <h2 className="text-white text-xl font-bold mt-0.5">{client.nom}</h2>
            <div className="flex items-center gap-3 mt-2">
              <span className="text-blue-100 text-sm font-mono bg-blue-800 bg-opacity-40 px-2 py-0.5 rounded">N° {client.numero_client}</span>
              {client.forme_juridique && <span className="text-blue-200 text-sm">{client.forme_juridique}</span>}
            </div>
          </div>
          <button onClick={onClose} className="text-white hover:text-blue-200 transition-colors p-1">
            <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
          </button>
        </div>

        <div className="grid grid-cols-3 divide-x border-b">
          <div className="px-6 py-4 text-center">
            <p className="text-2xl font-bold text-blue-700">{stats.nb_contrats_actifs}</p>
            <p className="text-xs text-gray-500 mt-0.5">Contrats actifs</p>
          </div>
          <div className="px-6 py-4 text-center">
            <p className="text-2xl font-bold text-gray-700">{stats.nb_contrats_termines}</p>
            <p className="text-xs text-gray-500 mt-0.5">Contrats terminés</p>
          </div>
          <div className="px-6 py-4 text-center">
            <p className="text-2xl font-bold text-green-700">{formatMontant(stats.montant_annuel_total)}</p>
            <p className="text-xs text-gray-500 mt-0.5">CA annuel actif</p>
          </div>
        </div>

        <div className="px-6 py-5 border-b">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">Coordonnées</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-3">
            <div className="flex gap-3">
              <svg className="w-4 h-4 text-gray-400 mt-0.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" /></svg>
              <div className="text-sm text-gray-700">
                {client.adresse_ligne1 && <div>{client.adresse_ligne1}</div>}
                {client.adresse_ligne2 && <div>{client.adresse_ligne2}</div>}
                {(client.code_postal || client.ville) && <div>{[client.code_postal, client.ville].filter(Boolean).join(' ')}</div>}
                {!client.adresse_ligne1 && !client.ville && <span className="text-gray-400 italic">Non renseignée</span>}
              </div>
            </div>
            <div className="flex gap-3 items-start">
              <svg className="w-4 h-4 text-gray-400 mt-0.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" /></svg>
              <div className="text-sm">{client.email ? <a href={`mailto:${client.email}`} className="text-blue-600 hover:underline">{client.email}</a> : <span className="text-gray-400 italic">Non renseigné</span>}</div>
            </div>
            <div className="flex gap-3 items-center">
              <svg className="w-4 h-4 text-gray-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z" /></svg>
              <span className="text-sm text-gray-700">{client.telephone || client.mobile ? [client.telephone, client.mobile].filter(Boolean).join(' / ') : <span className="text-gray-400 italic">Non renseigné</span>}</span>
            </div>
            <div className="flex gap-3 items-center">
              <svg className="w-4 h-4 text-gray-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>
              <span className="text-sm text-gray-700 font-mono">{client.siret ? `SIRET : ${client.siret}` : <span className="text-gray-400 italic font-sans">SIRET non renseigné</span>}{client.tva_intracom && <span className="ml-3 text-gray-500 font-sans">TVA : {client.tva_intracom}</span>}</span>
            </div>
            {(client.contact_nom || client.contact_prenom) && (
              <div className="flex gap-3 items-center md:col-span-2">
                <svg className="w-4 h-4 text-gray-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" /></svg>
                <span className="text-sm text-gray-700">Contact : <span className="font-medium">{[client.contact_prenom, client.contact_nom].filter(Boolean).join(' ')}</span>{client.contact_fonction && <span className="text-gray-500"> — {client.contact_fonction}</span>}</span>
              </div>
            )}
          </div>
          {client.notes && (
            <div className="mt-4 bg-yellow-50 border border-yellow-200 rounded-lg px-4 py-3">
              <p className="text-xs font-semibold text-yellow-700 uppercase tracking-wide mb-1">Notes</p>
              <p className="text-sm text-yellow-900 whitespace-pre-line">{client.notes}</p>
            </div>
          )}
        </div>

        <div>
          <div className="border-b flex">
            {[['actifs', 'Contrats actifs', stats.nb_contrats_actifs], ['termines', 'Historique', stats.nb_contrats_termines]].map(([id, label, count]) => (
              <button key={id} className={`px-6 py-3 text-sm font-medium border-b-2 transition-colors ${onglet === id ? 'border-blue-600 text-blue-700' : 'border-transparent text-gray-500 hover:text-gray-700'}`} onClick={() => setOnglet(id)}>
                {label} <span className={`ml-2 px-1.5 py-0.5 rounded-full text-xs ${onglet === id ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-500'}`}>{count}</span>
              </button>
            ))}
          </div>
          <div className="overflow-x-auto">
            {(() => {
              const liste = onglet === 'actifs' ? contrats_actifs : contrats_termines;
              if (liste.length === 0) return <p className="text-center text-gray-400 py-10 text-sm italic">Aucun contrat dans cette catégorie</p>;
              return (
                <table className="w-full text-left">
                  <thead><tr className="border-b bg-gray-50">
                    {['N° contrat','Famille','Période','Montant/an','Statut'].map(h => (
                      <th key={h} className={`px-4 py-2 text-xs font-semibold text-gray-500 uppercase tracking-wide${h === 'Montant/an' ? ' text-right' : h === 'Statut' ? ' text-center' : ''}`}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody className="divide-y divide-gray-100">
                    {liste.map(c => <LigneContrat key={c.id} contrat={c} onClick={handleContratClick} />)}
                  </tbody>
                  {onglet === 'actifs' && (
                    <tfoot><tr className="border-t-2 border-gray-200 bg-gray-50">
                      <td colSpan={3} className="px-4 py-3 text-sm font-semibold text-gray-600">Total CA annuel actif</td>
                      <td className="px-4 py-3 text-sm font-bold text-green-700 text-right">{formatMontant(stats.montant_annuel_total)}</td>
                      <td />
                    </tr></tfoot>
                  )}
                </table>
              );
            })()}
          </div>
        </div>

        <div className="border-t px-6 py-4 flex justify-between items-center bg-gray-50 rounded-b-xl">
          <p className="text-xs text-gray-400">Synchronisé le {client.synchro_at ? formatDate(client.synchro_at.split('T')[0]) : '—'}</p>
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800 border border-gray-300 rounded-lg hover:bg-gray-100 transition-colors">Fermer</button>
        </div>

      </div>
    </div>
  );
}

export default function Clients() {
  const [recherche, setRecherche] = useState('');
  const [resultats, setResultats] = useState([]);
  const [loading, setLoading] = useState(false);
  const [erreur, setErreur] = useState(null);
  const [ficheKarliaId, setFicheKarliaId] = useState(null);
  const [dejaRecherche, setDejaRecherche] = useState(false);

  const rechercher = useCallback(async (terme) => {
    if (!terme || terme.trim().length < 2) { setResultats([]); setDejaRecherche(false); return; }
    setLoading(true); setErreur(null);
    try {
      const r = await api.get('/api/clients/search', { params: { q: terme.trim() } });
      setResultats(r.data.data || []);
      setDejaRecherche(true);
    } catch (e) {
      setErreur(e.response?.data?.detail || 'Erreur lors de la recherche');
    } finally { setLoading(false); }
  }, []);

  useEffect(() => {
    const t = setTimeout(() => rechercher(recherche), 300);
    return () => clearTimeout(t);
  }, [recherche, rechercher]);

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Clients</h1>
        <p className="text-sm text-gray-500 mt-1">Recherchez un client par nom, numéro, ville ou SIRET</p>
      </div>

      <div className="relative mb-6">
        <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
          {loading
            ? <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
            : <svg className="w-5 h-5 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>
          }
        </div>
        <input type="text" value={recherche} onChange={e => setRecherche(e.target.value)}
          placeholder="Rechercher un client… (nom, numéro, ville, SIRET)"
          className="w-full pl-12 pr-10 py-3 text-base border border-gray-300 rounded-xl shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 bg-white"
          autoFocus />
        {recherche && (
          <button className="absolute inset-y-0 right-0 pr-4 flex items-center text-gray-400 hover:text-gray-600" onClick={() => { setRecherche(''); setResultats([]); setDejaRecherche(false); }}>
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
          </button>
        )}
      </div>

      {erreur && <div className="mb-4 bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">{erreur}</div>}

      {dejaRecherche && resultats.length === 0 && !loading && (
        <div className="text-center py-16 text-gray-400">
          <p className="font-medium text-gray-500">Aucun client trouvé</p>
          <p className="text-sm mt-1">Essayez un autre terme ou synchronisez le cache Karlia</p>
        </div>
      )}

      {resultats.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="px-4 py-2 bg-gray-50 border-b text-xs text-gray-500 font-medium uppercase tracking-wide">{resultats.length} résultat{resultats.length > 1 ? 's' : ''}</div>
          <ul className="divide-y divide-gray-100">
            {resultats.map(client => (
              <li key={client.karlia_id} className="flex items-center justify-between px-4 py-3 hover:bg-blue-50 cursor-pointer transition-colors group" onClick={() => setFicheKarliaId(client.karlia_id)}>
                <div className="flex items-center gap-4">
                  <div className="w-9 h-9 rounded-full bg-blue-100 flex items-center justify-center flex-shrink-0">
                    <span className="text-sm font-bold text-blue-700">{client.nom?.charAt(0)?.toUpperCase()}</span>
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-gray-900 group-hover:text-blue-700 transition-colors">{client.nom}</p>
                    <div className="flex items-center gap-3 mt-0.5">
                      <span className="text-xs font-mono text-gray-500">N° {client.numero_client}</span>
                      {client.ville && <span className="text-xs text-gray-400">{client.ville}</span>}
                      {client.email && <span className="text-xs text-gray-400">{client.email}</span>}
                    </div>
                  </div>
                </div>
                <svg className="w-5 h-5 text-gray-300 group-hover:text-blue-500 transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" /></svg>
              </li>
            ))}
          </ul>
        </div>
      )}

      {!dejaRecherche && !loading && (
        <div className="text-center py-20 text-gray-300">
          <svg className="w-16 h-16 mx-auto mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" /></svg>
          <p className="text-gray-400 font-medium">Saisissez au moins 2 caractères pour lancer la recherche</p>
        </div>
      )}

      {ficheKarliaId && <FicheClient karlia_id={ficheKarliaId} onClose={() => setFicheKarliaId(null)} />}
    </div>
  );
}
