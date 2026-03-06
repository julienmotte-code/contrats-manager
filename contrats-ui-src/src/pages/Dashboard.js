import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { contratsAPI, facturationAPI, indicesAPI } from '../services/api';
import api from '../services/api';
import { format } from 'date-fns';
import { fr } from 'date-fns/locale';
function KPI({ label, value, color, icon }) {
  return (
    <div className="card flex items-center gap-4">
      <div className={`text-3xl p-3 rounded-xl ${color}`}>{icon}</div>
      <div><div className="text-2xl font-bold text-gray-900">{value}</div><div className="text-sm text-gray-500">{label}</div></div>
    </div>
  );
}
export default function Dashboard() {
  const [renouvellements, setRenouvellements] = useState([]);
  const [facturesAVenir, setFacturesAVenir] = useState([]);
  const [stats, setStats] = useState({ actifs: 0, renouveler: 0, ca: 0 });
  const [indice, setIndice] = useState(null);
  const [loading, setLoading] = useState(true);
  const [synchroInfo, setSynchroInfo] = useState(null);
  const [synchroLoading, setSynchroLoading] = useState(false);
  const annee = new Date().getFullYear();
  const mois = new Date().getMonth() + 1;

  useEffect(() => {
    // Synchro automatique à l'ouverture + mise à jour du bandeau
    api.post('/api/synchro/lancer').then(r => setSynchroInfo(r.data)).catch(() => {
      api.get('/api/synchro/statut').then(r => setSynchroInfo(r.data)).catch(() => {});
    });
    Promise.all([
      contratsAPI.liste({ statut: 'EN_COURS', limit: 200 }),
      contratsAPI.renouvellements({ mois, annee }),
      facturationAPI.apercu(annee + 1),
      indicesAPI.courant().catch(() => null),
    ]).then(([contratsRes, renouvRes, factRes, indiceRes]) => {
      const contrats = contratsRes.data.data || [];
      const ca = contrats.reduce((s, c) => s + (c.montant_annuel_ht || 0), 0);
      setStats({ actifs: contratsRes.data.total || 0, renouveler: renouvRes.data.total || 0, ca: ca.toLocaleString('fr-FR') });
      setRenouvellements(renouvRes.data.data?.slice(0, 5) || []);
      setFacturesAVenir(factRes.data.data?.slice(0, 5) || []);
      if (indiceRes) setIndice(indiceRes.data);
    }).finally(() => setLoading(false));
  }, []);

  const lancerSynchro = async () => {
    setSynchroLoading(true);
    try {
      const r = await api.post('/api/synchro/lancer');
      setSynchroInfo(r.data);
    } catch(e) { console.error(e); }
    finally { setSynchroLoading(false); }
  };

  if (loading) return <div className="flex items-center justify-center h-64 text-gray-400 text-lg">Chargement...</div>;
  return (
    <div className="space-y-6">
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

      {/* KPIs */}
      <div className="grid grid-cols-3 gap-4">
        <KPI label="Contrats actifs" value={stats.actifs} icon="📄" color="bg-blue-50" />
        <KPI label="CA annuel HT" value={`${stats.ca} €`} icon="💶" color="bg-green-50" />
        <KPI label="À renouveler ce mois" value={stats.renouveler} icon="⚠️" color="bg-orange-50" />
      </div>



      <div className="grid grid-cols-2 gap-6">
        <div className="card">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold text-gray-900">🔄 Renouvellements ce mois</h2>
            <Link to="/renouvellements" className="text-blue-600 text-sm">Voir tout →</Link>
          </div>
          {renouvellements.length === 0 ? <p className="text-gray-400 text-sm text-center py-4">Aucun renouvellement ce mois</p> : (
            <div className="space-y-2">
              {renouvellements.map(c => (
                <Link key={c.id} to={`/contrats/${c.id}`} className="flex items-center justify-between p-3 rounded-lg hover:bg-gray-50 border border-gray-100">
                  <div><div className="font-medium text-sm">{c.numero_contrat}</div><div className="text-xs text-gray-500">{c.client_nom}</div></div>
                  <div className="text-right"><div className="text-sm font-medium">{c.montant_annuel_ht?.toLocaleString('fr-FR')} €</div><div className="text-xs text-orange-600">{c.date_fin ? format(new Date(c.date_fin), 'dd/MM/yyyy') : ''}</div></div>
                </Link>
              ))}
            </div>
          )}
        </div>
        <div className="card">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold text-gray-900">💶 Prochaines factures ({annee + 1})</h2>
            <Link to="/facturation" className="text-blue-600 text-sm">Gérer →</Link>
          </div>
          {facturesAVenir.length === 0 ? <p className="text-gray-400 text-sm text-center py-4">Aucune facture planifiée</p> : (
            <div className="space-y-2">
              {facturesAVenir.map(f => (
                <div key={f.id} className="flex items-center justify-between p-3 rounded-lg border border-gray-100">
                  <div><div className="font-medium text-sm">{f.contrat_numero}</div><div className="text-xs text-gray-500">{f.client_nom}</div></div>
                  <div className="text-right"><div className="text-sm font-medium">{f.montant_ht_prevu?.toLocaleString('fr-FR')} €</div><span className="badge-blue text-xs">Planifiée</span></div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
