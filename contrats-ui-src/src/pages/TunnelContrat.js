import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import api, { contratsAPI, clientsAPI, produitsAPI } from '../services/api';
import toast from 'react-hot-toast';
import { format, addDays } from 'date-fns';
import { fr } from 'date-fns/locale';

function calculerProrata(dateDebut, montantAnnuel, demiMois) {
  if (!dateDebut || !montantAnnuel) return null;
  const d = new Date(dateDebut + 'T12:00:00');
  const jour = d.getDate(); const mois = d.getMonth() + 1;
  if (mois === 1 && jour === 1 && !demiMois) return { prorate: false, nbMois: 12, montant: montantAnnuel, detail: "Début au 1er janvier — année complète" };
  let moisDebut, regle;
  if (jour <= 15) { moisDebut = mois; regle = `Début le ${jour}/${mois} (≤15) : facturation dès ce mois`; }
  else { moisDebut = mois + 1; regle = `Début le ${jour}/${mois} (>15) : facturation dès le mois suivant`; }
  const nbMois = 13 - moisDebut;
  const montantBase = Math.round((montantAnnuel * nbMois / 12) * 100) / 100;
  const bonusDemiMois = demiMois ? Math.round((montantAnnuel / 24) * 100) / 100 : 0;
  const montantTotal = Math.round((montantBase + bonusDemiMois) * 100) / 100;
  const detailDemi = demiMois ? ` + ½ mois (${bonusDemiMois.toLocaleString('fr-FR', { minimumFractionDigits: 2 })} €)` : '';
  return { prorate: true, nbMois, demiMois, bonusDemiMois, montant: montantTotal, montantBase, detail: regle + detailDemi };
}

const FAMILLES = [
  { code: 'COSOLUCE', label: 'Cosoluce', description: 'Révision Syntec Août' },
  { code: 'CANTINE', label: 'Cantine de France', description: 'Révision Syntec Octobre' },
  { code: 'DIGITECH', label: 'Digitech', description: 'Révision manuelle' },
  { code: 'MAINTENANCE', label: 'Maintenance matériel', description: 'Révision Syntec Août' },
  { code: 'ASSISTANCE_TEL', label: 'Assistance Téléphonique', description: 'Révision Syntec Août' },
  { code: 'KIWI_BACKUP', label: 'Kiwi Backup', description: 'Prix fixe' },
];

const ETAPES = ['Informations', 'Articles', 'Récapitulatif', 'Première facture'];

function ProgressBar({ etapeCourante }) {
  return (
    <div className="flex items-center mb-8">
      {ETAPES.map((e, i) => (
        <React.Fragment key={i}>
          <div className="flex items-center gap-2">
            <span className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold ${
              i < etapeCourante ? 'bg-green-500 text-white' :
              i === etapeCourante ? 'bg-blue-600 text-white' :
              'bg-gray-200 text-gray-400'}`}>
              {i < etapeCourante ? '✓' : i + 1}
            </span>
            <span className={`text-sm font-medium hidden sm:inline ${
              i === etapeCourante ? 'text-blue-700' :
              i < etapeCourante ? 'text-green-700' : 'text-gray-400'}`}>
              {e}
            </span>
          </div>
          {i < ETAPES.length - 1 && (
            <div className={`flex-1 h-0.5 mx-3 ${i < etapeCourante ? 'bg-green-400' : 'bg-gray-200'}`} />
          )}
        </React.Fragment>
      ))}
    </div>
  );
}

function SelectionClient({ clientSelectionne, setClientSelectionne }) {
  const [recherche, setRecherche] = useState('');
  const [resultats, setResultats] = useState([]);
  const [searching, setSearching] = useState(false);

  const chercher = useCallback(async (q) => {
    if (!q || q.length < 2) { setResultats([]); return; }
    setSearching(true);
    try {
      const r = await clientsAPI.liste({ recherche: q, limit: 10 });
      setResultats(r.data.data || []);
    } catch { toast.error('Erreur recherche client'); }
    finally { setSearching(false); }
  }, []);

  useEffect(() => {
    const t = setTimeout(() => chercher(recherche), 300);
    return () => clearTimeout(t);
  }, [recherche, chercher]);

  if (clientSelectionne) {
    return (
      <div className="flex items-center justify-between p-3 bg-blue-50 border border-blue-200 rounded-lg">
        <div>
          <p className="font-medium text-blue-900">{clientSelectionne.nom}</p>
          <p className="text-xs text-blue-600">{clientSelectionne.numero_client || clientSelectionne.karlia_id}</p>
        </div>
        <button onClick={() => setClientSelectionne(null)} className="text-xs text-blue-600 underline">Changer</button>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <input className="input" placeholder="Rechercher un client (nom, numéro)..."
        value={recherche} onChange={e => setRecherche(e.target.value)} />
      {searching && <p className="text-xs text-gray-400">Recherche...</p>}
      {resultats.length > 0 && (
        <div className="border border-gray-200 rounded-lg divide-y max-h-48 overflow-y-auto">
          {resultats.map(c => (
            <button key={c.karlia_id || c.id} onClick={() => { setClientSelectionne(c); setResultats([]); setRecherche(''); }}
              className="w-full text-left px-3 py-2 hover:bg-blue-50 text-sm">
              <span className="font-medium">{c.nom}</span>
              <span className="text-gray-400 ml-2 text-xs">{c.numero || ''}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function ArticlesEditor({ articles, setArticles }) {
  const [catalogue, setCatalogue] = useState([]);

  useEffect(() => {
    produitsAPI.liste({ limit: 200 })
      .then(r => setCatalogue(r.data.data || []))
      .catch(() => {});
  }, []);

  const addArticle = () => setArticles(prev => [...prev, {
    rang: prev.length, designation: '', article_karlia_id: null,
    reference: '', prix_unitaire_ht: '', quantite: 1, taux_tva: 20
  }]);

  const update = (i, field, val) => setArticles(prev =>
    prev.map((a, idx) => idx === i ? { ...a, [field]: val } : a));

  const remove = (i) => setArticles(prev =>
    prev.filter((_, idx) => idx !== i).map((a, idx) => ({ ...a, rang: idx })));

  const selectionnerCatalogue = (i, art) => {
    update(i, 'designation', art.designation || '');
    update(i, 'article_karlia_id', String(art.karlia_id || ''));
    update(i, 'reference', art.reference || '');
    update(i, 'prix_unitaire_ht', art.prix_unitaire_ht || '');
    update(i, 'taux_tva', art.taux_tva || 20);
  };

  return (
    <div className="space-y-3">
      {articles.map((art, i) => (
        <div key={i} className={`p-3 rounded-lg border ${i === 0 ? 'border-blue-200 bg-blue-50' : 'border-gray-200 bg-gray-50'}`}>
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-gray-500">
              {i === 0 ? '⭐ Article principal (rang 0 — obligatoire pour Karlia)' : `Article annexe ${i}`}
            </span>
            {i > 0 && <button onClick={() => remove(i)} className="text-red-500 text-xs">✕ Supprimer</button>}
          </div>
                    {catalogue.length > 0 && (
            <select className="input text-sm mb-2 font-medium border-blue-300 bg-white" value={art.article_karlia_id || ''}
              onChange={e => { const a = catalogue.find(x => String(x.karlia_id) === e.target.value); if (a) selectionnerCatalogue(i, a); }}>
              <option value="">📦 Choisir un article depuis Karlia...</option>
              {catalogue.map(a => (
                <option key={a.karlia_id} value={String(a.karlia_id)}>
                  {a.designation} — {a.prix_unitaire_ht || '?'} € HT
                </option>
              ))}
            </select>
          )}
          <div className="grid grid-cols-2 gap-2">
            <div className="col-span-2">
              <input className="input text-sm" placeholder="Désignation *" value={art.designation}
                onChange={e => update(i, 'designation', e.target.value)} />
            </div>
            <div>
              <input className="input text-sm" placeholder="ID Karlia *" value={art.article_karlia_id || ''}
                onChange={e => update(i, 'article_karlia_id', e.target.value)} readOnly 
                title="Sélectionnez depuis le catalogue ci-dessus" />
            </div>
            <div>
              <input className="input text-sm" placeholder="Référence" value={art.reference || ''}
                onChange={e => update(i, 'reference', e.target.value)} />
            </div>
            <div>
              <input className="input text-sm" type="number" placeholder="Prix HT *" value={art.prix_unitaire_ht}
                onChange={e => update(i, 'prix_unitaire_ht', e.target.value)} />
            </div>
            <div className="grid grid-cols-2 gap-1">
              <input className="input text-sm" type="number" placeholder="Qté" value={art.quantite}
                onChange={e => update(i, 'quantite', e.target.value)} />
              <select className="input text-sm" value={art.taux_tva}
                onChange={e => update(i, 'taux_tva', parseFloat(e.target.value))}>
                <option value={20}>20%</option>
                <option value={10}>10%</option>
                <option value={5.5}>5.5%</option>
                <option value={0}>0%</option>
              </select>
            </div>
          </div>
        </div>
      ))}
      <button onClick={addArticle} className="btn-secondary text-sm w-full">+ Ajouter un article</button>
    </div>
  );
}

export default function TunnelContrat() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const mode = searchParams.get('mode') || 'nouveau';
  const contratParentId = searchParams.get('contrat_id');

  const [etape, setEtape] = useState(0);
  const [loading, setLoading] = useState(false);
  const [prorata, setProrata] = useState(null);
  const [demiMois, setDemiMois] = useState(false);
  const [contratParent, setContratParent] = useState(null);
  const [contratCree, setContratCree] = useState(null);
  const [factureCree, setFactureCree] = useState(null);

  const [form, setForm] = useState({
    numero_contrat: '',
    famille_contrat: 'COSOLUCE',
    date_debut: '',
    date_fin: '',
    montant_annuel_ht: '',
    notes_internes: '',
    prorate_validated: false,
  });
  const [clientSelectionne, setClientSelectionne] = useState(null);
  const [articles, setArticles] = useState([{
    rang: 0, designation: '', article_karlia_id: null,
    reference: '', prix_unitaire_ht: '', quantite: 1, taux_tva: 20
  }]);

  // Calcul prorata à la volée
  useEffect(() => {
    if (form.date_debut && form.montant_annuel_ht) {
      setProrata(calculerProrata(form.date_debut, parseFloat(form.montant_annuel_ht), demiMois));
    } else {
      setProrata(null);
    }
  }, [form.date_debut, form.montant_annuel_ht, demiMois]);

  // Charger le contrat parent en mode renouvellement
  useEffect(() => {
    if (mode !== 'renouvellement' || !contratParentId) return;
    contratsAPI.detail(contratParentId).then(r => {
      const c = r.data;
      setContratParent(c);
      // Dates par défaut : lendemain de la fin + même durée
      const dateFin = new Date(c.date_fin + 'T12:00:00');
      const dateDebut = addDays(dateFin, 1);
      const dateFin2 = new Date(dateDebut);
      dateFin2.setFullYear(dateFin2.getFullYear() + (c.nombre_annees || 1));
      dateFin2.setDate(dateFin2.getDate() - 1);
      setForm(f => ({
        ...f,
        famille_contrat: c.famille_contrat || 'COSOLUCE',
        date_debut: format(dateDebut, 'yyyy-MM-dd'),
        date_fin: format(dateFin2, 'yyyy-MM-dd'),
        montant_annuel_ht: c.montant_annuel_ht || '',
      }));
      setClientSelectionne({
        id_karlia: c.client_karlia_id,
        nom: c.client_nom,
        numero: c.client_numero,
      });
      if (c.articles && c.articles.length > 0) {
        setArticles(c.articles.map((a, i) => ({
          rang: i,
          designation: a.designation || '',
          article_karlia_id: a.article_karlia_id || null,
          reference: a.reference || '',
          prix_unitaire_ht: a.prix_unitaire_ht || '',
          quantite: a.quantite || 1,
          taux_tva: a.taux_tva || 20,
        })));
      }
    }).catch(() => toast.error('Impossible de charger le contrat parent'));
  }, [mode, contratParentId]);

  // ── Validation étape 0 ──────────────────────────────────────
  const validerEtape0 = () => {
    if (!form.numero_contrat.trim()) { toast.error('Le numéro de contrat est obligatoire'); return; }
    if (!clientSelectionne) { toast.error('Sélectionnez un client'); return; }
    if (!form.date_debut || !form.date_fin) { toast.error('Les dates sont obligatoires'); return; }
    if (new Date(form.date_debut) >= new Date(form.date_fin)) { toast.error('La date de fin doit être après la date de début'); return; }
    if (!form.montant_annuel_ht || parseFloat(form.montant_annuel_ht) <= 0) { toast.error('Le montant annuel HT est obligatoire'); return; }
    if (prorata && prorata.prorate && !form.prorate_validated) { toast.error('Veuillez valider le montant proratisé'); return; }
    setEtape(1);
  };

  // ── Validation étape 1 ──────────────────────────────────────
  const validerEtape1 = () => {
    const principal = articles[0];
    if (!principal?.designation?.trim()) { toast.error('La désignation de l\'article principal est obligatoire'); return; }
    if (!principal?.article_karlia_id) { toast.error('L\'ID Karlia de l\'article principal est obligatoire'); return; }
    if (!principal?.prix_unitaire_ht || parseFloat(principal.prix_unitaire_ht) <= 0) { toast.error('Le prix HT est obligatoire'); return; }
    setEtape(2);
  };

  // ── Création du contrat (étape 2 → 3) ──────────────────────
  const creerContrat = async () => {
    setLoading(true);
    try {
      let contratId;

      if (mode === 'renouvellement') {
        // 1. Créer le renouvellement via l'API
        const r = await contratsAPI.renouveler(contratParentId, {
          type_renouvellement: 'NOUVEAU_CONTRAT',
          nouveau_numero: form.numero_contrat.trim(),
          nouvelle_date_debut: form.date_debut,
          nouvelle_date_fin: form.date_fin,
        });
        contratId = r.data.nouveau_contrat_id;
        // 2. Mettre à jour les articles, le montant et le prorata
        await api.put(`/api/contrats/${contratId}`, {
          montant_annuel_ht: parseFloat(form.montant_annuel_ht),
          prorate_validated: form.prorate_validated,
          articles: articles.map((a, i) => ({
            rang: i,
            designation: a.designation,
            article_karlia_id: a.article_karlia_id || null,
            reference: a.reference || null,
            prix_unitaire_ht: a.prix_unitaire_ht ? parseFloat(a.prix_unitaire_ht) : null,
            quantite: parseFloat(a.quantite),
            taux_tva: a.taux_tva || 20,
          })),
        });
      } else {
        // Nouveau contrat
        const r = await contratsAPI.creer({
          numero_contrat: form.numero_contrat.trim(),
          client_karlia_id: String(clientSelectionne.karlia_id || clientSelectionne.id_karlia),
          client_nom: clientSelectionne.nom,
          client_numero: clientSelectionne.numero_client || null,
          famille_contrat: form.famille_contrat,
          date_debut: form.date_debut,
          date_fin: form.date_fin,
          montant_annuel_ht: parseFloat(form.montant_annuel_ht),
          prorate_validated: form.prorate_validated,
          notes_internes: form.notes_internes || null,
          type_contrat: 'CONTRAT',
          articles: articles.map((a, i) => ({
            rang: i,
            designation: a.designation,
            article_karlia_id: a.article_karlia_id || null,
            reference: a.reference || null,
            prix_unitaire_ht: a.prix_unitaire_ht ? parseFloat(a.prix_unitaire_ht) : null,
            quantite: parseFloat(a.quantite),
            taux_tva: a.taux_tva || 20,
          })),
        });
        contratId = r.data.id;
      }

      // 3. Valider le contrat
      await contratsAPI.valider(contratId);
      // 4. Recharger le contrat validé
      const detail = await contratsAPI.detail(contratId);
      setContratCree(detail.data);
      toast.success(`Contrat ${form.numero_contrat} créé et validé`);
      setEtape(3);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Erreur lors de la création');
    } finally {
      setLoading(false);
    }
  };

  // ── Émission de la première facture ────────────────────────
  const emettrePremiereFacture = async () => {
    const plan = contratCree?.plan_facturation || [];
    const premiere = plan.find(p => p.statut === 'PLANIFIEE' || p.statut === 'CALCULEE');
    if (!premiere) { toast.error('Aucune facture planifiée trouvée'); return; }
    setLoading(true);
    try {
      if (premiere.statut === 'PLANIFIEE') {
        await api.post('/api/facturation/calculer', {
          annee: premiere.annee_facturation,
          plan_ids: [premiere.id],
          nouveaux_montants: {},
        });
      }
      const r = await api.post('/api/facturation/lancer', {
        annee: premiere.annee_facturation,
        plan_ids: [premiere.id],
      });
      setFactureCree(r.data);
      if (r.data.emises > 0) toast.success('Facture émise dans Karlia !');
      else toast.error('Erreur lors de l\'émission');
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Erreur émission facture');
    } finally {
      setLoading(false);
    }
  };

  const terminer = () => navigate(contratCree ? `/contrats/${contratCree.id}` : '/contrats');

  // ── Rendu ───────────────────────────────────────────────────
  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">
          {mode === 'renouvellement' ? '🔄 Renouvellement de contrat' : '➕ Nouveau contrat'}
        </h1>
        {mode === 'renouvellement' && contratParent && (
          <p className="text-gray-500 text-sm mt-1">
            Contrat parent : <span className="font-medium text-blue-600">{contratParent.numero_contrat}</span>
            {' — '}{contratParent.client_nom}
            {' — fin le '}{contratParent.date_fin ? format(new Date(contratParent.date_fin + 'T12:00:00'), 'dd/MM/yyyy', { locale: fr }) : '—'}
          </p>
        )}
      </div>

      <ProgressBar etapeCourante={etape} />

      {/* ── ÉTAPE 0 : Informations ── */}
      {etape === 0 && (
        <div className="card space-y-4">
          <h2 className="font-semibold text-gray-900 text-lg border-b pb-2">① Informations du contrat</h2>
          <div className="grid grid-cols-2 gap-4">
            <div className="col-span-2">
              <label className="label">
                {mode === 'renouvellement' ? 'Numéro du nouveau contrat *' : 'Numéro de contrat *'}
              </label>
              <input className="input" placeholder="Ex: CTR-2026-001"
                value={form.numero_contrat} onChange={e => setForm(f => ({ ...f, numero_contrat: e.target.value }))} />
              {mode === 'renouvellement' && (
                <p className="text-xs text-gray-400 mt-1">Numéro saisi manuellement — aucune génération automatique</p>
              )}
            </div>
            <div className="col-span-2">
              <label className="label">Client *</label>
              <SelectionClient clientSelectionne={clientSelectionne} setClientSelectionne={setClientSelectionne} />
            </div>
            <div className="col-span-2">
              <label className="label">Famille de contrat *</label>
              <select className="input" value={form.famille_contrat}
                onChange={e => setForm(f => ({ ...f, famille_contrat: e.target.value }))}>
                {FAMILLES.map(f => <option key={f.code} value={f.code}>{f.label} — {f.description}</option>)}
              </select>
            </div>
            <div>
              <label className="label">Date de début *</label>
              <input className="input" type="date" value={form.date_debut}
                onChange={e => setForm(f => ({ ...f, date_debut: e.target.value }))} />
              {mode === 'renouvellement' && (
                <p className="text-xs text-gray-400 mt-1">Par défaut : lendemain de la fin du contrat précédent</p>
              )}
            </div>
            <div>
              <label className="label">Date de fin *</label>
              <input className="input" type="date" value={form.date_fin}
                onChange={e => setForm(f => ({ ...f, date_fin: e.target.value }))} />
              {mode === 'renouvellement' && contratParent && (
                <p className="text-xs text-gray-400 mt-1">Par défaut : même durée ({contratParent.nombre_annees} an{contratParent.nombre_annees > 1 ? 's' : ''})</p>
              )}
            </div>
            <div className="col-span-2">
              <label className="label">Montant annuel HT (€) *</label>
              <input className="input" type="number" step="0.01" placeholder="Ex: 1500.00"
                value={form.montant_annuel_ht} onChange={e => setForm(f => ({ ...f, montant_annuel_ht: e.target.value }))} />
            </div>
            {prorata && prorata.prorate && (
              <div className="col-span-2">
                <div className="bg-orange-50 border border-orange-200 rounded-lg p-4 space-y-2">
                  <p className="text-sm font-semibold text-orange-800">⚠️ Prorata première année</p>
                  <p className="text-sm text-orange-700">{prorata.detail}</p>
                  <div className="flex items-center gap-4 text-sm">
                    <span className="text-orange-800">{prorata.nbMois} mois facturés</span>
                    <span className="font-bold text-lg text-orange-900">{prorata.montant?.toLocaleString('fr-FR', { minimumFractionDigits: 2 })} € HT</span>
                  </div>
                  <label className="flex items-center gap-2 text-sm cursor-pointer text-orange-800">
                    <input type="checkbox" checked={demiMois} onChange={e => setDemiMois(e.target.checked)} />
                    <span>Ajouter ½ mois supplémentaire</span>
                  </label>
                  <label className="flex items-center gap-2 text-sm cursor-pointer font-medium text-orange-900">
                    <input type="checkbox" checked={form.prorate_validated} onChange={e => setForm(f => ({ ...f, prorate_validated: e.target.checked }))} />
                    <span>Je valide ce montant proratisé</span>
                  </label>
                </div>
              </div>
            )}
            {prorata && !prorata.prorate && (
              <div className="col-span-2">
                <div className="bg-green-50 border border-green-200 rounded-lg px-4 py-2 text-sm text-green-800">✅ {prorata.detail}</div>
              </div>
            )}
            <div className="col-span-2">
              <label className="label">Notes internes</label>
              <textarea className="input h-16 resize-none" placeholder="Notes internes optionnelles..."
                value={form.notes_internes} onChange={e => setForm(f => ({ ...f, notes_internes: e.target.value }))} />
            </div>
          </div>
          <div className="flex justify-end pt-2">
            <button onClick={validerEtape0} className="btn-primary px-6">Suivant : Articles →</button>
          </div>
        </div>
      )}

      {/* ── ÉTAPE 1 : Articles ── */}
      {etape === 1 && (
        <div className="card space-y-4">
          <h2 className="font-semibold text-gray-900 text-lg border-b pb-2">② Articles du contrat</h2>
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-800">
            ⚠️ L'article principal avec ID Karlia est obligatoire pour que la facture soit enregistrée avec le bon montant.
          </div>
          <ArticlesEditor articles={articles} setArticles={setArticles} />
          <div className="flex justify-between pt-2">
            <button onClick={() => setEtape(0)} className="btn-secondary px-4">← Retour</button>
            <button onClick={validerEtape1} className="btn-primary px-6">Suivant : Récapitulatif →</button>
          </div>
        </div>
      )}

      {/* ── ÉTAPE 2 : Récapitulatif ── */}
      {etape === 2 && (
        <div className="card space-y-4">
          <h2 className="font-semibold text-gray-900 text-lg border-b pb-2">③ Récapitulatif et validation</h2>
          <div className="grid grid-cols-2 gap-3 text-sm">
            {[
              ['Numéro', form.numero_contrat],
              ['Client', clientSelectionne?.nom],
              ['Famille', FAMILLES.find(f => f.code === form.famille_contrat)?.label],
              ['Montant annuel HT', `${parseFloat(form.montant_annuel_ht || 0).toLocaleString('fr-FR', { minimumFractionDigits: 2 })} €`],
              ['Début', form.date_debut ? format(new Date(form.date_debut + 'T12:00:00'), 'dd/MM/yyyy', { locale: fr }) : '—'],
              ['Fin', form.date_fin ? format(new Date(form.date_fin + 'T12:00:00'), 'dd/MM/yyyy', { locale: fr }) : '—'],
            ].map(([label, val]) => (
              <div key={label} className="bg-gray-50 rounded-lg p-3">
                <p className="text-xs text-gray-500 mb-1">{label}</p>
                <p className="font-semibold">{val}</p>
              </div>
            ))}
          </div>
          <div>
            <p className="text-xs text-gray-500 mb-2">Articles</p>
            {articles.map((a, i) => (
              <div key={i} className="flex justify-between text-sm bg-gray-50 rounded px-3 py-2 mb-1">
                <span>{i === 0 ? '⭐ ' : ''}{a.designation}</span>
                <span className="font-medium">{a.prix_unitaire_ht ? `${parseFloat(a.prix_unitaire_ht).toLocaleString('fr-FR', { minimumFractionDigits: 2 })} €` : '—'}</span>
              </div>
            ))}
          </div>
          {mode === 'renouvellement' && contratParent && (
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-sm text-blue-800">
              Le contrat <strong>{contratParent.numero_contrat}</strong> sera archivé et remplacé par <strong>{form.numero_contrat}</strong>.
            </div>
          )}
          <div className="flex justify-between pt-2">
            <button onClick={() => setEtape(1)} disabled={loading} className="btn-secondary px-4">← Retour</button>
            <button onClick={creerContrat} disabled={loading} className="btn-primary px-6">
              {loading ? '⏳ Création en cours...' : '✅ Créer et valider le contrat'}
            </button>
          </div>
        </div>
      )}

      {/* ── ÉTAPE 3 : Première facture ── */}
      {etape === 3 && contratCree && (
        <div className="card space-y-4">
          <h2 className="font-semibold text-gray-900 text-lg border-b pb-2">④ Première facture</h2>
          <div className="bg-green-50 border border-green-200 rounded-lg p-4 text-green-800">
            <p className="font-semibold">✅ Contrat {contratCree.numero_contrat} créé et validé</p>
            <p className="text-sm mt-1">{contratCree.client_nom}</p>
          </div>
          {!factureCree ? (
            <>
              <div className="space-y-1">
                <p className="text-sm font-medium text-gray-700 mb-2">Plan de facturation :</p>
                {(contratCree.plan_facturation || []).map((p, i) => (
                  <div key={i} className={`flex items-center justify-between text-sm rounded px-3 py-2 ${i === 0 ? 'bg-blue-50 border border-blue-200' : 'bg-gray-50'}`}>
                    <span>{i === 0 ? '👉 ' : ''}{p.type_facture} {p.annee_facturation}</span>
                    <span className="font-medium">{p.montant_ht_prevu?.toLocaleString('fr-FR', { minimumFractionDigits: 2 })} €</span>
                    <span className={`text-xs px-2 py-0.5 rounded-full ${p.statut === 'EMISE' ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}`}>{p.statut}</span>
                  </div>
                ))}
              </div>
              <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-800">
                Voulez-vous émettre la première facture maintenant dans Karlia ? (statut : Envoyée directement)
              </div>
              <div className="flex gap-3 justify-between pt-2">
                <button onClick={terminer} className="btn-secondary px-4">
                  Passer — je le ferai depuis Facturation
                </button>
                <button onClick={emettrePremiereFacture} disabled={loading} className="btn-primary px-6">
                  {loading ? '⏳ Émission...' : '💶 Émettre la première facture'}
                </button>
              </div>
            </>
          ) : (
            <div className="space-y-4">
              {factureCree.emises > 0 && (
                <div className="bg-green-50 border border-green-200 rounded-lg p-4 text-green-800">
                  <p className="font-semibold">💶 {factureCree.emises} facture(s) émise(s) dans Karlia</p>
                </div>
              )}
              {factureCree.erreurs > 0 && (
                <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-800">
                  <p className="font-semibold">❌ {factureCree.erreurs} erreur(s) lors de l'émission</p>
                </div>
              )}
              <div className="flex justify-end">
                <button onClick={terminer} className="btn-primary px-6">Voir le contrat →</button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
