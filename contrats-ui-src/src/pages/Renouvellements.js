import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { contratsAPI } from '../services/api';
import { format } from 'date-fns';
import toast from 'react-hot-toast';
export default function Renouvellements() {
  const [contrats, setContrats] = useState([]);
  const [loading, setLoading] = useState(true);
  const [mois, setMois] = useState(new Date().getMonth() + 1);
  const [annee, setAnnee] = useState(new Date().getFullYear());
  const [actionId, setActionId] = useState(null);
  const [typeRenouvellement, setTypeRenouvellement] = useState('SPONTANE');
  const [actionLoading, setActionLoading] = useState(false);
  const charger = () => { setLoading(true); contratsAPI.renouvellements({ mois, annee }).then(r => setContrats(r.data.data || [])).catch(() => toast.error('Erreur chargement')).finally(() => setLoading(false)); };
  useEffect(() => { charger(); }, [mois, annee]);
  const traiterRenouvellement = async (id) => {
    setActionLoading(true);
    try { const r = await contratsAPI.renouveler(id, { type_renouvellement: typeRenouvellement }); toast.success(r.data.message); setActionId(null); charger(); }
    catch (e) { toast.error(e.response?.data?.detail || 'Erreur'); }
    finally { setActionLoading(false); }
  };
  const moisNoms = ['Janvier','Février','Mars','Avril','Mai','Juin','Juillet','Août','Septembre','Octobre','Novembre','Décembre'];
  return (
    <div className="space-y-6">
      <div><h1 className="text-2xl font-bold text-gray-900">Renouvellements</h1><p className="text-gray-500 text-sm mt-1">Contrats arrivant à échéance</p></div>
      <div className="card">
        <div className="flex gap-4 items-end">
          <div><label className="label">Mois</label><select className="input w-40" value={mois} onChange={e => setMois(parseInt(e.target.value))}>{moisNoms.map((m,i) => <option key={i+1} value={i+1}>{m}</option>)}</select></div>
          <div><label className="label">Année</label><select className="input w-28" value={annee} onChange={e => setAnnee(parseInt(e.target.value))}>{[-1,0,1].map(o => { const a = new Date().getFullYear()+o; return <option key={a} value={a}>{a}</option>; })}</select></div>
          <button onClick={charger} className="btn-secondary">Actualiser</button>
        </div>
      </div>
      <div className="bg-orange-50 border border-orange-200 rounded-xl p-4 flex items-center gap-3">
        <span className="text-2xl">⚠️</span>
        <div><span className="font-semibold text-orange-900">{contrats.length} contrat(s)</span><span className="text-orange-800"> arrivent à échéance en {moisNoms[mois-1]} {annee}</span></div>
      </div>
      <div className="card p-0 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200"><tr><th className="text-left px-4 py-3 font-medium text-gray-600">Contrat</th><th className="text-left px-4 py-3 font-medium text-gray-600">Client</th><th className="text-right px-4 py-3 font-medium text-gray-600">Montant HT/an</th><th className="text-center px-4 py-3 font-medium text-gray-600">Échéance</th><th className="text-center px-4 py-3 font-medium text-gray-600">Actions</th></tr></thead>
          <tbody className="divide-y divide-gray-100">
            {loading ? <tr><td colSpan={5} className="text-center py-8 text-gray-400">Chargement...</td></tr>
            : contrats.length === 0 ? <tr><td colSpan={5} className="text-center py-8 text-gray-400">Aucun contrat à renouveler ce mois</td></tr>
            : contrats.map(c => (
              <React.Fragment key={c.id}>
                <tr className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-blue-700"><Link to={`/contrats/${c.id}`} className="hover:underline">{c.numero_contrat}</Link></td>
                  <td className="px-4 py-3 text-gray-700">{c.client_nom}</td>
                  <td className="px-4 py-3 text-right font-medium">{c.montant_annuel_ht?.toLocaleString('fr-FR', { minimumFractionDigits: 2 })} €</td>
                  <td className="px-4 py-3 text-center text-orange-700 font-medium">{c.date_fin ? format(new Date(c.date_fin), 'dd/MM/yyyy') : '-'}</td>
                  <td className="px-4 py-3 text-center"><button onClick={() => setActionId(actionId === c.id ? null : c.id)} className="btn-secondary text-xs py-1 px-3">🔄 Traiter</button></td>
                </tr>
                {actionId === c.id && (
                  <tr>
                    <td colSpan={5} className="px-4 py-4 bg-gray-50 border-b border-gray-200">
                      <div className="space-y-3 max-w-xl">
                        <div className="font-medium text-gray-900 text-sm">Type de renouvellement :</div>
                        <div className="grid grid-cols-3 gap-3">
                          {[{ value: 'SPONTANE', label: '✅ Spontané', desc: 'Prolonge +1 an' },
                            { value: 'NOUVEAU_CONTRAT', label: '📄 Nouveau contrat', desc: 'Fusionne les avenants' },
                            { value: 'FIN', label: '🚫 Fin', desc: 'Clôture sans suite' }
                          ].map(opt => (
                            <label key={opt.value} className={`flex flex-col gap-1 p-3 rounded-lg border cursor-pointer ${typeRenouvellement === opt.value ? 'border-blue-400 bg-blue-50' : 'border-gray-200 hover:bg-gray-100'}`}>
                              <div className="flex items-center gap-2"><input type="radio" name={`type-${c.id}`} value={opt.value} checked={typeRenouvellement === opt.value} onChange={e => setTypeRenouvellement(e.target.value)} /><span className="font-medium text-sm">{opt.label}</span></div>
                              <span className="text-xs text-gray-500 ml-5">{opt.desc}</span>
                            </label>
                          ))}
                        </div>
                        <div className="flex gap-2">
                          <button onClick={() => traiterRenouvellement(c.id)} disabled={actionLoading} className="btn-primary text-sm">{actionLoading ? 'Traitement...' : 'Confirmer'}</button>
                          <button onClick={() => setActionId(null)} className="btn-secondary text-sm">Annuler</button>
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
