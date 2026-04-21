import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import api from '../services/api';
import { indicesAPI } from '../services/api';
import { format } from 'date-fns';
import { fr } from 'date-fns/locale';

// Icônes par famille de contrat
const FAMILLE_ICONS = {
  COSOLUCE: '🏛️',
  CANTINE: '🍽️',
  DIGITECH: '💻',
  MAINTENANCE: '🔧',
  ASSISTANCE_TEL: '📞',
  KIWI_BACKUP: '💾',
  AUTRE: '📋',
};

// Couleurs par famille de contrat
const FAMILLE_COLORS = {
  COSOLUCE: 'bg-blue-50 border-blue-200 text-blue-700',
  CANTINE: 'bg-amber-50 border-amber-200 text-amber-700',
  DIGITECH: 'bg-purple-50 border-purple-200 text-purple-700',
  MAINTENANCE: 'bg-emerald-50 border-emerald-200 text-emerald-700',
  ASSISTANCE_TEL: 'bg-cyan-50 border-cyan-200 text-cyan-700',
  KIWI_BACKUP: 'bg-teal-50 border-teal-200 text-teal-700',
  AUTRE: 'bg-gray-50 border-gray-200 text-gray-700',
};

// Config des statuts commandes
const STATUT_CONFIG = {
  nouvelles: { label: 'Nouvelles', icon: '🆕', color: 'bg-red-50 border-red-200 text-red-700', link: '/commandes/nouvelles' },
  a_planifier: { label: 'À planifier', icon: '📅', color: 'bg-orange-50 border-orange-200 text-orange-700', link: '/commandes/a-planifier' },
  planifiees: { label: 'Planifiées', icon: '✅', color: 'bg-green-50 border-green-200 text-green-700', link: '/commandes/planifiees' },
};

function FamilleCard({ famille }) {
  const icon = FAMILLE_ICONS[famille.code] || '📋';
  const colors = FAMILLE_COLORS[famille.code] || FAMILLE_COLORS.AUTRE;

  return (
    <Link
      to={`/contrats?famille=${famille.code}`}
      className={`block border rounded-xl p-4 transition-all hover:shadow-md hover:scale-[1.02] ${colors}`}
    >
      <div className="flex items-center gap-3">
        <span className="text-2xl">{icon}</span>
        <div className="min-w-0 flex-1">
          <div className="text-2xl font-bold">{famille.total}</div>
          <div className="text-sm font-medium truncate">{famille.label}</div>
        </div>
      </div>
    </Link>
  );
}

function CommandeStatutCard({ statut, count }) {
  const config = STATUT_CONFIG[statut];
  if (!config) return null;

  return (
    <Link
      to={config.link}
      className={`block border rounded-xl p-4 transition-all hover:shadow-md hover:scale-[1.02] ${config.color}`}
    >
      <div className="flex items-center gap-3">
        <span className="text-2xl">{config.icon}</span>
        <div className="min-w-0 flex-1">
          <div className="text-2xl font-bold">{count}</div>
          <div className="text-sm font-medium">{config.label}</div>
        </div>
      </div>
    </Link>
  );
}

export default function Dashboard() {
  const [dashboardStats, setDashboardStats] = useState(null);
  const [indice, setIndice] = useState(null);
  const [loading, setLoading] = useState(true);
  const [synchroInfo, setSynchroInfo] = useState(null);
  const [synchroLoading, setSynchroLoading] = useState(false);

  useEffect(() => {
    // Synchro automatique à l'ouverture + mise à jour du bandeau
    api.post('/api/synchro/lancer').then(r => setSynchroInfo(r.data)).catch(() => {
      api.get('/api/synchro/statut').then(r => setSynchroInfo(r.data)).catch(() => {});
    });

    Promise.all([
      api.get('/api/dashboard/stats'),
      indicesAPI.courant().catch(() => null),
    ]).then(([statsRes, indiceRes]) => {
      setDashboardStats(statsRes.data);
      if (indiceRes) setIndice(indiceRes.data);
    }).catch(err => {
      console.error('Erreur chargement dashboard:', err);
    }).finally(() => setLoading(false));
  }, []);

  const lancerSynchro = async () => {
    setSynchroLoading(true);
    try {
      const r = await api.post('/api/synchro/lancer');
      setSynchroInfo(r.data);
    } catch (e) {
      console.error(e);
    } finally {
      setSynchroLoading(false);
    }
  };

  if (loading) return <div className="flex items-center justify-center h-64 text-gray-400 text-lg">Chargement...</div>;

  const contrats = dashboardStats?.contrats_par_famille || [];
  const commandes = dashboardStats?.commandes_par_statut || {};
  const totalContrats = dashboardStats?.total_contrats || 0;

  return (
    <div className="space-y-6">
      {/* En-tête */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Tableau de bord</h1>
          <p className="text-gray-500 text-sm mt-1">{format(new Date(), "EEEE d MMMM yyyy", { locale: fr })}</p>
        </div>
        <div className="flex gap-3">
          <Link to="/contrats/tunnel?mode=nouveau" className="btn-primary">➕ Nouveau contrat</Link>
          <Link to="/indices" className="btn-secondary">📈 Saisir un indice</Link>
        </div>
      </div>

      {/* Bandeau synchro */}
      <div className="bg-white border border-gray-200 rounded-xl px-5 py-3 flex items-center justify-between">
        <div className="text-sm text-gray-500">
          🔄 Dernière synchronisation Karlia :
          <span className="font-medium text-gray-700 ml-1">{synchroInfo?.derniere_synchro || 'Inconnue'}</span>
          {synchroInfo?.stats && <span className="text-gray-400 ml-2">({synchroInfo.stats})</span>}
        </div>
        <button onClick={lancerSynchro} disabled={synchroLoading} className="btn-secondary text-sm py-1.5">
          {synchroLoading ? '⏳ Synchronisation...' : '🔄 Synchroniser maintenant'}
        </button>
      </div>

      {/* Contrats actifs par famille */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-gray-900">📄 Contrats actifs par famille</h2>
          <div className="flex items-center gap-3">
            <span className="text-sm text-gray-500">{totalContrats} contrat{totalContrats > 1 ? 's' : ''} actif{totalContrats > 1 ? 's' : ''}</span>
            <Link to="/contrats" className="text-blue-600 text-sm hover:underline">Voir tout →</Link>
          </div>
        </div>
        {contrats.length === 0 ? (
          <p className="text-gray-400 text-sm text-center py-6">Aucun contrat actif</p>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
            {contrats.map(f => (
              <FamilleCard key={f.code} famille={f} />
            ))}
          </div>
        )}
      </div>

      {/* État des commandes */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-gray-900">📦 État des commandes</h2>
          <span className="text-sm text-gray-500">{commandes.total || 0} commande{(commandes.total || 0) > 1 ? 's' : ''} au total</span>
        </div>
        <div className="grid grid-cols-3 gap-3">
          <CommandeStatutCard statut="nouvelles" count={commandes.nouvelles || 0} />
          <CommandeStatutCard statut="a_planifier" count={commandes.a_planifier || 0} />
          <CommandeStatutCard statut="planifiees" count={commandes.planifiees || 0} />
        </div>
      </div>

      {/* Dernier indice Syntec */}
      {indice?.indice && (
        <div className="card">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="font-semibold text-gray-900">📈 Dernier indice Syntec</h2>
              <p className="text-sm text-gray-500 mt-1">
                {indice.indice.mois} {indice.indice.annee} — Valeur : <span className="font-bold text-gray-900">{indice.indice.valeur}</span>
              </p>
            </div>
            <Link to="/indices" className="text-blue-600 text-sm hover:underline">Gérer les indices →</Link>
          </div>
        </div>
      )}
    </div>
  );
}
