import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { format } from 'date-fns';
import { fr } from 'date-fns/locale';
import toast from 'react-hot-toast';
import { facturesFournisseursAPI } from '../services/api';

// Mapping TVA Karlia (cohérent avec backend : 1=20, 2=10, 3=5.5, 4=0)
const TVA_TAUX = { '1': 20, '2': 10, '3': 5.5, '4': 0 };

const tauxPour = (idVat) => {
  if (idVat === null || idVat === undefined) return 20;
  return TVA_TAUX[String(idVat)] ?? 20;
};

const formatMontant = (m) => {
  const n = typeof m === 'string' ? parseFloat(m) : m;
  if (m === null || m === undefined || Number.isNaN(n)) return '-';
  return new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR' }).format(n);
};

const formatQte = (q) => {
  const n = typeof q === 'string' ? parseFloat(q) : q;
  if (q === null || q === undefined || Number.isNaN(n)) return '-';
  return n.toLocaleString('fr-FR', { maximumFractionDigits: 3 });
};

const formatDateTime = (d) => {
  if (!d) return '-';
  try {
    return format(new Date(d), 'd MMM yyyy HH:mm', { locale: fr });
  } catch {
    return d;
  }
};

const toNum = (v) => {
  if (v === null || v === undefined || v === '') return 0;
  const n = typeof v === 'string' ? parseFloat(v) : v;
  return Number.isNaN(n) ? 0 : n;
};

const ligneKey = (idBl, ligneIndex) => `${idBl}_${ligneIndex}`;

export default function FactureFournisseurEdition() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [facture, setFacture] = useState(null);
  const [lignes, setLignes] = useState([]);
  // Snapshot des bornes max par ligne, lu depuis GET /{id} (champ
  // quantite_max_facturable persisté à la création du brouillon).
  // Remplace l'ancien rappel à /facturables qui coûtait ~10 s.
  const [bornesMax, setBornesMax] = useState({});
  const [dateFacture, setDateFacture] = useState('');
  const [reference, setReference] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [validating, setValidating] = useState(false);
  const [error, setError] = useState(null);

  const enLectureSeule = facture?.statut === 'validee';

  const charger = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await facturesFournisseursAPI.detail(id);
      const f = r.data;
      setFacture(f);
      setDateFacture(f.date_facture || '');
      setReference(f.reference || '');
      const lignesEtat = (f.lignes || []).map(l => ({
        id_bl_karlia: l.id_bl_karlia,
        ligne_index: l.ligne_index,
        id_product: l.id_product_karlia ?? null,
        designation: l.designation,
        reference: l.reference || '',
        quantite: String(l.quantite),
        prix_unitaire_ht: String(l.prix_unitaire_ht),
        id_vat: l.id_vat_karlia || null,
      }));
      setLignes(lignesEtat);

      // Bornes max : on lit la colonne persistée quantite_max_facturable
      // pour chaque ligne. Plus aucun appel /facturables au mount.
      const map = {};
      (f.lignes || []).forEach(l => {
        if (l.quantite_max_facturable !== null && l.quantite_max_facturable !== undefined) {
          map[ligneKey(l.id_bl_karlia, l.ligne_index)] = toNum(l.quantite_max_facturable);
        }
      });
      setBornesMax(map);
    } catch (e) {
      console.error(e);
      const msg = e.response?.data?.detail || 'Erreur de chargement';
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { charger(); }, [charger]);

  // Borne max par ligne :
  // - en lecture seule (validée) : peu importe, l'input est disabled.
  // - en brouillon : utilise quantite_max_facturable persistée.
  // - fallback (ligne créée avant migration 0004 → borneMax absent) :
  //   on autorise au moins la quantité actuelle (sécurité — le backend
  //   revalidera à la validation de toute façon).
  const maxQuantitePour = useCallback((l) => {
    const k = ligneKey(l.id_bl_karlia, l.ligne_index);
    const borne = bornesMax[k];
    if (borne === undefined) {
      return Math.max(toNum(l.quantite), 0);
    }
    return borne;
  }, [bornesMax]);

  const setLigne = (idx, patch) => {
    setLignes(prev => prev.map((l, i) => (i === idx ? { ...l, ...patch } : l)));
  };

  const supprimerLigne = (idx) => {
    if (lignes.length <= 1) {
      toast.error('Une facture doit contenir au moins une ligne. Supprimez plutôt le brouillon.');
      return;
    }
    setLignes(prev => prev.filter((_, i) => i !== idx));
  };

  // Recalcul EN DIRECT des totaux
  const totaux = useMemo(() => {
    let ht = 0;
    let tva = 0;
    lignes.forEach(l => {
      const qte = toNum(l.quantite);
      const pu = toNum(l.prix_unitaire_ht);
      const total = qte * pu;
      ht += total;
      tva += total * tauxPour(l.id_vat) / 100;
    });
    return { ht, tva, ttc: ht + tva };
  }, [lignes]);

  // Erreurs de garde-fou par ligne (front)
  const erreursLignes = useMemo(() => {
    const errs = {};
    lignes.forEach((l, idx) => {
      const qte = toNum(l.quantite);
      if (qte <= 0) {
        errs[idx] = 'La quantité doit être strictement positive';
        return;
      }
      const max = maxQuantitePour(l);
      if (qte > max + 0.000001) {
        errs[idx] = `Dépasse la quantité restante (${formatQte(max)})`;
      }
    });
    return errs;
  }, [lignes, maxQuantitePour]);

  const hasErreurs = Object.keys(erreursLignes).length > 0;

  const construireLignesPayload = () => lignes.map(l => ({
    id_bl_karlia: l.id_bl_karlia,
    ligne_index: l.ligne_index,
    id_product: l.id_product ?? null,
    designation: l.designation,
    reference: l.reference || null,
    quantite: toNum(l.quantite),
    prix_unitaire_ht: toNum(l.prix_unitaire_ht),
    id_vat: l.id_vat || null,
  }));

  const enregistrer = async () => {
    if (hasErreurs) {
      toast.error('Corrigez les erreurs avant de sauvegarder');
      return;
    }
    setSaving(true);
    try {
      // PUT ne modifie pas les en-têtes (date, ref) côté backend actuel ;
      // on ne renvoie que les lignes (signature backend FactureUpdateRequest).
      const r = await facturesFournisseursAPI.modifier(id, { lignes: construireLignesPayload() });
      toast.success('Brouillon enregistré');
      setFacture(r.data);
      // Rafraîchir les bornes après PUT (le service en a posé de nouvelles
      // sur les lignes recréées).
      const map = {};
      (r.data.lignes || []).forEach(l => {
        if (l.quantite_max_facturable !== null && l.quantite_max_facturable !== undefined) {
          map[ligneKey(l.id_bl_karlia, l.ligne_index)] = toNum(l.quantite_max_facturable);
        }
      });
      setBornesMax(map);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Erreur de sauvegarde');
    } finally {
      setSaving(false);
    }
  };

  const valider = async () => {
    if (hasErreurs) {
      toast.error('Corrigez les erreurs avant de valider');
      return;
    }
    if (!window.confirm(
      `Valider la facture ${reference || `#${id}`} ?\n\n`
      + `Une fois validée, la facture sera figée (lecture seule) et `
      + `les quantités décompteront les bons de réception correspondants.`
    )) return;
    setValidating(true);
    try {
      // Sauvegarde implicite des dernières modifs des lignes avant validation.
      await facturesFournisseursAPI.modifier(id, { lignes: construireLignesPayload() });
      const r = await facturesFournisseursAPI.valider(id);
      toast.success('Facture validée');
      setFacture(r.data);
      // Mise à jour de l'état local : tout passe en lecture seule.
      const lignesEtat = (r.data.lignes || []).map(l => ({
        id_bl_karlia: l.id_bl_karlia,
        ligne_index: l.ligne_index,
        id_product: l.id_product_karlia ?? null,
        designation: l.designation,
        reference: l.reference || '',
        quantite: String(l.quantite),
        prix_unitaire_ht: String(l.prix_unitaire_ht),
        id_vat: l.id_vat_karlia || null,
      }));
      setLignes(lignesEtat);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Erreur de validation');
    } finally {
      setValidating(false);
    }
  };

  if (loading) {
    return <div className="text-center text-gray-400 py-12">Chargement de la facture...</div>;
  }
  if (error) {
    return (
      <div className="space-y-4">
        <button onClick={() => navigate('/factures-fournisseurs')} className="btn-secondary">
          ← Retour
        </button>
        <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-800">
          ❌ {error}
        </div>
      </div>
    );
  }
  if (!facture) return null;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">
            Facture fournisseur {reference || `#${facture.id}`}
          </h1>
          <p className="text-gray-500 text-sm mt-1">
            🏢 {facture.nom_fournisseur || `Fournisseur #${facture.id_fournisseur_karlia}`}
            {' • '}
            <span className={`px-2 py-0.5 rounded text-xs font-medium ${
              facture.statut === 'validee' ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-700'
            }`}>{facture.statut}</span>
            {' • Créée le '}{formatDateTime(facture.created_at)}
          </p>
        </div>
        <button onClick={() => navigate('/factures-fournisseurs')} className="btn-secondary">
          ← Retour à la liste
        </button>
      </div>

      {enLectureSeule && (
        <div className="bg-green-50 border border-green-200 rounded-lg px-4 py-3 text-sm text-green-800">
          🔒 Cette facture est <strong>validée</strong> et figée. Toute modification est désactivée.
        </div>
      )}

      {/* En-tête éditable */}
      <div className="card grid grid-cols-1 md:grid-cols-3 gap-4">
        <div>
          <label className="label">Date de facture</label>
          <input
            type="date"
            className="input"
            value={dateFacture}
            onChange={e => setDateFacture(e.target.value)}
            disabled={enLectureSeule}
          />
        </div>
        <div>
          <label className="label">Référence</label>
          <input
            type="text"
            className="input"
            value={reference}
            onChange={e => setReference(e.target.value)}
            placeholder="Numéro/référence interne"
            disabled={enLectureSeule}
          />
        </div>
        <div>
          <label className="label">Fournisseur</label>
          <div className="input bg-gray-50 cursor-not-allowed">
            {facture.nom_fournisseur || `#${facture.id_fournisseur_karlia}`}
          </div>
        </div>
      </div>

      {/* Tableau lignes */}
      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-gray-500 border-b">
              <th className="pb-3">Désignation</th>
              <th className="pb-3">Référence</th>
              <th className="pb-3">BR</th>
              <th className="pb-3 text-right">Quantité</th>
              <th className="pb-3 text-right">Max</th>
              <th className="pb-3 text-right">PU HT</th>
              <th className="pb-3">TVA</th>
              <th className="pb-3 text-right">Total HT</th>
              <th className="pb-3 text-right">Total TTC</th>
              {!enLectureSeule && <th className="pb-3"></th>}
            </tr>
          </thead>
          <tbody className="divide-y">
            {lignes.map((l, idx) => {
              const qte = toNum(l.quantite);
              const pu = toNum(l.prix_unitaire_ht);
              const totalHt = qte * pu;
              const totalTtc = totalHt * (1 + tauxPour(l.id_vat) / 100);
              const max = maxQuantitePour(l);
              const err = erreursLignes[idx];
              return (
                <tr key={`${l.id_bl_karlia}_${l.ligne_index}`} className={err ? 'bg-red-50' : ''}>
                  <td className="py-3">{l.designation}</td>
                  <td className="py-3 text-xs text-gray-600">{l.reference || '-'}</td>
                  <td className="py-3 text-xs text-gray-500">
                    #{l.id_bl_karlia}/{l.ligne_index}
                  </td>
                  <td className="py-3 text-right">
                    <input
                      type="number"
                      className={`input text-right w-24 ${err ? 'border-red-400' : ''}`}
                      value={l.quantite}
                      step="0.001"
                      min="0"
                      onChange={e => setLigne(idx, { quantite: e.target.value })}
                      disabled={enLectureSeule}
                    />
                    {err && <div className="text-xs text-red-600 mt-1">{err}</div>}
                  </td>
                  <td className="py-3 text-right font-mono text-xs text-gray-500">
                    {formatQte(max)}
                  </td>
                  <td className="py-3 text-right">
                    <input
                      type="number"
                      className="input text-right w-24"
                      value={l.prix_unitaire_ht}
                      step="0.0001"
                      min="0"
                      onChange={e => setLigne(idx, { prix_unitaire_ht: e.target.value })}
                      disabled={enLectureSeule}
                    />
                  </td>
                  <td className="py-3">
                    <span className="text-xs text-gray-600">
                      {tauxPour(l.id_vat).toLocaleString('fr-FR', { maximumFractionDigits: 1 })} %
                    </span>
                  </td>
                  <td className="py-3 text-right font-mono">{formatMontant(totalHt)}</td>
                  <td className="py-3 text-right font-mono font-medium">{formatMontant(totalTtc)}</td>
                  {!enLectureSeule && (
                    <td className="py-3 text-right">
                      <button
                        onClick={() => supprimerLigne(idx)}
                        className="text-red-600 hover:underline text-xs"
                        title="Retirer la ligne"
                      >
                        🗑️
                      </button>
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
          <tfoot className="border-t-2 border-gray-200">
            <tr>
              <td colSpan={enLectureSeule ? 7 : 7} className="pt-3 text-right text-sm text-gray-600">
                Total HT
              </td>
              <td className="pt-3 text-right font-mono font-medium">{formatMontant(totaux.ht)}</td>
              <td colSpan={enLectureSeule ? 1 : 2}></td>
            </tr>
            <tr>
              <td colSpan={7} className="text-right text-sm text-gray-600">Total TVA</td>
              <td className="text-right font-mono">{formatMontant(totaux.tva)}</td>
              <td colSpan={enLectureSeule ? 1 : 2}></td>
            </tr>
            <tr>
              <td colSpan={7} className="pb-3 text-right text-sm font-semibold">Total TTC</td>
              <td className="pb-3 text-right font-mono font-bold text-base">{formatMontant(totaux.ttc)}</td>
              <td colSpan={enLectureSeule ? 1 : 2}></td>
            </tr>
          </tfoot>
        </table>
      </div>

      {/* Actions */}
      {!enLectureSeule && (
        <div className="sticky bottom-4 bg-white border border-gray-200 rounded-xl shadow-lg px-6 py-4 flex items-center justify-between">
          <div className="text-sm text-gray-600">
            {hasErreurs ? (
              <span className="text-red-600">⚠️ {Object.keys(erreursLignes).length} ligne(s) en erreur</span>
            ) : (
              <span>✅ Prêt à enregistrer</span>
            )}
          </div>
          <div className="flex gap-3">
            <button
              onClick={enregistrer}
              disabled={saving || validating || hasErreurs}
              className="btn-secondary"
            >
              {saving ? '⏳ Enregistrement...' : '💾 Enregistrer'}
            </button>
            <button
              onClick={valider}
              disabled={saving || validating || hasErreurs}
              className="btn-primary"
            >
              {validating ? '⏳ Validation...' : '✅ Valider la facture'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
