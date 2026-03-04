import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { contratsAPI } from '../services/api';
import { format } from 'date-fns';
function StatutBadge({ statut }) {
  const map = { EN_COURS: <span className="badge-green">En cours</span>, A_RENOUVELER: <span className="badge-orange">À renouveler</span>, TERMINE: <span className="badge-gray">Terminé</span>, BROUILLON: <span className="badge-blue">Brouillon</span> };
  return map[statut] || <span className="badge-gray">{statut}</span>;
}
export default function Contrats() {
  const [contrats, setContrats] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [recherche, setRecherche] = useState('');
  const [statut, setStatut] = useState('');
  const [page, setPage] = useState(0);
  const limit = 20;
  const charger = () => {
    setLoading(true);
    contratsAPI.liste({ recherche: recherche || undefined, statut: statut || undefined, limit, offset: page * limit })
      .then(r => { setContrats(r.data.data || []); setTotal(r.data.total || 0); })
      .finally(() => setLoading(false));
  };
  useEffect(() => { charger(); }, [page]);
  const handleRecherche = (e) => { e.preventDefault(); setPage(0); charger(); };
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div><h1 className="text-2xl font-bold text-gray-900">Contrats</h1><p className="text-gray-500 text-sm mt-1">{total} contrat(s)</p></div>
        <Link to="/contrats/nouveau" className="btn-primary">➕ Nouveau contrat</Link>
      </div>
      <div className="card">
        <form onSubmit={handleRecherche} className="flex gap-3 flex-wrap">
          <input className="input flex-1 min-w-48" placeholder="🔍 Rechercher..." value={recherche} onChange={e => setRecherche(e.target.value)} />
          <select className="input w-48" value={statut} onChange={e => setStatut(e.target.value)}>
            <option value="">Tous les statuts</option>
            <option value="BROUILLON">Brouillon</option>
            <option value="EN_COURS">En cours</option>
            <option value="A_RENOUVELER">À renouveler</option>
            <option value="TERMINE">Terminé</option>
          </select>
          <button type="submit" className="btn-primary">Rechercher</button>
          <button type="button" className="btn-secondary" onClick={() => { setRecherche(''); setStatut(''); setPage(0); setTimeout(charger, 100); }}>Réinitialiser</button>
        </form>
      </div>
      <div className="card p-0 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="text-left px-4 py-3 font-medium text-gray-600">N° Contrat</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Client</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Début</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Fin</th>
              <th className="text-right px-4 py-3 font-medium text-gray-600">Montant HT/an</th>
              <th className="text-center px-4 py-3 font-medium text-gray-600">Statut</th>
              <th className="text-center px-4 py-3 font-medium text-gray-600">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading ? <tr><td colSpan={7} className="text-center py-12 text-gray-400">Chargement...</td></tr>
            : contrats.length === 0 ? <tr><td colSpan={7} className="text-center py-12 text-gray-400">Aucun contrat trouvé</td></tr>
            : contrats.map(c => (
              <tr key={c.id} className="hover:bg-gray-50">
                <td className="px-4 py-3 font-medium text-blue-700"><Link to={`/contrats/${c.id}`} className="hover:underline">{c.numero_contrat}</Link></td>
                <td className="px-4 py-3 text-gray-700"><div>{c.client_nom}</div>{c.client_numero && <div className="text-xs text-gray-400">{c.client_numero}</div>}</td>
                <td className="px-4 py-3 text-gray-600">{c.date_debut ? format(new Date(c.date_debut), 'dd/MM/yyyy') : '-'}</td>
                <td className="px-4 py-3 text-gray-600">{c.date_fin ? format(new Date(c.date_fin), 'dd/MM/yyyy') : '-'}</td>
                <td className="px-4 py-3 text-right font-medium">{c.montant_annuel_ht?.toLocaleString('fr-FR', { minimumFractionDigits: 2 })} €</td>
                <td className="px-4 py-3 text-center"><StatutBadge statut={c.statut} /></td>
                <td className="px-4 py-3 text-center"><Link to={`/contrats/${c.id}`} className="text-blue-600 hover:text-blue-800">👁 Voir</Link></td>
              </tr>
            ))}
          </tbody>
        </table>
        {total > limit && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-gray-200 bg-gray-50">
            <span className="text-sm text-gray-600">{page * limit + 1}–{Math.min((page + 1) * limit, total)} sur {total}</span>
            <div className="flex gap-2">
              <button className="btn-secondary py-1 px-3 text-xs" disabled={page === 0} onClick={() => setPage(p => p - 1)}>← Préc.</button>
              <button className="btn-secondary py-1 px-3 text-xs" disabled={(page + 1) * limit >= total} onClick={() => setPage(p => p + 1)}>Suiv. →</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
