import React, { useState, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { contratsAPI, clientsAPI, produitsAPI, indicesAPI } from '../services/api';
import api from '../services/api';
import toast from 'react-hot-toast';

function calculerProrata(dateDebut, montantAnnuel, demiMois) {
  if (!dateDebut || !montantAnnuel) return null;
  const d = new Date(dateDebut);
  const jour = d.getDate(); const mois = d.getMonth() + 1;
  if (mois === 1 && jour === 1 && !demiMois) return { prorate: false, nbMois: 12, montant: montantAnnuel, detail: "Début au 1er janvier — année complète" };
  let moisDebut, regle;
  if (jour <= 15) { moisDebut = mois; regle = `Début le ${jour}/${mois} (≤15) : facturation dès ce mois`; }
  else { moisDebut = mois + 1; regle = `Début le ${jour}/${mois} (>15) : facturation dès le mois suivant`; }
  let nbMois = 13 - moisDebut;
  const montantBase = Math.round((montantAnnuel * nbMois / 12) * 100) / 100;
  const bonusDemiMois = demiMois ? Math.round((montantAnnuel / 24) * 100) / 100 : 0;
  const montantTotal = Math.round((montantBase + bonusDemiMois) * 100) / 100;
  return { prorate: true, nbMois, demiMois, bonusDemiMois, montant: montantTotal, montantBase, detail: regle };
}

export default function ModifierContrat() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [clientRecherche, setClientRecherche] = useState('');
  const [clientsResultats, setClientsResultats] = useState([]);
  const [clientSelectionne, setClientSelectionne] = useState(null);
  const [produits, setProduits] = useState([]);
  const [indices, setIndices] = useState([]);
  const [familles, setFamilles] = useState([]);
  const [prorata, setProrata] = useState(null);
  const [demiMois, setDemiMois] = useState(false);
  const [form, setForm] = useState(null);

  useEffect(() => {
    Promise.all([
      contratsAPI.detail(id),
      produitsAPI.liste({ limit: 300 }),
      indicesAPI.liste(),
      api.get('/api/indices/familles'),
    ]).then(([contratRes, produitsRes, indicesRes, famillesRes]) => {
      setFamilles(famillesRes.data.data || []);
      const c = contratRes.data;
      setClientSelectionne({ karlia_id: c.client_karlia_id, nom: c.client_nom, numero_client: c.client_numero });
      setDemiMois(c.prorate_demi_mois || false);
      setForm({
        numero_contrat: c.numero_contrat || '',
        type_contrat: c.type_contrat || 'CONTRAT',
        famille_contrat: c.famille_contrat || 'COSOLUCE',
        date_debut: c.date_debut ? c.date_debut.substring(0, 10) : '',
        date_fin: c.date_fin ? c.date_fin.substring(0, 10) : '',
        montant_annuel_ht: c.montant_annuel_ht || '',
        indice_reference_id: c.indice_reference_id || '',
        prorate_validated: c.prorate_validated || false,
        prorate_note: c.prorate_note || '',
        articles: c.articles?.length > 0 ? c.articles.map(a => ({
          rang: a.rang,
          article_karlia_id: a.article_karlia_id || '',
          designation: a.designation || '',
          prix_unitaire_ht: a.prix_unitaire_ht || '',
          quantite: a.quantite || 1,
          taux_tva: a.taux_tva || 20,
        })) : [{ rang: 0, article_karlia_id: '', designation: '', prix_unitaire_ht: '', quantite: 1, taux_tva: 20 }],
      });
      setProduits(produitsRes.data.data || []);
      setIndices(indicesRes.data.data || []);
    }).finally(() => setLoading(false));
  }, [id]);

  useEffect(() => {
    if (form?.date_debut && form?.montant_annuel_ht)
      setProrata(calculerProrata(form.date_debut, parseFloat(form.montant_annuel_ht), demiMois));
  }, [form?.date_debut, form?.montant_annuel_ht, demiMois]);

  const rechercherClients = async (q) => {
    if (q.length < 2) { setClientsResultats([]); return; }
    try { const r = await clientsAPI.recherche(q); setClientsResultats(r.data.data || []); } catch { setClientsResultats([]); }
  };

  const setArticle = (rang, field, value) => {
    setForm(f => ({ ...f, articles: f.articles.map(a => a.rang === rang ? { ...a, [field]: value } : a) }));
    if (field === 'article_karlia_id' && value) {
      const prod = produits.find(p => p.karlia_id === value);
      if (prod) setForm(f => ({ ...f, articles: f.articles.map(a => a.rang === rang ? { ...a, designation: prod.designation, prix_unitaire_ht: prod.prix_unitaire_ht || '', article_karlia_id: value } : a) }));
    }
  };

  const ajouterArticle = () => {
    const max = Math.max(...form.articles.map(a => a.rang));
    if (max >= 7) { toast.error('Maximum 7 articles'); return; }
    setForm(f => ({ ...f, articles: [...f.articles, { rang: max + 1, article_karlia_id: '', designation: '', prix_unitaire_ht: '', quantite: 1, taux_tva: 20 }] }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!clientSelectionne) { toast.error('Veuillez sélectionner un client'); return; }
    if (!form.articles.find(a => a.rang === 0)?.designation) { toast.error('La désignation principale est obligatoire'); return; }
    setSaving(true);
    try {
      await api.put(`/api/contrats/${id}`, {
        ...form,
        client_karlia_id: clientSelectionne.karlia_id,
        client_nom: clientSelectionne.nom,
        client_numero: clientSelectionne.numero_client,
        montant_annuel_ht: parseFloat(form.montant_annuel_ht),
        indice_reference_id: form.indice_reference_id || null,
        prorate_demi_mois: demiMois,
        articles: form.articles.filter(a => a.designation).map(a => ({
          ...a,
          prix_unitaire_ht: a.prix_unitaire_ht ? parseFloat(a.prix_unitaire_ht) : null,
          quantite: parseFloat(a.quantite),
        })),
      });
      toast.success('Contrat mis à jour');
      navigate(`/contrats/${id}`);
    } catch (e) { toast.error(e.response?.data?.detail || 'Erreur mise à jour'); }
    finally { setSaving(false); }
  };

  if (loading || !form) return <div className="flex items-center justify-center h-64 text-gray-400">Chargement...</div>;

  const nbAnnees = form.date_debut && form.date_fin ? new Date(form.date_fin).getFullYear() - new Date(form.date_debut).getFullYear() + 1 : null;

  return (
    <div className="space-y-6 max-w-4xl">
      <div><h1 className="text-2xl font-bold text-gray-900">Modifier le contrat</h1><p className="text-gray-500 text-sm mt-1">Modification possible uniquement en statut Brouillon</p></div>
      <form onSubmit={handleSubmit} className="space-y-6">
        <div className="card space-y-4">
          <h2 className="font-semibold text-gray-900 text-lg border-b pb-2">① Identification</h2>
          <div className="grid grid-cols-2 gap-4">
            <div><label className="label">Numéro de contrat *</label><input className="input" required value={form.numero_contrat} onChange={e => setForm(f => ({ ...f, numero_contrat: e.target.value }))} /></div>
            <div><label className="label">Type</label><select className="input" value={form.type_contrat} onChange={e => setForm(f => ({ ...f, type_contrat: e.target.value }))}><option value="CONTRAT">Contrat</option><option value="AVENANT">Avenant</option></select></div>
            <div className="col-span-2"><label className="label">Famille de contrat *</label><select className="input" value={form.famille_contrat} onChange={e => setForm(f => ({ ...f, famille_contrat: e.target.value }))}>{familles.map(f => <option key={f.code} value={f.code}>{f.label} — {f.description}</option>)}</select></div>
          </div>
        </div>
        <div className="card space-y-4">
          <h2 className="font-semibold text-gray-900 text-lg border-b pb-2">② Client</h2>
          {clientSelectionne ? (
            <div className="flex items-center justify-between bg-green-50 border border-green-200 rounded-lg p-3">
              <div><div className="font-medium text-green-900">{clientSelectionne.nom}</div><div className="text-sm text-green-700">{clientSelectionne.numero_client}</div></div>
              <button type="button" onClick={() => setClientSelectionne(null)} className="text-green-600 hover:text-green-800 text-sm">Changer</button>
            </div>
          ) : (
            <div className="space-y-3">
              <input className="input" placeholder="🔍 Rechercher un client..." value={clientRecherche} onChange={e => { setClientRecherche(e.target.value); rechercherClients(e.target.value); }} />
              {clientsResultats.length > 0 && (
                <div className="border border-gray-200 rounded-lg divide-y max-h-48 overflow-y-auto">
                  {clientsResultats.map(c => (
                    <button key={c.karlia_id} type="button" className="w-full text-left px-4 py-2.5 hover:bg-blue-50"
                      onClick={() => { setClientSelectionne(c); setClientsResultats([]); setClientRecherche(''); }}>
                      <div className="font-medium text-sm">{c.nom}</div><div className="text-xs text-gray-500">{c.numero_client} — {c.ville}</div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
        <div className="card space-y-4">
          <h2 className="font-semibold text-gray-900 text-lg border-b pb-2">③ Dates</h2>
          <div className="grid grid-cols-2 gap-4">
            <div><label className="label">Date de début *</label><input className="input" type="date" required value={form.date_debut} onChange={e => setForm(f => ({ ...f, date_debut: e.target.value }))} /></div>
            <div><label className="label">Date de fin *</label><input className="input" type="date" required value={form.date_fin} onChange={e => setForm(f => ({ ...f, date_fin: e.target.value }))} /></div>
          </div>
          {nbAnnees && <div className="bg-blue-50 text-blue-800 px-4 py-2 rounded-lg text-sm font-medium">➜ Durée : {nbAnnees} an(s)</div>}
        </div>
        <div className="card space-y-4">
          <h2 className="font-semibold text-gray-900 text-lg border-b pb-2">④ Montant et indice</h2>
          <div className="grid grid-cols-2 gap-4">
            <div><label className="label">Montant annuel HT *</label><div className="relative"><input className="input pr-8" type="number" step="0.01" min="0" required value={form.montant_annuel_ht} onChange={e => setForm(f => ({ ...f, montant_annuel_ht: e.target.value }))} /><span className="absolute right-3 top-2 text-gray-400 text-sm">€</span></div></div>
            <div><label className="label">Indice Syntec de référence</label><select className="input" value={form.indice_reference_id} onChange={e => setForm(f => ({ ...f, indice_reference_id: e.target.value }))}><option value="">Sélectionner</option>{indices.map(i => <option key={i.id} value={i.id}>{i.date_publication} — {i.valeur}</option>)}</select></div>
          </div>
          {prorata && prorata.prorate && (
            <div className="bg-orange-50 border border-orange-200 rounded-lg p-4 space-y-2">
              <div className="font-medium text-orange-900">⚠️ Prorata première année</div>
              <div className="text-sm text-orange-800">{prorata.detail}</div>
              <div className="text-orange-900"><span className="font-medium">{prorata.nbMois} mois</span> → <span className="font-bold text-lg">{prorata.montant?.toLocaleString('fr-FR', { minimumFractionDigits: 2 })} € HT</span></div>
              <label className="flex items-center gap-2 text-sm cursor-pointer bg-orange-100 rounded-lg px-3 py-2 border border-orange-300">
                <input type="checkbox" checked={demiMois} onChange={e => setDemiMois(e.target.checked)} />
                <span>Ajouter ½ mois (+{form.montant_annuel_ht ? (parseFloat(form.montant_annuel_ht)/24).toLocaleString('fr-FR', { minimumFractionDigits: 2 }) : '0'} €)</span>
              </label>
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input type="checkbox" checked={form.prorate_validated} onChange={e => setForm(f => ({ ...f, prorate_validated: e.target.checked }))} />
                <span>Je valide ce montant proratisé</span>
              </label>
            </div>
          )}
          {prorata && !prorata.prorate && <div className="bg-green-50 border border-green-200 rounded-lg px-4 py-2 text-sm text-green-800">✅ {prorata.detail}</div>}
        </div>
        <div className="card space-y-4">
          <h2 className="font-semibold text-gray-900 text-lg border-b pb-2">⑤ Articles</h2>
          <div className="space-y-3">
            {form.articles.map(art => (
              <div key={art.rang} className={`border rounded-lg p-3 ${art.rang === 0 ? 'border-blue-300 bg-blue-50' : 'border-gray-200'}`}>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-medium text-gray-600">{art.rang === 0 ? '🔵 Désignation principale' : `Annexe — Ligne ${art.rang}`}</span>
                  {art.rang > 0 && <button type="button" onClick={() => setForm(f => ({ ...f, articles: f.articles.filter(a => a.rang !== art.rang) }))} className="text-red-400 hover:text-red-600 text-xs">✕</button>}
                </div>
                <div className="grid grid-cols-12 gap-2">
                  <div className="col-span-4"><select className="input text-xs" value={art.article_karlia_id} onChange={e => setArticle(art.rang, 'article_karlia_id', e.target.value)}><option value="">Sélectionner article Karlia</option>{produits.map(p => <option key={p.karlia_id} value={p.karlia_id}>{p.reference ? `[${p.reference}] ` : ''}{p.designation}</option>)}</select></div>
                  <div className="col-span-4"><input className="input text-xs" placeholder="Désignation *" required={art.rang === 0} value={art.designation} onChange={e => setArticle(art.rang, 'designation', e.target.value)} /></div>
                  <div className="col-span-2"><input className="input text-xs" type="number" placeholder="Prix HT" value={art.prix_unitaire_ht} onChange={e => setArticle(art.rang, 'prix_unitaire_ht', e.target.value)} /></div>
                  <div className="col-span-2"><input className="input text-xs" type="number" placeholder="TVA%" value={art.taux_tva} onChange={e => setArticle(art.rang, 'taux_tva', e.target.value)} /></div>
                </div>
              </div>
            ))}
          </div>
          {form.articles.length < 8 && <button type="button" onClick={ajouterArticle} className="btn-secondary text-sm">➕ Ajouter une ligne</button>}
        </div>
        <div className="flex gap-3">
          <button type="submit" disabled={saving} className="btn-primary px-8">{saving ? 'Enregistrement...' : '💾 Enregistrer les modifications'}</button>
          <button type="button" className="btn-secondary" onClick={() => navigate(`/contrats/${id}`)}>Annuler</button>
        </div>
      </form>
    </div>
  );
}
