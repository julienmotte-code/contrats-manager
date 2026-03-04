import React, { useState, useEffect } from 'react';
import api from '../services/api';
import toast from 'react-hot-toast';

const MOIS_OPTIONS = [
  { value: 'AOUT', label: 'Août' },
  { value: 'OCTOBRE', label: 'Octobre' },
  { value: 'AUTRE', label: 'Autre' },
];

export default function Indices() {
  const [indices, setIndices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filtreMois, setFiltreMois] = useState('');
  const [filtreAnnee, setFiltreAnnee] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ annee: new Date().getFullYear(), mois: 'AOUT', valeur: '', commentaire: '' });
  const [saving, setSaving] = useState(false);
  const [editId, setEditId] = useState(null);
  const [editValeur, setEditValeur] = useState('');

  const charger = () => {
    setLoading(true);
    const params = new URLSearchParams();
    if (filtreMois) params.append('mois', filtreMois);
    if (filtreAnnee) params.append('annee', filtreAnnee);
    api.get(`/api/indices?${params}`).then(r => setIndices(r.data.data || [])).finally(() => setLoading(false));
  };

  useEffect(() => { charger(); }, [filtreMois, filtreAnnee]);

  const sauvegarder = async () => {
    if (!form.valeur) { toast.error('Valeur obligatoire'); return; }
    setSaving(true);
    try {
      await api.post('/api/indices', form);
      toast.success('Indice ajouté');
      setShowForm(false);
      setForm({ annee: new Date().getFullYear(), mois: 'AOUT', valeur: '', commentaire: '' });
      charger();
    } catch (e) { toast.error(e.response?.data?.detail || 'Erreur'); }
    finally { setSaving(false); }
  };

  const modifier = async (id) => {
    try {
      await api.put(`/api/indices/${id}`, { valeur: parseFloat(editValeur) });
      toast.success('Indice mis à jour');
      setEditId(null);
      charger();
    } catch (e) { toast.error('Erreur'); }
  };

  const supprimer = async (id) => {
    if (!window.confirm('Supprimer cet indice ?')) return;
    try {
      await api.delete(`/api/indices/${id}`);
      toast.success('Indice supprimé');
      charger();
    } catch (e) { toast.error('Erreur'); }
  };

  // Grouper par année
  const parAnnee = indices.reduce((acc, i) => {
    if (!acc[i.annee]) acc[i.annee] = [];
    acc[i.annee].push(i);
    return acc;
  }, {});

  return (
    <div className="space-y-6 max-w-4xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Indices Syntec</h1>
          <p className="text-gray-500 text-sm mt-1">Gestion des indices de révision annuelle</p>
        </div>
        <button onClick={() => setShowForm(s => !s)} className="btn-primary">
          {showForm ? 'Annuler' : '➕ Ajouter un indice'}
        </button>
      </div>

      {showForm && (
        <div className="card space-y-4">
          <h2 className="font-semibold text-gray-900 border-b pb-2">Nouvel indice Syntec</h2>
          <div className="grid grid-cols-4 gap-4">
            <div>
              <label className="label">Année *</label>
              <input className="input" type="number" min="2000" max="2100" value={form.annee}
                onChange={e => setForm(f => ({ ...f, annee: parseInt(e.target.value) }))} />
            </div>
            <div>
              <label className="label">Mois *</label>
              <select className="input" value={form.mois} onChange={e => setForm(f => ({ ...f, mois: e.target.value }))}>
                {MOIS_OPTIONS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
              </select>
            </div>
            <div>
              <label className="label">Valeur *</label>
              <input className="input" type="number" step="0.01" placeholder="ex: 323.1"
                value={form.valeur} onChange={e => setForm(f => ({ ...f, valeur: e.target.value }))} />
            </div>
            <div>
              <label className="label">Commentaire</label>
              <input className="input" placeholder="Optionnel" value={form.commentaire}
                onChange={e => setForm(f => ({ ...f, commentaire: e.target.value }))} />
            </div>
          </div>
          <button onClick={sauvegarder} disabled={saving} className="btn-primary">
            {saving ? 'Enregistrement...' : '💾 Enregistrer'}
          </button>
        </div>
      )}

      {/* Filtres */}
      <div className="flex gap-4">
        <select className="input w-40" value={filtreMois} onChange={e => setFiltreMois(e.target.value)}>
          <option value="">Tous les mois</option>
          {MOIS_OPTIONS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
        </select>
        <input className="input w-32" type="number" placeholder="Année" value={filtreAnnee}
          onChange={e => setFiltreAnnee(e.target.value)} />
        {(filtreMois || filtreAnnee) && (
          <button className="btn-secondary text-sm" onClick={() => { setFiltreMois(''); setFiltreAnnee(''); }}>
            ✕ Réinitialiser
          </button>
        )}
      </div>

      {/* Tableau par année */}
      {loading ? (
        <div className="text-center text-gray-400 py-8">Chargement...</div>
      ) : Object.keys(parAnnee).length === 0 ? (
        <div className="text-center text-gray-400 py-8">Aucun indice enregistré</div>
      ) : (
        Object.keys(parAnnee).sort((a, b) => b - a).map(annee => (
          <div key={annee} className="card">
            <h3 className="font-semibold text-gray-900 mb-3 border-b pb-2">📅 {annee}</h3>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-gray-500 border-b">
                  <th className="pb-2">Mois</th>
                  <th className="pb-2">Valeur</th>
                  <th className="pb-2">Commentaire</th>
                  <th className="pb-2">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {parAnnee[annee].map(i => (
                  <tr key={i.id} className="py-2">
                    <td className="py-2">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${i.mois === 'AOUT' ? 'bg-blue-100 text-blue-800' : i.mois === 'OCTOBRE' ? 'bg-orange-100 text-orange-800' : 'bg-gray-100 text-gray-700'}`}>
                        {MOIS_OPTIONS.find(m => m.value === i.mois)?.label || i.mois}
                      </span>
                    </td>
                    <td className="py-2">
                      {editId === i.id ? (
                        <div className="flex gap-2 items-center">
                          <input className="input w-28 text-sm" type="number" step="0.01" value={editValeur}
                            onChange={e => setEditValeur(e.target.value)} />
                          <button onClick={() => modifier(i.id)} className="btn-primary text-xs px-2 py-1">✓</button>
                          <button onClick={() => setEditId(null)} className="btn-secondary text-xs px-2 py-1">✕</button>
                        </div>
                      ) : (
                        <span className="font-mono font-medium">{i.valeur}</span>
                      )}
                    </td>
                    <td className="py-2 text-gray-500">{i.commentaire || '—'}</td>
                    <td className="py-2">
                      <div className="flex gap-2">
                        <button onClick={() => { setEditId(i.id); setEditValeur(i.valeur); }} className="text-blue-600 hover:text-blue-800 text-xs">✏️</button>
                        <button onClick={() => supprimer(i.id)} className="text-red-400 hover:text-red-600 text-xs">🗑️</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))
      )}
    </div>
  );
}
