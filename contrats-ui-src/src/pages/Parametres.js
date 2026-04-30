import React, { useState, useEffect, useRef } from 'react';
import api from '../services/api';
import toast from 'react-hot-toast';

const TYPES_MODELES = [
  { value: 'CONTRAT_COSOLUCE',       label: 'Cosoluce + Annexes' },
  { value: 'CONTRAT_CANTINE',        label: 'Cantine de France' },
  { value: 'CONTRAT_MAINTENANCE',    label: 'Maintenance Système' },
  { value: 'CONTRAT_ASSISTANCE_TEL', label: 'Assistance Téléphonique' },
  { value: 'CONTRAT_DIGITECH',       label: 'Digitech' },
  { value: 'CONTRAT_KIWI_BACKUP',    label: 'Kiwi Backup' },
];

const PARAMS_CHORUS = [
  { cle: 'chorus_client_id', label: 'Client ID PISTE', type: 'text', placeholder: 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx' },
  { cle: 'chorus_client_secret', label: 'Client Secret PISTE', type: 'password', placeholder: 'Secret OAuth2' },
  { cle: 'chorus_tech_username', label: 'Login compte technique', type: 'text', placeholder: 'TECH_1_xxxxx@cpro.fr' },
  { cle: 'chorus_tech_password', label: 'Mot de passe technique', type: 'password', placeholder: 'Mot de passe' },
  { cle: 'chorus_siret_emetteur', label: 'SIRET émetteur', type: 'text', placeholder: '12345678901234' },
  { cle: 'chorus_code_service', label: 'Code service (optionnel)', type: 'text', placeholder: '' },
  { cle: 'chorus_code_banque', label: 'Code banque (optionnel)', type: 'text', placeholder: '' },
  { cle: 'chorus_id_fournisseur', label: 'idFournisseur Chorus (requis)', type: 'text', placeholder: 'ID numérique de la structure fournisseur' },
  { cle: 'chorus_id_utilisateur_courant', label: 'idUtilisateurCourant Chorus (optionnel)', type: 'text', placeholder: 'ID numérique du compte technique' },
];

export default function Parametres() {
  const [params, setParams] = useState(null);
  const [nouvelleClé, setNouvelleClé] = useState('');
  const [showCle, setShowCle] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [viding, setViding] = useState(false);
  const [synchroLoading, setSynchroLoading] = useState(false);
  const [testResult, setTestResult] = useState(null);
  // Modèles
  const [modeles, setModeles] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [uploadType, setUploadType] = useState(TYPES_MODELES[0].value);
  const [uploadNom, setUploadNom] = useState('');
  const [uploadVersion, setUploadVersion] = useState('1.0');
  const fileRef = useRef(null);
  // Chorus Pro
  const [chorusParams, setChorusParams] = useState({});
  const [chorusSaving, setChorusSaving] = useState(false);
  const [chorusTesting, setChorusTesting] = useState(false);
  const [chorusTestResult, setChorusTestResult] = useState(null);
  const [chorusMode, setChorusMode] = useState('true');

  const charger = () => {
    setLoading(true);
    api.get('/api/parametres/').then(r => setParams(r.data)).finally(() => setLoading(false));
  };

  const chargerModeles = () => {
    api.get('/api/documents/modeles').then(r => setModeles(r.data.data || [])).catch(() => {});
  };

  const chargerChorusParams = () => {
    api.get('/api/parametres/chorus').then(r => {
      const data = r.data || {};
      setChorusParams(data);
      setChorusMode(data.chorus_mode_qualification || 'true');
    }).catch(() => {});
  };

  useEffect(() => { charger(); chargerModeles(); chargerChorusParams(); }, []);

  const sauvegarderCle = async () => {
    if (!nouvelleClé) { toast.error('Saisissez une clé API'); return; }
    setSaving(true);
    try {
      await api.put('/api/parametres/karlia-api-key', { valeur: nouvelleClé });
      toast.success('Clé API mise à jour');
      setNouvelleClé(''); setShowCle(false); charger();
    } catch (e) { toast.error(e.response?.data?.detail || 'Erreur'); }
    finally { setSaving(false); }
  };

  const testerConnexion = async () => {
    setTesting(true); setTestResult(null);
    try {
      const r = await api.post('/api/parametres/tester-connexion');
      setTestResult(r.data);
      if (r.data.succes) toast.success('Connexion Karlia OK');
      else toast.error('Connexion Karlia échouée');
    } catch (e) { toast.error('Erreur test connexion'); }
    finally { setTesting(false); }
  };

  const viderCache = async () => {
    if (!window.confirm('Vider tout le cache clients et articles ? Cette action est irréversible (les données Karlia ne sont pas affectées).')) return;
    setViding(true);
    try {
      const r = await api.post('/api/parametres/vider-cache');
      toast.success(r.data.message); charger();
    } catch (e) { toast.error(e.response?.data?.detail || 'Erreur'); }
    finally { setViding(false); }
  };

  const lancerSynchro = async () => {
    setSynchroLoading(true);
    try {
      await api.post('/api/synchro/lancer');
      toast.success('Synchronisation terminée'); charger();
    } catch (e) { toast.error('Erreur synchronisation'); }
    finally { setSynchroLoading(false); }
  };

  const uploaderModele = async () => {
    const fichier = fileRef.current?.files?.[0];
    if (!fichier) { toast.error('Choisissez un fichier .docx'); return; }
    if (!uploadNom.trim()) { toast.error('Saisissez un nom pour ce modèle'); return; }
    setUploading(true);
    try {
      const form = new FormData();
      form.append('fichier', fichier);
      form.append('type_document', uploadType);
      form.append('nom', uploadNom.trim());
      form.append('version', uploadVersion.trim() || '1.0');
      await api.post('/api/documents/modeles/upload', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      toast.success('Modèle uploadé et activé');
      setUploadNom(''); setUploadVersion('1.0');
      if (fileRef.current) fileRef.current.value = '';
      chargerModeles();
    } catch (e) { toast.error(e.response?.data?.detail || 'Erreur upload'); }
    finally { setUploading(false); }
  };

  const activerModele = async (id) => {
    try {
      await api.patch('/api/documents/modeles/' + id + '/activer');
      toast.success('Modèle activé'); chargerModeles();
    } catch (e) { toast.error('Erreur'); }
  };

  const supprimerModele = async (id, nom) => {
    if (!window.confirm('Supprimer le modèle ' + nom + ' ?')) return;
    try {
      await api.delete('/api/documents/modeles/' + id);
      toast.success('Modèle supprimé'); chargerModeles();
    } catch (e) { toast.error('Erreur'); }
  };

  // Chorus Pro
  const sauvegarderChorus = async () => {
    setChorusSaving(true);
    try {
      const data = { ...chorusParams, chorus_mode_qualification: chorusMode };
      await api.put('/api/parametres/chorus', data);
      toast.success('Paramètres Chorus Pro enregistrés');
      chargerChorusParams();
    } catch (e) { toast.error(e.response?.data?.detail || 'Erreur'); }
    finally { setChorusSaving(false); }
  };

  const testerChorusConnexion = async () => {
    setChorusTesting(true); setChorusTestResult(null);
    try {
      const r = await api.get('/api/chorus/test-connexion');
      setChorusTestResult(r.data);
      if (r.data.ok) toast.success('Connexion Chorus Pro OK');
      else toast.error('Connexion Chorus Pro échouée');
    } catch (e) { 
      setChorusTestResult({ ok: false, error: e.response?.data?.detail || 'Erreur' });
      toast.error(e.response?.data?.detail || 'Erreur test connexion'); 
    }
    finally { setChorusTesting(false); }
  };

  const handleChorusChange = (cle, valeur) => {
    setChorusParams(prev => ({ ...prev, [cle]: valeur }));
  };

  if (loading) return <div className="flex items-center justify-center h-64 text-gray-400">Chargement...</div>;

  const modelesParType = TYPES_MODELES.map(t => ({
    ...t,
    modeles: modeles.filter(m => m.type_document === t.value),
  })).filter(t => t.modeles.length > 0);

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Paramètres</h1>
        <p className="text-gray-500 text-sm mt-1">Configuration du module et connexions API</p>
      </div>

      {/* Clé API Karlia */}
      <div className="card space-y-4">
        <h2 className="font-semibold text-gray-900 border-b pb-2">🔑 Clé API Karlia</h2>
        <div className="flex items-center justify-between bg-gray-50 rounded-lg px-4 py-3">
          <div>
            <div className="text-sm text-gray-500">Clé active</div>
            <div className="font-mono font-medium text-gray-900">{params?.karlia_api_key_apercu || 'Non configurée'}</div>
          </div>
          <button onClick={testerConnexion} disabled={testing} className="btn-secondary text-sm">
            {testing ? '⏳ Test...' : '🔌 Tester la connexion'}
          </button>
        </div>
        {testResult && (
          <div className={'rounded-lg px-4 py-3 text-sm ' + (testResult.succes ? 'bg-green-50 border border-green-200 text-green-800' : 'bg-red-50 border border-red-200 text-red-800')}>
            {testResult.succes ? '✅' : '❌'} {typeof testResult.message === 'object' ? JSON.stringify(testResult.message) : testResult.message}
          </div>
        )}
        <div className="space-y-3">
          <div>
            <label className="label">Nouvelle clé API</label>
            <div className="flex gap-2">
              <input className="input flex-1 font-mono" type={showCle ? 'text' : 'password'}
                placeholder="Collez votre clé API Karlia ici" value={nouvelleClé}
                onChange={e => setNouvelleClé(e.target.value)} />
              <button type="button" className="btn-secondary px-3" onClick={() => setShowCle(s => !s)}>
                {showCle ? '🙈' : '👁'}
              </button>
            </div>
          </div>
          <button onClick={sauvegarderCle} disabled={saving || !nouvelleClé} className="btn-primary">
            {saving ? 'Enregistrement...' : '💾 Enregistrer la clé'}
          </button>
        </div>
      </div>

      {/* Chorus Pro */}
      <div className="card space-y-4">
        <h2 className="font-semibold text-gray-900 border-b pb-2">📤 Chorus Pro (Facturation collectivités)</h2>
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-sm text-blue-800">
          💡 Pour configurer Chorus Pro : créez un compte sur <a href="https://developer.aife.economie.gouv.fr" target="_blank" rel="noreferrer" className="underline">PISTE</a>, 
          puis un compte technique sur <a href="https://chorus-pro.gouv.fr" target="_blank" rel="noreferrer" className="underline">Chorus Pro</a>.
        </div>
        
        <div className="space-y-3">
          {PARAMS_CHORUS.map(p => (
            <div key={p.cle}>
              <label className="label">{p.label}</label>
              <input 
                className="input font-mono text-sm" 
                type={p.type}
                placeholder={p.placeholder}
                value={chorusParams[p.cle] || ''}
                onChange={e => handleChorusChange(p.cle, e.target.value)}
              />
            </div>
          ))}
          
          <div>
            <label className="label">Mode</label>
            <select 
              className="input" 
              value={chorusMode} 
              onChange={e => setChorusMode(e.target.value)}
            >
              <option value="true">🧪 Qualification (test)</option>
              <option value="false">🚀 Production</option>
            </select>
          </div>
        </div>

        {chorusTestResult && (
          <div className={'rounded-lg px-4 py-3 text-sm ' + (chorusTestResult.ok ? 'bg-green-50 border border-green-200 text-green-800' : 'bg-red-50 border border-red-200 text-red-800')}>
            {chorusTestResult.ok ? '✅' : '❌'} {chorusTestResult.ok ? `Connexion OK (${chorusTestResult.mode})` : (chorusTestResult.error || 'Erreur de connexion')}
          </div>
        )}

        <div className="flex gap-3">
          <button onClick={sauvegarderChorus} disabled={chorusSaving} className="btn-primary">
            {chorusSaving ? 'Enregistrement...' : '💾 Enregistrer'}
          </button>
          <button onClick={testerChorusConnexion} disabled={chorusTesting} className="btn-secondary">
            {chorusTesting ? '⏳ Test...' : '🔌 Tester la connexion'}
          </button>
        </div>
      </div>

      {/* Modèles de contrats */}
      <div className="card space-y-4">
        <h2 className="font-semibold text-gray-900 border-b pb-2">📄 Modèles de contrats Word</h2>

        {/* Upload */}
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 space-y-3">
          <p className="text-sm font-medium text-blue-800">Ajouter ou remplacer un modèle</p>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">Type de contrat</label>
              <select className="input" value={uploadType} onChange={e => setUploadType(e.target.value)}>
                {TYPES_MODELES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
              </select>
            </div>
            <div>
              <label className="label">Version</label>
              <input className="input" value={uploadVersion} onChange={e => setUploadVersion(e.target.value)} placeholder="ex: 1.0" />
            </div>
          </div>
          <div>
            <label className="label">Nom du modèle</label>
            <input className="input" value={uploadNom} onChange={e => setUploadNom(e.target.value)} placeholder="ex: Contrat Cosoluce 2026" />
          </div>
          <div>
            <label className="label">Fichier .docx</label>
            <input ref={fileRef} type="file" accept=".docx" className="block w-full text-sm text-gray-600 file:mr-3 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-medium file:bg-blue-100 file:text-blue-700 hover:file:bg-blue-200 cursor-pointer" />
          </div>
          <button onClick={uploaderModele} disabled={uploading} className="btn-primary text-sm disabled:opacity-50">
            {uploading ? '⏳ Upload en cours...' : '⬆ Uploader et activer ce modèle'}
          </button>
        </div>

        {/* Liste des modèles */}
        {modelesParType.length === 0 ? (
          <p className="text-sm text-gray-400 italic">Aucun modèle enregistré en base. Les fichiers présents dans /app/storage/modeles/ sont utilisés en fallback.</p>
        ) : (
          <div className="space-y-4">
            {modelesParType.map(type => (
              <div key={type.value}>
                <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">{type.label}</p>
                <div className="space-y-2">
                  {type.modeles.map(m => (
                    <div key={m.id} className={'flex items-center justify-between p-3 rounded-lg border ' + (m.actif ? 'bg-green-50 border-green-200' : 'bg-gray-50 border-gray-100')}>
                      <div>
                        <p className="text-sm font-medium text-gray-800">{m.nom} <span className="text-xs text-gray-400">v{m.version}</span></p>
                        <p className="text-xs text-gray-400">
                          {m.actif ? '✅ Actif' : '⬜ Inactif'} · uploadé par {m.uploaded_by}
                          {m.uploaded_at ? ' le ' + new Date(m.uploaded_at).toLocaleDateString('fr-FR') : ''}
                        </p>
                      </div>
                      <div className="flex gap-2">
                        {!m.actif && (
                          <button onClick={() => activerModele(m.id)} className="btn-secondary text-xs">✅ Activer</button>
                        )}
                        <button onClick={() => supprimerModele(m.id, m.nom)} className="btn-danger text-xs">🗑</button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Cache et synchronisation */}
      <div className="card space-y-4">
        <h2 className="font-semibold text-gray-900 border-b pb-2">🔄 Cache et synchronisation</h2>
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div className="bg-gray-50 rounded-lg px-4 py-3">
            <div className="text-gray-500">Dernière synchronisation</div>
            <div className="font-medium text-gray-900 mt-1">{params?.derniere_synchro || 'Jamais'}</div>
          </div>
          <div className="bg-gray-50 rounded-lg px-4 py-3">
            <div className="text-gray-500">Données synchronisées</div>
            <div className="font-medium text-gray-900 mt-1">{params?.synchro_stats || '—'}</div>
          </div>
        </div>
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 text-sm text-yellow-800">
          ⚠️ Pour tester avec une base Karlia différente : <strong>1)</strong> Changez la clé API ci-dessus, <strong>2)</strong> Videz le cache, <strong>3)</strong> Lancez la synchronisation.
        </div>
        <div className="flex gap-3">
          <button onClick={lancerSynchro} disabled={synchroLoading} className="btn-primary">
            {synchroLoading ? '⏳ Synchronisation...' : '🔄 Synchroniser maintenant'}
          </button>
          <button onClick={viderCache} disabled={viding} className="btn-danger">
            {viding ? 'Vidage...' : '🗑️ Vider le cache'}
          </button>
        </div>
      </div>

      {/* Informations */}
      <div className="card space-y-2">
        <h2 className="font-semibold text-gray-900 border-b pb-2">ℹ️ Informations</h2>
        <div className="text-sm text-gray-600 space-y-1">
          <div className="flex justify-between"><span>Version du module</span><span className="font-medium">1.4.0</span></div>
          <div className="flex justify-between"><span>Synchro nocturne</span><span className="font-medium">Chaque nuit à 2h00</span></div>
          <div className="flex justify-between"><span>Quota API Karlia</span><span className="font-medium">100 req/min</span></div>
        </div>
      </div>
    </div>
  );
}
