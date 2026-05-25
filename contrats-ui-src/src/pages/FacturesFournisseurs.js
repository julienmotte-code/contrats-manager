import React, { useState, useEffect, useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { format } from 'date-fns';
import { fr } from 'date-fns/locale';
import toast from 'react-hot-toast';
import { facturesFournisseursAPI } from '../services/api';

const formatMontant = (m) => {
  if (m === null || m === undefined || m === '') return '-';
  const n = typeof m === 'string' ? parseFloat(m) : m;
  if (Number.isNaN(n)) return '-';
  return new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR' }).format(n);
};

const formatDate = (d) => {
  if (!d) return '-';
  try {
    return format(new Date(d + 'T12:00:00'), 'd MMM yyyy', { locale: fr });
  } catch {
    return d;
  }
};

const formatDateTime = (d) => {
  if (!d) return '-';
  try {
    return format(new Date(d), 'd MMM yyyy HH:mm', { locale: fr });
  } catch {
    return d;
  }
};

export default function FacturesFournisseurs() {
  const navigate = useNavigate();
  const [factures, setFactures] = useState([]);
  const [loading, setLoading] = useState(false);
  const [filtreStatut, setFiltreStatut] = useState('');

  const charger = useCallback(() => {
    setLoading(true);
    const params = filtreStatut ? { statut: filtreStatut } : {};
    facturesFournisseursAPI.liste(params)
      .then(r => setFactures(r.data || []))
      .catch(e => {
        console.error(e);
        toast.error(e.response?.data?.detail || 'Erreur de chargement');
      })
      .finally(() => setLoading(false));
  }, [filtreStatut]);

  useEffect(() => { charger(); }, [charger]);

  const supprimer = async (f) => {
    if (f.statut !== 'brouillon') return;
    if (!window.confirm(`Supprimer le brouillon ${f.reference || `#${f.id}`} ?`)) return;
    try {
      await facturesFournisseursAPI.supprimer(f.id);
      toast.success('Brouillon supprimé');
      charger();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Erreur de suppression');
    }
  };

  const nbBrouillons = factures.filter(f => f.statut === 'brouillon').length;
  const nbValidees = factures.filter(f => f.statut === 'validee').length;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Factures fournisseurs</h1>
          <p className="text-gray-500 text-sm mt-1">
            Construction des factures fournisseurs depuis les bons de réception Karlia
          </p>
        </div>
        <button
          onClick={() => navigate('/factures-fournisseurs/nouvelle')}
          className="btn-primary"
        >
          ➕ Nouvelle facture fournisseur
        </button>
      </div>

      {/* Filtre statut */}
      <div className="card flex flex-wrap gap-4 items-end">
        <div>
          <label className="label">Statut</label>
          <select
            className="input w-56"
            value={filtreStatut}
            onChange={e => setFiltreStatut(e.target.value)}
          >
            <option value="">Tous</option>
            <option value="brouillon">Brouillons</option>
            <option value="validee">Validées</option>
          </select>
        </div>
        <div className="text-sm text-gray-600 ml-auto flex gap-4">
          <span>📝 Brouillons : <strong>{nbBrouillons}</strong></span>
          <span>✅ Validées : <strong>{nbValidees}</strong></span>
        </div>
      </div>

      {/* Tableau */}
      {loading ? (
        <div className="text-center text-gray-400 py-8">Chargement...</div>
      ) : factures.length === 0 ? (
        <div className="text-center text-gray-400 py-12">
          Aucune facture fournisseur {filtreStatut ? `(${filtreStatut})` : ''}.
          {' '}
          <Link to="/factures-fournisseurs/nouvelle" className="text-blue-600 underline">
            Créer la première
          </Link>
        </div>
      ) : (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-gray-500 border-b">
                <th className="pb-3">Référence</th>
                <th className="pb-3">Fournisseur</th>
                <th className="pb-3">Date facture</th>
                <th className="pb-3 text-right">Lignes</th>
                <th className="pb-3 text-right">Total HT</th>
                <th className="pb-3 text-right">Total TVA</th>
                <th className="pb-3 text-right">Total TTC</th>
                <th className="pb-3">Statut</th>
                <th className="pb-3">Créée le</th>
                <th className="pb-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {factures.map(f => (
                <tr key={f.id} className="hover:bg-gray-50">
                  <td className="py-3 font-medium">{f.reference || <span className="text-gray-400">—</span>}</td>
                  <td className="py-3 text-gray-700">
                    {f.nom_fournisseur || <span className="text-gray-400">#{f.id_fournisseur_karlia}</span>}
                  </td>
                  <td className="py-3">{formatDate(f.date_facture)}</td>
                  <td className="py-3 text-right">{f.nb_lignes}</td>
                  <td className="py-3 text-right font-mono">{formatMontant(f.total_ht)}</td>
                  <td className="py-3 text-right font-mono">{formatMontant(f.total_tva)}</td>
                  <td className="py-3 text-right font-mono font-medium">{formatMontant(f.total_ttc)}</td>
                  <td className="py-3">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                      f.statut === 'validee' ? 'bg-green-100 text-green-800' :
                      f.statut === 'brouillon' ? 'bg-gray-100 text-gray-700' :
                      'bg-orange-100 text-orange-800'
                    }`}>{f.statut}</span>
                  </td>
                  <td className="py-3 text-xs text-gray-500">{formatDateTime(f.created_at)}</td>
                  <td className="py-3 text-right space-x-2">
                    <button
                      onClick={() => navigate(`/factures-fournisseurs/${f.id}`)}
                      className="text-blue-600 hover:underline text-sm"
                    >
                      {f.statut === 'brouillon' ? '✏️ Éditer' : '👁️ Voir'}
                    </button>
                    {f.statut === 'brouillon' && (
                      <button
                        onClick={() => supprimer(f)}
                        className="text-red-600 hover:underline text-sm"
                      >
                        🗑️ Supprimer
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
