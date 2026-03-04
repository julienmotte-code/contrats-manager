import React, { useState, useEffect } from 'react';
import api from '../services/api';
import toast from 'react-hot-toast';

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

  const charger = () => {
    setLoading(true);
    api.get('/api/parametres/').then(r => setParams(r.data)).finally(() => setLoading(false));
  };

  useEffect(() => { charger(); }, []);

  const sauvegarderCle = async () => {
    if (!nouvelleClé) { toast.error('Saisissez une clé API'); return; }
    setSaving(true);
    try {
      await api.put('/api/parametres/karlia-api-key', { valeur: nouvelleClé });
      toast.success('Clé API mise à jour');
      setNouvelleClé('');
      setShowCle(false);
      charger();
    } catch (e) { toast.error(e.response?.data?.detail || 'Erreur'); }
    finally { setSaving(false); }
  };

  const testerConnexion = async () => {
    setTesting(true);
    setTestResult(null);
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
      toast.success(r.data.message);
      charger();
    } catch (e) { toast.error(e.response?.data?.detail || 'Erreur'); }
    finally { setViding(false); }
  };

  const lancerSynchro = async () => {
    setSynchroLoading(true);
    try {
      await api.post('/api/synchro/lancer');
      toast.success('Synchronisation terminée');
      charger();
    } catch (e) { toast.error('Erreur synchronisation'); }
    finally { setSynchroLoading(false); }
  };

  if (loading) return <div className="flex items-center justify-center h-64 text-gray-400">Chargement...</div>;

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Paramètres</h1>
        <p className="text-gray-500 text-sm mt-1">Configuration du module et connexion Karlia</p>
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
          <div className={`rounded-lg px-4 py-3 text-sm ${testResult.succes ? 'bg-green-50 border border-green-200 text-green-800' : 'bg-red-50 border border-red-200 text-red-800'}`}>
            {testResult.succes ? '✅' : '❌'} {typeof testResult.message === 'object' ? JSON.stringify(testResult.message) : testResult.message}
          </div>
        )}

        <div className="space-y-3">
          <div>
            <label className="label">Nouvelle clé API</label>
            <div className="flex gap-2">
              <input
                className="input flex-1 font-mono"
                type={showCle ? 'text' : 'password'}
                placeholder="Collez votre clé API Karlia ici"
                value={nouvelleClé}
                onChange={e => setNouvelleClé(e.target.value)}
              />
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
          <div className="flex justify-between"><span>Version du module</span><span className="font-medium">1.0.0</span></div>
          <div className="flex justify-between"><span>Synchro nocturne</span><span className="font-medium">Chaque nuit à 2h00</span></div>
          <div className="flex justify-between"><span>Quota API Karlia</span><span className="font-medium">100 req/min</span></div>
        </div>
      </div>
    </div>
  );
}
