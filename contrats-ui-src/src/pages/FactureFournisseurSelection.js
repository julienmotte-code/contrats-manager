import React, { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
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

const formatQte = (q) => {
  if (q === null || q === undefined) return '-';
  const n = typeof q === 'string' ? parseFloat(q) : q;
  if (Number.isNaN(n)) return '-';
  return n.toLocaleString('fr-FR', { maximumFractionDigits: 3 });
};

const formatDate = (d) => {
  if (!d) return '-';
  try {
    return format(new Date(d + 'T12:00:00'), 'd MMM yyyy', { locale: fr });
  } catch {
    return d;
  }
};

const ligneKey = (idBl, ligneIndex) => `${idBl}_${ligneIndex}`;

// Normalise pour la recherche : sans accent, en minuscules.
const normalise = (s) => (s || '')
  .toString()
  .toLocaleLowerCase('fr-FR')
  .normalize('NFD')
  .replace(/[̀-ͯ]/g, '');

export default function FactureFournisseurSelection() {
  const navigate = useNavigate();
  const [groupes, setGroupes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  // Map { key -> { ligne, id_bl, id_fournisseur } }
  const [selection, setSelection] = useState(new Map());
  const [creating, setCreating] = useState(false);
  // Filtre local (sans appel réseau)
  const [filtre, setFiltre] = useState('');

  const chargerFacturables = (forceRefresh = false) => {
    if (forceRefresh) setRefreshing(true); else setLoading(true);
    return facturesFournisseursAPI.facturables(
      forceRefresh ? { force_refresh: true } : undefined
    )
      .then(r => {
        setGroupes(r.data || []);
        setError(null);
        if (forceRefresh) toast.success('Liste rafraîchie depuis Karlia');
      })
      .catch(e => {
        console.error(e);
        const msg = e.response?.data?.detail || 'Erreur de chargement des facturables';
        setError(msg);
        toast.error(msg);
      })
      .finally(() => { setLoading(false); setRefreshing(false); });
  };

  useEffect(() => { chargerFacturables(false); }, []);

  // Fournisseur actuellement « verrouillé » par la sélection (mono-fournisseur)
  const fournisseurVerrouille = useMemo(() => {
    if (selection.size === 0) return null;
    const first = selection.values().next().value;
    return first.id_fournisseur;
  }, [selection]);

  // Filtrage LOCAL sur le nom du fournisseur (aucun appel réseau).
  // Note : on ne filtre PAS sur un nom de client/affaire car la réponse
  // /facturables ne contient pas de nom lisible (seul un id_opportunity
  // numérique existe côté Karlia, non propagé pour l'instant).
  const groupesAffiches = useMemo(() => {
    const q = normalise(filtre).trim();
    if (!q) return groupes;
    return groupes.filter(g => normalise(g.nom_fournisseur).includes(q));
  }, [groupes, filtre]);

  const toggleLigne = (idFournisseur, idBl, ligne) => {
    const key = ligneKey(idBl, ligne.ligne_index);
    setSelection(prev => {
      const next = new Map(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.set(key, { ligne, id_bl: idBl, id_fournisseur: idFournisseur });
      }
      return next;
    });
  };

  const toggleBR = (idFournisseur, br, allSelected) => {
    setSelection(prev => {
      const next = new Map(prev);
      br.lignes.forEach(l => {
        const k = ligneKey(br.id_bl, l.ligne_index);
        if (allSelected) {
          next.delete(k);
        } else {
          next.set(k, { ligne: l, id_bl: br.id_bl, id_fournisseur: idFournisseur });
        }
      });
      return next;
    });
  };

  const creer = async () => {
    if (selection.size === 0) {
      toast.error('Sélectionnez au moins une ligne');
      return;
    }
    const idFournisseur = fournisseurVerrouille;
    const lignes = Array.from(selection.values()).map(({ ligne, id_bl }) => ({
      id_bl_karlia: id_bl,
      ligne_index: ligne.ligne_index,
      id_product: ligne.id_product ?? null,
      designation: ligne.designation,
      reference: ligne.reference || null,
      quantite: parseFloat(ligne.quantite_restante),
      prix_unitaire_ht: parseFloat(ligne.prix_unitaire_ht),
      id_vat: ligne.id_vat || null,
    }));

    setCreating(true);
    try {
      const r = await facturesFournisseursAPI.creer({ id_fournisseur: idFournisseur, lignes });
      toast.success('Brouillon créé');
      navigate(`/factures-fournisseurs/${r.data.id}`);
    } catch (e) {
      console.error(e);
      toast.error(e.response?.data?.detail || 'Erreur de création');
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Nouvelle facture fournisseur</h1>
          <p className="text-gray-500 text-sm mt-1">
            Sélectionnez les lignes des bons de réception à facturer
          </p>
        </div>
        <button onClick={() => navigate('/factures-fournisseurs')} className="btn-secondary">
          ← Retour
        </button>
      </div>

      <div className="bg-blue-50 border border-blue-200 rounded-lg px-4 py-3 text-sm text-blue-800">
        ℹ️ Une facture fournisseur ne peut concerner qu'un <strong>seul fournisseur</strong>.
        Dès qu'une ligne est sélectionnée, les autres fournisseurs sont désactivés.
      </div>

      {/* Barre de filtre + bouton rafraîchir */}
      <div className="card flex flex-col md:flex-row gap-3 items-stretch md:items-center">
        <div className="flex-1">
          <label className="label">Filtrer par fournisseur</label>
          <input
            type="text"
            className="input"
            placeholder="Nom du fournisseur (filtrage local, instantané)"
            value={filtre}
            onChange={e => setFiltre(e.target.value)}
            disabled={loading}
          />
        </div>
        <div className="flex flex-col">
          <label className="label invisible">.</label>
          <button
            onClick={() => chargerFacturables(true)}
            disabled={loading || refreshing}
            className="btn-secondary whitespace-nowrap"
            title="Rappelle Karlia (catalogue + bons de réception). À utiliser quand Karlia a été modifié."
          >
            {refreshing ? '⏳ Rafraîchissement...' : '🔄 Rafraîchir depuis Karlia'}
          </button>
        </div>
      </div>

      {loading ? (
        <div className="text-center text-gray-400 py-8">Chargement des bons de réception facturables...</div>
      ) : error ? (
        <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-800">
          ❌ {error}
        </div>
      ) : groupes.length === 0 ? (
        <div className="text-center text-gray-400 py-12">
          Aucun bon de réception facturable. Tous les BR ont déjà été facturés.
        </div>
      ) : groupesAffiches.length === 0 ? (
        <div className="text-center text-gray-400 py-12">
          Aucun fournisseur ne correspond à « {filtre} ».
          <div className="mt-2">
            <button onClick={() => setFiltre('')} className="text-blue-600 hover:underline text-sm">
              Effacer le filtre
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-5">
          {groupesAffiches.map(g => {
            const disabled = fournisseurVerrouille !== null && fournisseurVerrouille !== g.id_fournisseur;
            return (
              <div
                key={g.id_fournisseur}
                className={`card ${disabled ? 'opacity-50' : ''}`}
              >
                <div className="flex items-center justify-between mb-3 pb-3 border-b">
                  <div>
                    <h2 className="text-lg font-semibold text-gray-900">
                      🏢 {g.nom_fournisseur || `Fournisseur #${g.id_fournisseur}`}
                    </h2>
                    <p className="text-xs text-gray-500">
                      id Karlia : {g.id_fournisseur} — {g.bons_reception.length} BR facturable(s)
                    </p>
                  </div>
                  {disabled && (
                    <span className="text-xs text-orange-700 bg-orange-100 px-2 py-1 rounded">
                      🔒 Désactivé : autre fournisseur sélectionné
                    </span>
                  )}
                </div>

                {g.bons_reception.map(br => {
                  const allSelected = br.lignes.every(l => selection.has(ligneKey(br.id_bl, l.ligne_index)));
                  const someSelected = br.lignes.some(l => selection.has(ligneKey(br.id_bl, l.ligne_index)));
                  return (
                    <div key={br.id_bl} className="mt-4 first:mt-0">
                      <div className="flex items-center gap-2 mb-2">
                        <input
                          type="checkbox"
                          disabled={disabled}
                          checked={allSelected}
                          ref={el => { if (el) el.indeterminate = !allSelected && someSelected; }}
                          onChange={() => toggleBR(g.id_fournisseur, br, allSelected)}
                        />
                        <span className="font-medium text-sm">
                          📦 BR {br.numero || `#${br.id_bl}`}
                        </span>
                        <span className="text-xs text-gray-500">— {formatDate(br.date)}</span>
                      </div>
                      <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                          <thead>
                            <tr className="text-left text-gray-500 border-b text-xs">
                              <th className="pb-2 w-8"></th>
                              <th className="pb-2">Désignation</th>
                              <th className="pb-2">Référence</th>
                              <th className="pb-2 text-right">Livré</th>
                              <th className="pb-2 text-right">Déjà facturé</th>
                              <th className="pb-2 text-right">Restant</th>
                              <th className="pb-2 text-right">PU HT</th>
                              <th className="pb-2 text-right">Total restant HT</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y">
                            {br.lignes.map(l => {
                              const key = ligneKey(br.id_bl, l.ligne_index);
                              const selected = selection.has(key);
                              const totalRestant = parseFloat(l.quantite_restante) * parseFloat(l.prix_unitaire_ht);
                              return (
                                <tr key={key} className={selected ? 'bg-blue-50' : ''}>
                                  <td className="py-2">
                                    <input
                                      type="checkbox"
                                      disabled={disabled}
                                      checked={selected}
                                      onChange={() => toggleLigne(g.id_fournisseur, br.id_bl, l)}
                                    />
                                  </td>
                                  <td className="py-2">{l.designation}</td>
                                  <td className="py-2 text-gray-600 text-xs">{l.reference || '-'}</td>
                                  <td className="py-2 text-right font-mono">{formatQte(l.quantite_livree)}</td>
                                  <td className="py-2 text-right font-mono">
                                    {parseFloat(l.quantite_deja_facturee) > 0 ? (
                                      <span className="text-orange-600">{formatQte(l.quantite_deja_facturee)}</span>
                                    ) : (
                                      <span className="text-gray-400">0</span>
                                    )}
                                  </td>
                                  <td className="py-2 text-right font-mono font-medium">
                                    {formatQte(l.quantite_restante)}
                                  </td>
                                  <td className="py-2 text-right font-mono">{formatMontant(l.prix_unitaire_ht)}</td>
                                  <td className="py-2 text-right font-mono">{formatMontant(totalRestant)}</td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
      )}

      {/* Barre d'action sticky */}
      {selection.size > 0 && (
        <div className="sticky bottom-4 bg-white border border-gray-200 rounded-xl shadow-lg px-6 py-4 flex items-center justify-between">
          <div className="text-sm text-gray-600">
            <strong>{selection.size}</strong> ligne(s) sélectionnée(s)
            {' • '}
            Fournisseur :{' '}
            <strong>
              {groupes.find(g => g.id_fournisseur === fournisseurVerrouille)?.nom_fournisseur
                || `#${fournisseurVerrouille}`}
            </strong>
          </div>
          <div className="flex gap-3">
            <button onClick={() => setSelection(new Map())} className="btn-secondary">
              ☐ Tout désélectionner
            </button>
            <button onClick={creer} disabled={creating} className="btn-primary">
              {creating ? '⏳ Création...' : '✅ Créer le brouillon'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
