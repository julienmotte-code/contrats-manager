import React, { useState, useEffect, useCallback } from 'react';
import api from '../services/api';
import toast from 'react-hot-toast';

export default function Facturation() {
  const anneeCourante = new Date().getFullYear();
  const [annee, setAnnee] = useState(anneeCourante);
  const [familles, setFamilles] = useState([]);
  const [filtreFamille, setFiltreFamille] = useState('');
  const [factures, setFactures] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState(new Set());
  const [emitting, setEmitting] = useState(false);
  const [calculating, setCalculating] = useState(false);
  const [resultat, setResultat] = useState(null);
  const [showDigitech, setShowDigitech] = useState(false);
  const [montantsDigitech, setMontantsDigitech] = useState({});

  useEffect(() => {
    api.get('/api/indices/familles').then(r => setFamilles(r.data.data || []));
  }, []);

  const charger = useCallback(() => {
    setLoading(true);
    setSelected(new Set());
    setResultat(null);
    const params = filtreFamille ? `?famille=${filtreFamille}` : '';
    api.get(`/api/facturation/apercu/${annee}${params}`)
      .then(r => setFactures(r.data.data || []))
      .finally(() => setLoading(false));
  }, [annee, filtreFamille]);

  useEffect(() => { charger(); }, [charger]);

  const toggleSelect = (id) => {
    setSelected(s => {
      const n = new Set(s);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });
  };

  const selectAll = () => setSelected(new Set(facturesFiltrees.map(f => f.plan_id)));
  const deselectAll = () => setSelected(new Set());

  const selectFamille = (famille) => {
    const ids = facturesFiltrees.filter(f => f.famille_contrat === famille).map(f => f.plan_id);
    setSelected(s => {
      const n = new Set(s);
      ids.forEach(id => n.add(id));
      return n;
    });
  };

  // Factures filtrées et facturable selon année
  const facturesFiltrees = factures.filter(f => !filtreFamille || f.famille_contrat === filtreFamille);
  const facturesSelectionnees = facturesFiltrees.filter(f => selected.has(f.plan_id));
  const hasDigitech = facturesSelectionnees.some(f => f.regle_revision === 'MANUELLE');
  const indicesManquants = facturesSelectionnees.filter(f => !f.indices_ok && f.regle_revision !== 'MANUELLE' && f.regle_revision !== 'AUCUNE');

  const calculer = async () => {
    if (selected.size === 0) { toast.error('Sélectionnez au moins un contrat'); return; }
    if (indicesManquants.length > 0) {
      toast.error(`Indices manquants pour : ${indicesManquants.map(f => f.numero_contrat).join(', ')}`);
      return;
    }
    if (hasDigitech && Object.keys(montantsDigitech).length === 0) {
      setShowDigitech(true);
      return;
    }
    setCalculating(true);
    try {
      const r = await api.post('/api/facturation/calculer', {
        annee,
        plan_ids: [...selected],
        nouveaux_montants: montantsDigitech,
      });
      toast.success('Calculs effectués');
      setShowDigitech(false);
      charger();
    } catch (e) { toast.error(e.response?.data?.detail || 'Erreur calcul'); }
    finally { setCalculating(false); }
  };

  const emettre = async () => {
    if (selected.size === 0) { toast.error('Sélectionnez au moins un contrat'); return; }
    if (indicesManquants.length > 0) {
      toast.error(`Indices manquants pour : ${indicesManquants.map(f => f.numero_contrat).join(', ')}`);
      return;
    }
    const nonCalcules = facturesSelectionnees.filter(f => f.statut === 'PLANIFIEE');
    if (nonCalcules.length > 0) {
      toast.error(`Calculez d'abord les montants avant d'émettre`);
      return;
    }
    if (!window.confirm(`Émettre ${selected.size} facture(s) dans Karlia pour ${annee} ?`)) return;
    setEmitting(true);
    try {
      const r = await api.post('/api/facturation/lancer', { annee, plan_ids: [...selected] });
      setResultat(r.data);
      if (r.data.emises > 0) toast.success(`${r.data.emises} facture(s) émise(s) dans Karlia`);
      if (r.data.erreurs > 0) toast.error(`${r.data.erreurs} erreur(s)`);
      charger();
    } catch (e) { toast.error(e.response?.data?.detail || 'Erreur émission'); }
    finally { setEmitting(false); }
  };

  const famillesPresentes = [...new Set(facturesFiltrees.map(f => f.famille_contrat))];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Facturation</h1>
        <p className="text-gray-500 text-sm mt-1">Émission des factures annuelles avec révision des indices</p>
      </div>

      {/* Sélection année + famille */}
      <div className="card flex flex-wrap gap-4 items-end">
        <div>
          <label className="label">Année</label>
          <div className="flex gap-2 items-center">
            <button onClick={() => setAnnee(a => a - 1)} className="btn-secondary px-3">◀</button>
            <span className={`text-xl font-bold px-4 py-2 rounded-lg ${annee === anneeCourante ? 'bg-green-100 text-green-800' : annee < anneeCourante ? 'bg-gray-100 text-gray-700' : 'bg-red-100 text-red-700'}`}>
              {annee}
              {annee === anneeCourante && <span className="text-xs ml-1">(en cours)</span>}
              {annee > anneeCourante && <span className="text-xs ml-1">⚠️ futur</span>}
            </span>
            <button onClick={() => setAnnee(a => a + 1)} className="btn-secondary px-3">▶</button>
          </div>
        </div>
        <div>
          <label className="label">Famille</label>
          <select className="input w-56" value={filtreFamille} onChange={e => setFiltreFamille(e.target.value)}>
            <option value="">Toutes les familles</option>
            {familles.map(f => <option key={f.code} value={f.code}>{f.label}</option>)}
          </select>
        </div>
      </div>

      {/* Alerte année future */}
      {annee > anneeCourante && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-800">
          ⚠️ Vous consultez l'année <strong>{annee}</strong> — la facturation est désactivée pour les années futures.
        </div>
      )}

      {/* Sélection rapide par famille */}
      {famillesPresentes.length > 1 && (
        <div className="flex flex-wrap gap-2 items-center">
          <span className="text-sm text-gray-500">Sélection rapide :</span>
          {famillesPresentes.map(f => {
            const famille = familles.find(x => x.code === f);
            return (
              <button key={f} onClick={() => selectFamille(f)} className="btn-secondary text-xs">
                {famille?.label || f}
              </button>
            );
          })}
          <button onClick={selectAll} className="btn-secondary text-xs">✅ Tout</button>
          <button onClick={deselectAll} className="btn-secondary text-xs">☐ Aucun</button>
        </div>
      )}

      {/* Alertes indices manquants */}
      {indicesManquants.length > 0 && (
        <div className="bg-orange-50 border border-orange-200 rounded-lg px-4 py-3 text-sm text-orange-800">
          ⚠️ Indices manquants pour les contrats sélectionnés :
          <ul className="mt-1 list-disc list-inside">
            {indicesManquants.map(f => <li key={f.plan_id}><strong>{f.numero_contrat}</strong> ({f.client_nom}) — {f.indices_message}</li>)}
          </ul>
          <a href="/indices" className="underline font-medium mt-1 inline-block">→ Aller saisir les indices</a>
        </div>
      )}

      {/* Popup Digitech */}
      {showDigitech && (
        <div className="card border-2 border-blue-300 space-y-4">
          <h3 className="font-semibold text-blue-900">✏️ Révision manuelle — Contrats Digitech</h3>
          <p className="text-sm text-blue-700">Saisissez le nouveau montant annuel pour chaque contrat Digitech sélectionné.</p>
          {facturesSelectionnees.filter(f => f.regle_revision === 'MANUELLE').map(f => (
            <div key={f.plan_id} className="grid grid-cols-3 gap-4 items-center border-b pb-3">
              <div>
                <div className="font-medium text-sm">{f.numero_contrat}</div>
                <div className="text-xs text-gray-500">{f.client_nom}</div>
              </div>
              <div className="text-sm text-gray-600">
                Montant N-1 : <strong>{f.montant_annuel_precedent?.toLocaleString('fr-FR', { minimumFractionDigits: 2 })} €</strong>
              </div>
              <div>
                <input className="input text-sm" type="number" step="0.01" placeholder="Nouveau montant HT"
                  value={montantsDigitech[f.plan_id] || ''}
                  onChange={e => setMontantsDigitech(m => ({ ...m, [f.plan_id]: e.target.value }))} />
              </div>
            </div>
          ))}
          <div className="flex gap-3">
            <button onClick={calculer} disabled={calculating} className="btn-primary">
              {calculating ? 'Calcul...' : '✅ Valider et calculer'}
            </button>
            <button onClick={() => setShowDigitech(false)} className="btn-secondary">Annuler</button>
          </div>
        </div>
      )}

      {/* Tableau */}
      {loading ? (
        <div className="text-center text-gray-400 py-8">Chargement...</div>
      ) : facturesFiltrees.length === 0 ? (
        <div className="text-center text-gray-400 py-12">Aucune facture à émettre pour {annee}</div>
      ) : (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-gray-500 border-b">
                <th className="pb-3 pr-4"><input type="checkbox" onChange={e => e.target.checked ? selectAll() : deselectAll()} checked={selected.size === facturesFiltrees.length && facturesFiltrees.length > 0} /></th>
                <th className="pb-3">Contrat</th>
                <th className="pb-3">Client</th>
                <th className="pb-3">Famille</th>
                <th className="pb-3">Révision</th>
                <th className="pb-3 text-right">Montant N-1</th>
                <th className="pb-3 text-right">Montant révisé</th>
                <th className="pb-3">Statut</th>
                <th className="pb-3">Indices</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {facturesFiltrees.map(f => {
                const famille = familles.find(x => x.code === f.famille_contrat);
                return (
                  <tr key={f.plan_id} className={`hover:bg-gray-50 ${selected.has(f.plan_id) ? 'bg-blue-50' : ''}`}>
                    <td className="py-3 pr-4">
                      <input type="checkbox" checked={selected.has(f.plan_id)}
                        onChange={() => toggleSelect(f.plan_id)}
                        disabled={!f.facturable} />
                    </td>
                    <td className="py-3 font-medium">{f.numero_contrat}</td>
                    <td className="py-3 text-gray-600">{f.client_nom}</td>
                    <td className="py-3">
                      <span className="px-2 py-0.5 bg-gray-100 rounded text-xs">{famille?.label || f.famille_contrat}</span>
                    </td>
                    <td className="py-3 text-xs text-gray-500">{f.regle_revision}</td>
                    <td className="py-3 text-right font-mono">{f.montant_annuel_precedent?.toLocaleString('fr-FR', { minimumFractionDigits: 2 })} €</td>
                    <td className="py-3 text-right font-mono font-medium">
                      {f.montant_revise ? (
                        <span className="text-green-700">{parseFloat(f.montant_revise).toLocaleString('fr-FR', { minimumFractionDigits: 2 })} €</span>
                      ) : (
                        <span className="text-gray-400">— à calculer</span>
                      )}
                    </td>
                    <td className="py-3">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                        f.statut === 'EMISE' ? 'bg-green-100 text-green-800' :
                        f.statut === 'CALCULEE' ? 'bg-blue-100 text-blue-800' :
                        f.statut === 'ERREUR' ? 'bg-red-100 text-red-800' :
                        'bg-gray-100 text-gray-700'
                      }`}>{f.statut}</span>
                    </td>
                    <td className="py-3">
                      {f.regle_revision === 'AUCUNE' ? <span className="text-xs text-gray-400">Prix fixe</span> :
                       f.regle_revision === 'MANUELLE' ? <span className="text-xs text-blue-600">Saisie manuelle</span> :
                       f.indices_ok ? <span className="text-xs text-green-600">✅</span> :
                       <span className="text-xs text-red-600">❌ {f.indices_message}</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Actions */}
      {selected.size > 0 && (
        <div className="sticky bottom-4 bg-white border border-gray-200 rounded-xl shadow-lg px-6 py-4 flex items-center justify-between">
          <div className="text-sm text-gray-600">
            <strong>{selected.size}</strong> contrat(s) sélectionné(s)
          </div>
          <div className="flex gap-3">
            <button onClick={calculer} disabled={calculating || annee > anneeCourante} className="btn-secondary">
              {calculating ? '⏳ Calcul...' : '🧮 Calculer les montants'}
            </button>
            <button onClick={emettre} disabled={emitting || annee > anneeCourante} className="btn-primary">
              {emitting ? '⏳ Émission...' : `🚀 Émettre ${selected.size} facture(s)`}
            </button>
          </div>
        </div>
      )}

      {/* Résultat */}
      {resultat && (
        <div className="card bg-gray-50 space-y-2 text-sm">
          <div className="font-semibold">Résultat d'émission</div>
          <div className="flex gap-6">
            <span>Traités : <strong>{resultat.traites}</strong></span>
            <span className="text-green-700">Émises : <strong>{resultat.emises}</strong></span>
            {resultat.erreurs > 0 && <span className="text-red-600">Erreurs : <strong>{resultat.erreurs}</strong></span>}
          </div>
          {resultat.resultats?.filter(r => !r.succes).map((r, i) => (
            <div key={i} className="text-red-600">❌ {r.erreur}</div>
          ))}
        </div>
      )}
    </div>
  );
}
