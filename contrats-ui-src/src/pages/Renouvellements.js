import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { contratsAPI } from '../services/api';
import { format } from 'date-fns';
import toast from 'react-hot-toast';

const moisNoms = ['Janvier','Février','Mars','Avril','Mai','Juin','Juillet','Août','Septembre','Octobre','Novembre','Décembre'];

export default function Renouvellements() {
  const [contrats, setContrats] = useState([]);
  const [loading, setLoading] = useState(true);
  const [mois, setMois] = useState(new Date().getMonth() + 1);
  const [annee, setAnnee] = useState(new Date().getFullYear());

  // Sélection multiple
  const [selection, setSelection] = useState(new Set());

  // Action individuelle (modale inline)
  const [actionId, setActionId] = useState(null);
  const [typeRenouvellement, setTypeRenouvellement] = useState('SPONTANE');
  const [actionLoading, setActionLoading] = useState(false);

  // Action en lot
  const [typeRenouvellementLot, setTypeRenouvellementLot] = useState('SPONTANE');
  const [lotLoading, setLotLoading] = useState(false);

  const charger = () => {
    setLoading(true);
    setSelection(new Set());
    contratsAPI.renouvellements({ mois, annee })
      .then(r => setContrats(r.data.data || []))
      .catch(() => toast.error('Erreur chargement'))
      .finally(() => setLoading(false));
  };

  useEffect(() => { charger(); }, [mois, annee]);

  // Sélection
  const toggleSelection = (id) => {
    setSelection(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };
  const toutSelectionner = () => {
    if (selection.size === contrats.length) {
      setSelection(new Set());
    } else {
      setSelection(new Set(contrats.map(c => c.id)));
    }
  };

  // Action individuelle
  const traiterRenouvellement = async (id) => {
    setActionLoading(true);
    try {
      const r = await contratsAPI.renouveler(id, { type_renouvellement: typeRenouvellement });
      toast.success(r.data.message);
      setActionId(null);
      charger();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Erreur');
    } finally {
      setActionLoading(false);
    }
  };

  // Action en lot
  const traiterLot = async () => {
    if (selection.size === 0) return;
    setLotLoading(true);
    try {
      const r = await contratsAPI.renouvelerLot({
        ids: Array.from(selection),
        type_renouvellement: typeRenouvellementLot,
      });
      const { traites, erreurs, detail_erreurs } = r.data;
      if (erreurs > 0) {
        toast.error(`${traites} traité(s), ${erreurs} erreur(s) : ${detail_erreurs.map(e => e.erreur).join(', ')}`);
      } else {
        toast.success(`${traites} contrat(s) traité(s) avec succès`);
      }
      charger();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Erreur traitement lot');
    } finally {
      setLotLoading(false);
    }
  };

  const tousCoches = contrats.length > 0 && selection.size === contrats.length;
  const partiellementCoches = selection.size > 0 && selection.size < contrats.length;

  return (
    <div className="space-y-6">
      {/* En-tête */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Renouvellements</h1>
        <p className="text-gray-500 text-sm mt-1">Contrats arrivant à échéance</p>
      </div>

      {/* Filtres */}
      <div className="card">
        <div className="flex gap-4 items-end flex-wrap">
          <div>
            <label className="label">Mois</label>
            <select className="input w-40" value={mois} onChange={e => { setMois(parseInt(e.target.value)); }}>
              {moisNoms.map((m, i) => <option key={i+1} value={i+1}>{m}</option>)}
            </select>
          </div>
          <div>
            <label className="label">Année</label>
            <select className="input w-28" value={annee} onChange={e => { setAnnee(parseInt(e.target.value)); }}>
              {[-1, 0, 1].map(o => { const a = new Date().getFullYear() + o; return <option key={a} value={a}>{a}</option>; })}
            </select>
          </div>
          <button onClick={charger} className="btn-secondary">Actualiser</button>
        </div>
      </div>

      {/* Bandeau résumé */}
      <div className="bg-orange-50 border border-orange-200 rounded-xl p-4 flex items-center gap-3">
        <span className="text-2xl">⚠️</span>
        <div>
          <span className="font-semibold text-orange-900">{contrats.length} contrat(s)</span>
          <span className="text-orange-800"> arrivent à échéance en {moisNoms[mois-1]} {annee}</span>
        </div>
      </div>

      {/* Panneau action en lot — visible dès qu'au moins 1 coché */}
      {selection.size > 0 && (
        <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2 text-blue-900 font-semibold">
            <span className="inline-flex items-center justify-center w-7 h-7 rounded-full bg-blue-600 text-white text-sm font-bold">
              {selection.size}
            </span>
            contrat(s) sélectionné(s)
          </div>
          <div className="flex items-center gap-3 ml-auto flex-wrap">
            <select
              className="input w-52"
              value={typeRenouvellementLot}
              onChange={e => setTypeRenouvellementLot(e.target.value)}
            >
              <option value="SPONTANE">🔄 Reconduire (+1 an)</option>
              <option value="FIN">🛑 Terminer sans suite</option>
            </select>
            <button
              onClick={traiterLot}
              disabled={lotLoading}
              className="btn-primary disabled:opacity-50"
            >
              {lotLoading ? 'Traitement...' : `Appliquer aux ${selection.size} contrat(s)`}
            </button>
            <button
              onClick={() => setSelection(new Set())}
              className="btn-secondary text-sm"
            >
              Désélectionner tout
            </button>
          </div>
        </div>
      )}

      {/* Tableau */}
      <div className="card p-0 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="px-4 py-3 w-10">
                <input
                  type="checkbox"
                  checked={tousCoches}
                  ref={el => { if (el) el.indeterminate = partiellementCoches; }}
                  onChange={toutSelectionner}
                  className="w-4 h-4 rounded border-gray-300 text-blue-600 cursor-pointer"
                  title="Tout sélectionner"
                />
              </th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Contrat</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Client</th>
              <th className="text-right px-4 py-3 font-medium text-gray-600">Montant HT/an</th>
              <th className="text-center px-4 py-3 font-medium text-gray-600">Échéance</th>
              <th className="text-center px-4 py-3 font-medium text-gray-600">Action individuelle</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading ? (
              <tr><td colSpan={6} className="text-center py-8 text-gray-400">Chargement...</td></tr>
            ) : contrats.length === 0 ? (
              <tr><td colSpan={6} className="text-center py-8 text-gray-400">Aucun contrat à renouveler ce mois</td></tr>
            ) : contrats.map(c => (
              <React.Fragment key={c.id}>
                <tr className={`hover:bg-gray-50 transition-colors ${selection.has(c.id) ? 'bg-blue-50' : ''}`}>
                  <td className="px-4 py-3">
                    <input
                      type="checkbox"
                      checked={selection.has(c.id)}
                      onChange={() => toggleSelection(c.id)}
                      className="w-4 h-4 rounded border-gray-300 text-blue-600 cursor-pointer"
                    />
                  </td>
                  <td className="px-4 py-3 font-medium text-blue-700">
                    <Link to={`/contrats/${c.id}`} className="hover:underline">{c.numero_contrat}</Link>
                  </td>
                  <td className="px-4 py-3 text-gray-700">{c.client_nom}</td>
                  <td className="px-4 py-3 text-right font-medium">
                    {c.montant_annuel_ht?.toLocaleString('fr-FR', { minimumFractionDigits: 2 })} €
                  </td>
                  <td className="px-4 py-3 text-center text-orange-700 font-medium">
                    {c.date_fin ? format(new Date(c.date_fin + 'T12:00:00'), 'dd/MM/yyyy') : '-'}
                  </td>
                  <td className="px-4 py-3 text-center">
                    <button
                      onClick={() => setActionId(actionId === c.id ? null : c.id)}
                      className="btn-secondary text-xs px-3 py-1"
                    >
                      {actionId === c.id ? 'Fermer' : 'Traiter'}
                    </button>
                  </td>
                </tr>

                {/* Panneau action individuelle inline */}
                {actionId === c.id && (
                  <tr className="bg-orange-50">
                    <td colSpan={6} className="px-6 py-4">
                      <div className="flex flex-wrap items-center gap-4">
                        <div>
                          <label className="label text-xs">Type de renouvellement</label>
                          <select
                            className="input w-60 text-sm"
                            value={typeRenouvellement}
                            onChange={e => setTypeRenouvellement(e.target.value)}
                          >
                            <option value="SPONTANE">🔄 Reconduire (+1 an)</option>
                            <option value="NOUVEAU_CONTRAT">📄 Créer un nouveau contrat</option>
                            <option value="FIN">🛑 Terminer sans suite</option>
                          </select>
                        </div>
                        <div className="flex gap-2 mt-4">
                          <button
                            onClick={() => traiterRenouvellement(c.id)}
                            disabled={actionLoading}
                            className="btn-primary text-sm disabled:opacity-50"
                          >
                            {actionLoading ? 'En cours...' : 'Confirmer'}
                          </button>
                          <button
                            onClick={() => setActionId(null)}
                            className="btn-secondary text-sm"
                          >
                            Annuler
                          </button>
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
