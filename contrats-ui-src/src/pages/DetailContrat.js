import React, { useState, useEffect } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { contratsAPI } from '../services/api';
import api from '../services/api';
import { format } from 'date-fns';
import toast from 'react-hot-toast';

function StatutBadge({ statut }) {
  const map = { EN_COURS: <span className="badge-green">En cours</span>, A_RENOUVELER: <span className="badge-orange">À renouveler</span>, TERMINE: <span className="badge-gray">Terminé</span>, BROUILLON: <span className="badge-blue">Brouillon</span> };
  return map[statut] || <span className="badge-gray">{statut}</span>;
}

export default function DetailContrat() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [contrat, setContrat] = useState(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [showTerminer, setShowTerminer] = useState(false);
  const [motifFin, setMotifFin] = useState('');
  const [showRenouveler, setShowRenouveler] = useState(false);
  const [typeRenouvellement, setTypeRenouvellement] = useState('SPONTANE');
  const [prorataValidating, setProrataValidating] = useState(false);
  const [docs, setDocs] = useState([]);
  const [generatingDoc, setGeneratingDoc] = useState(false);

  useEffect(() => {
    contratsAPI.detail(id).then(r => setContrat(r.data)).catch(() => toast.error('Contrat introuvable')).finally(() => setLoading(false));
    api.get(`/api/documents/contrat/${id}`).then(r => setDocs(r.data.data || [])).catch(() => {});
  }, [id]);

  const supprimer = async () => {
    if (!window.confirm('Supprimer définitivement ce contrat brouillon ?')) return;
    setActionLoading(true);
    try { await api.delete(`/api/contrats/${id}`); toast.success('Contrat supprimé'); navigate('/contrats'); }
    catch (e) { toast.error(e.response?.data?.detail || 'Erreur suppression'); }
    finally { setActionLoading(false); }
  };

  const validerProrata = async () => {
    setProrataValidating(true);
    try { await api.put(`/api/contrats/${id}`, { prorate_validated: true }); toast.success('Prorata validé'); setContrat(c => ({ ...c, prorate_validated: true })); }
    catch (e) { toast.error(e.response?.data?.detail || 'Erreur'); }
    finally { setProrataValidating(false); }
  };

  const valider = async () => {
    setActionLoading(true);
    try { await contratsAPI.valider(id); toast.success('Contrat validé'); setContrat(c => ({ ...c, statut: 'EN_COURS' })); }
    catch (e) { toast.error(e.response?.data?.detail || 'Erreur validation'); }
    finally { setActionLoading(false); }
  };

  const terminer = async () => {
    setActionLoading(true);
    try { await contratsAPI.terminer(id, motifFin); toast.success('Contrat terminé'); setContrat(c => ({ ...c, statut: 'TERMINE' })); setShowTerminer(false); }
    catch (e) { toast.error(e.response?.data?.detail || 'Erreur'); }
    finally { setActionLoading(false); }
  };

  const renouveler = async () => {
    setActionLoading(true);
    try {
      const r = await contratsAPI.renouveler(id, { type_renouvellement: typeRenouvellement });
      toast.success(r.data.message); setShowRenouveler(false);
      if (r.data.nouveau_contrat_id) navigate(`/contrats/${r.data.nouveau_contrat_id}`);
      else contratsAPI.detail(id).then(r => setContrat(r.data));
    } catch (e) { toast.error(e.response?.data?.detail || 'Erreur'); }
    finally { setActionLoading(false); }
  };

  const telechargerDoc = async (docId, nomFichier) => {
    const token = localStorage.getItem('token');
    const resp = await fetch(`/api/documents/telecharger/${docId}`, { headers: { Authorization: `Bearer ${token}` } });
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = nomFichier; a.click();
    URL.revokeObjectURL(url);
  };

  const genererDocument = async () => {
    setGeneratingDoc(true);
    try {
      const r = await api.post(`/api/documents/generer/${id}`);
      const { document_id, nom_fichier } = r.data;
      const liste = await api.get(`/api/documents/contrat/${id}`);
      setDocs(liste.data.data || []);
      await telechargerDoc(document_id, nom_fichier);
      toast.success('Contrat généré et téléchargé');
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Erreur lors de la génération');
    } finally {
      setGeneratingDoc(false);
    }
  };

  if (loading) return <div className="flex items-center justify-center h-64 text-gray-400">Chargement...</div>;
  if (!contrat) return <div className="text-center py-12 text-gray-400">Contrat introuvable</div>;

  const articlePrincipal = contrat.articles?.find(a => a.rang === 0);
  const articlesAnnexe = contrat.articles?.filter(a => a.rang > 0) || [];

  return (
    <div className="space-y-6 max-w-4xl">
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-3"><h1 className="text-2xl font-bold text-gray-900">{contrat.numero_contrat}</h1><StatutBadge statut={contrat.statut} /><span className="badge-gray">{contrat.type_contrat}</span></div>
          <p className="text-gray-500 text-sm mt-1">{contrat.client_nom} — {contrat.client_numero}</p>
        </div>
        <div className="flex gap-2">
          <Link to="/contrats" className="btn-secondary text-sm">← Retour</Link>
          {contrat.statut === 'BROUILLON' && <Link to={`/contrats/${id}/modifier`} className="btn-secondary text-sm">✏️ Modifier</Link>}
          {contrat.statut === 'BROUILLON' && (<>
            <button onClick={supprimer} disabled={actionLoading} className="btn-danger text-sm">🗑️ Supprimer</button>
            {contrat.prorate_annee1 && !contrat.prorate_validated && (
              <button onClick={validerProrata} disabled={prorataValidating} className="btn-secondary text-sm">✅ Valider le prorata</button>
            )}
            <button onClick={valider} disabled={actionLoading || (contrat.prorate_annee1 && !contrat.prorate_validated)} className="btn-success text-sm"
              title={contrat.prorate_annee1 && !contrat.prorate_validated ? 'Validez d abord le prorata' : ''}>
              ✅ Valider le contrat
            </button>
          </>)}
          {contrat.statut === 'EN_COURS' && (<>
            <button onClick={() => setShowRenouveler(true)} className="btn-secondary text-sm">🔄 Renouveler</button>
            <button onClick={() => setShowTerminer(true)} className="btn-danger text-sm">🚫 Terminer</button>
          </>)}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="card space-y-3">
          <h2 className="font-semibold text-gray-900 border-b pb-2">📋 Informations</h2>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between"><span className="text-gray-500">Client</span><span className="font-medium">{contrat.client_nom}</span></div>
            <div className="flex justify-between"><span className="text-gray-500">N° client</span><span>{contrat.client_numero}</span></div>
            <div className="flex justify-between"><span className="text-gray-500">Début</span><span>{contrat.date_debut ? format(new Date(contrat.date_debut + 'T12:00:00'), 'dd/MM/yyyy') : '-'}</span></div>
            <div className="flex justify-between"><span className="text-gray-500">Fin</span><span>{contrat.date_fin ? format(new Date(contrat.date_fin + 'T12:00:00'), 'dd/MM/yyyy') : '-'}</span></div>
            <div className="flex justify-between"><span className="text-gray-500">Durée</span><span>{contrat.nombre_annees} an(s)</span></div>
          </div>
        </div>
        <div className="card space-y-3">
          <h2 className="font-semibold text-gray-900 border-b pb-2">💶 Montants</h2>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between"><span className="text-gray-500">Montant annuel HT</span><span className="font-bold text-lg">{contrat.montant_annuel_ht?.toLocaleString('fr-FR', { minimumFractionDigits: 2 })} €</span></div>
            {contrat.prorate_annee1 && (<>
              <div className="flex justify-between"><span className="text-gray-500">Prorata an 1</span><span className="font-medium text-orange-700">{contrat.prorate_montant_ht?.toLocaleString('fr-FR', { minimumFractionDigits: 2 })} €</span></div>
              <div className="flex justify-between"><span className="text-gray-500">Nb mois prorata</span><span>{contrat.prorate_nb_mois} mois</span></div>
              <div className="flex justify-between"><span className="text-gray-500">Prorata validé</span><span>{contrat.prorate_validated ? '✅ Oui' : '⚠️ Non'}</span></div>
            </>)}
          </div>
        </div>
      </div>

      <div className="card space-y-4">
        <h2 className="font-semibold text-gray-900 border-b pb-2">📦 Articles</h2>
        {articlePrincipal && <div className="bg-blue-50 border border-blue-200 rounded-lg p-3"><div className="text-xs font-medium text-blue-600 mb-1">Désignation principale</div><div className="font-medium text-blue-900">{articlePrincipal.designation}</div>{articlePrincipal.prix_unitaire_ht && <div className="text-sm text-blue-700 mt-1">{parseFloat(articlePrincipal.prix_unitaire_ht).toLocaleString('fr-FR', { minimumFractionDigits: 2 })} € HT</div>}</div>}
        {articlesAnnexe.length > 0 && (
          <table className="w-full text-sm">
            <thead className="bg-gray-50"><tr><th className="text-left px-3 py-2 text-gray-500">Désignation</th><th className="text-right px-3 py-2 text-gray-500">Prix HT</th><th className="text-right px-3 py-2 text-gray-500">Qté</th><th className="text-right px-3 py-2 text-gray-500">TVA</th></tr></thead>
            <tbody className="divide-y divide-gray-100">{articlesAnnexe.map(a => <tr key={a.rang}><td className="px-3 py-2">{a.designation}</td><td className="px-3 py-2 text-right">{a.prix_unitaire_ht ? `${parseFloat(a.prix_unitaire_ht).toLocaleString('fr-FR', { minimumFractionDigits: 2 })} €` : '-'}</td><td className="px-3 py-2 text-right">{a.quantite}</td><td className="px-3 py-2 text-right">{a.taux_tva}%</td></tr>)}</tbody>
          </table>
        )}
      </div>

      {contrat.plan_facturation?.length > 0 && (
        <div className="card space-y-4">
          <h2 className="font-semibold text-gray-900 border-b pb-2">💶 Plan de facturation</h2>
          <table className="w-full text-sm">
            <thead className="bg-gray-50"><tr><th className="text-left px-3 py-2 text-gray-500">N°</th><th className="text-left px-3 py-2 text-gray-500">Année</th><th className="text-left px-3 py-2 text-gray-500">Type</th><th className="text-left px-3 py-2 text-gray-500">Échéance</th><th className="text-right px-3 py-2 text-gray-500">Montant HT</th><th className="text-center px-3 py-2 text-gray-500">Statut</th><th className="text-left px-3 py-2 text-gray-500">Réf. Karlia</th></tr></thead>
            <tbody className="divide-y divide-gray-100">
              {contrat.plan_facturation.map(p => (
                <tr key={p.id} className="hover:bg-gray-50">
                  <td className="px-3 py-2 font-medium">{p.numero_facture}</td>
                  <td className="px-3 py-2">{p.annee_facturation}</td>
                  <td className="px-3 py-2">{p.type_facture === 'PRORATE' ? <span className="badge-orange">Prorata</span> : <span className="badge-blue">Annuelle</span>}</td>
                  <td className="px-3 py-2">{p.date_echeance ? p.date_echeance ? format(new Date(p.date_echeance + 'T12:00:00'), 'dd/MM/yyyy') : '-' : '-'}</td>
                  <td className="px-3 py-2 text-right font-medium">{(p.montant_ht_facture || p.montant_ht_prevu)?.toLocaleString('fr-FR', { minimumFractionDigits: 2 })} €</td>
                  <td className="px-3 py-2 text-center">{p.statut === 'EMISE' ? <span className="badge-green">Émise</span> : p.statut === 'ERREUR' ? <span className="badge-red">Erreur</span> : <span className="badge-gray">Planifiée</span>}</td>
                  <td className="px-3 py-2 text-xs text-gray-500">{p.facture_karlia_ref || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="card space-y-4">
        <div className="flex items-center justify-between border-b pb-2">
          <h2 className="font-semibold text-gray-900">📄 Contrat papier</h2>
          <button onClick={genererDocument} disabled={generatingDoc} className="btn-primary text-sm disabled:opacity-50">
            {generatingDoc ? '⟳ Génération...' : '📄 Générer le contrat Word'}
          </button>
        </div>
        {docs.length === 0 ? (
          <p className="text-sm text-gray-400 italic">Aucun contrat généré pour l'instant.</p>
        ) : (
          <div className="space-y-2">
            {docs.map(doc => (
              <div key={doc.id} className="flex items-center justify-between p-3 bg-gray-50 rounded-lg border border-gray-100">
                <div>
                  <p className="text-sm font-medium text-gray-700">{doc.nom_fichier}</p>
                  <p className="text-xs text-gray-400">
                    {doc.generated_at ? doc.generated_at ? format(new Date(doc.generated_at), 'dd/MM/yyyy') : '—' : '—'}
                    {doc.generated_by ? ` · par ${doc.generated_by}` : ''}
                  </p>
                </div>
                <button onClick={() => telechargerDoc(doc.id, doc.nom_fichier)} className="btn-secondary text-sm">
                  ⬇ Télécharger
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {showTerminer && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 w-full max-w-md space-y-4">
            <h3 className="font-bold text-gray-900 text-lg">🚫 Terminer le contrat</h3>
            <p className="text-gray-600 text-sm">Le contrat sera clôturé. Plus aucune facture ne sera émise.</p>
            <div><label className="label">Motif de fin</label><textarea className="input h-24 resize-none" placeholder="Départ client..." value={motifFin} onChange={e => setMotifFin(e.target.value)} /></div>
            <div className="flex gap-3"><button onClick={terminer} disabled={actionLoading} className="btn-danger flex-1">Confirmer</button><button onClick={() => setShowTerminer(false)} className="btn-secondary flex-1">Annuler</button></div>
          </div>
        </div>
      )}

      {showRenouveler && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 w-full max-w-md space-y-4">
            <h3 className="font-bold text-gray-900 text-lg">🔄 Renouveler le contrat</h3>
            <div className="space-y-3">
              {[{ value: 'SPONTANE', label: '✅ Renouvellement spontané', desc: 'Prolongation +1 an, facturation continue.' },
                { value: 'NOUVEAU_CONTRAT', label: '📄 Nouveau contrat', desc: 'Crée un nouveau contrat. Les avenants seront fusionnés.' },
                { value: 'FIN', label: '🚫 Fin du contrat', desc: 'Le client ne renouvelle pas.' }
              ].map(opt => (
                <label key={opt.value} className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer ${typeRenouvellement === opt.value ? 'border-blue-400 bg-blue-50' : 'border-gray-200 hover:bg-gray-50'}`}>
                  <input type="radio" name="type" value={opt.value} checked={typeRenouvellement === opt.value} onChange={e => setTypeRenouvellement(e.target.value)} className="mt-1" />
                  <div><div className="font-medium text-sm">{opt.label}</div><div className="text-xs text-gray-500 mt-0.5">{opt.desc}</div></div>
                </label>
              ))}
            </div>
            <div className="flex gap-3"><button onClick={renouveler} disabled={actionLoading} className="btn-primary flex-1">Confirmer</button><button onClick={() => setShowRenouveler(false)} className="btn-secondary flex-1">Annuler</button></div>
          </div>
        </div>
      )}
    </div>
  );
}
