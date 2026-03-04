import React, { useState, useEffect } from 'react';
import api from '../services/api';
import toast from 'react-hot-toast';

const ROLES = [
  { value: 'ADMIN', label: 'Administrateur', color: 'bg-red-100 text-red-800', description: 'Accès total + gestion utilisateurs' },
  { value: 'GESTIONNAIRE', label: 'Gestionnaire', color: 'bg-blue-100 text-blue-800', description: 'Contrats + facturation + indices' },
  { value: 'CONSULTANT', label: 'Consultant', color: 'bg-gray-100 text-gray-700', description: 'Lecture seule' },
];

const roleInfo = (role) => ROLES.find(r => r.value === role) || ROLES[2];

export default function Utilisateurs() {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editUser, setEditUser] = useState(null);
  const [form, setForm] = useState({ login: '', email: '', nom_complet: '', role: 'CONSULTANT', password: '', actif: true });
  const [saving, setSaving] = useState(false);

  const charger = () => {
    setLoading(true);
    api.get('/api/utilisateurs').then(r => setUsers(r.data.data || [])).finally(() => setLoading(false));
  };

  useEffect(() => { charger(); }, []);

  const ouvrir = (user = null) => {
    if (user) {
      setEditUser(user);
      setForm({ login: user.login, email: user.email, nom_complet: user.nom_complet || '', role: user.role, password: '', actif: user.actif });
    } else {
      setEditUser(null);
      setForm({ login: '', email: '', nom_complet: '', role: 'CONSULTANT', password: '', actif: true });
    }
    setShowForm(true);
  };

  const sauvegarder = async () => {
    if (!form.email || (!editUser && !form.password)) {
      toast.error('Email et mot de passe obligatoires');
      return;
    }
    if (!editUser && !form.login) {
      toast.error('Login obligatoire');
      return;
    }
    setSaving(true);
    try {
      if (editUser) {
        await api.put(`/api/utilisateurs/${editUser.id}`, form);
        toast.success('Utilisateur mis à jour');
      } else {
        await api.post('/api/utilisateurs', form);
        toast.success('Utilisateur créé');
      }
      setShowForm(false);
      charger();
    } catch (e) { toast.error(e.response?.data?.detail || 'Erreur'); }
    finally { setSaving(false); }
  };

  const supprimer = async (user) => {
    if (!window.confirm(`Supprimer l'utilisateur ${user.login} ?`)) return;
    try {
      await api.delete(`/api/utilisateurs/${user.id}`);
      toast.success('Utilisateur supprimé');
      charger();
    } catch (e) { toast.error(e.response?.data?.detail || 'Erreur'); }
  };

  const toggleActif = async (user) => {
    try {
      await api.put(`/api/utilisateurs/${user.id}`, { actif: !user.actif });
      toast.success(user.actif ? 'Utilisateur désactivé' : 'Utilisateur activé');
      charger();
    } catch (e) { toast.error('Erreur'); }
  };

  return (
    <div className="space-y-6 max-w-4xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Utilisateurs</h1>
          <p className="text-gray-500 text-sm mt-1">Gestion des accès et des droits</p>
        </div>
        <button onClick={() => ouvrir()} className="btn-primary">➕ Nouvel utilisateur</button>
      </div>

      {/* Légende des rôles */}
      <div className="grid grid-cols-3 gap-4">
        {ROLES.map(r => (
          <div key={r.value} className="card p-3">
            <span className={`px-2 py-0.5 rounded text-xs font-medium ${r.color}`}>{r.label}</span>
            <p className="text-xs text-gray-500 mt-1">{r.description}</p>
          </div>
        ))}
      </div>

      {/* Formulaire */}
      {showForm && (
        <div className="card space-y-4 border-2 border-blue-200">
          <h2 className="font-semibold text-gray-900 border-b pb-2">
            {editUser ? `Modifier — ${editUser.login}` : 'Nouvel utilisateur'}
          </h2>
          <div className="grid grid-cols-2 gap-4">
            {!editUser && (
              <div>
                <label className="label">Login *</label>
                <input className="input" placeholder="ex: jdupont" value={form.login}
                  onChange={e => setForm(f => ({ ...f, login: e.target.value }))} />
              </div>
            )}
            <div>
              <label className="label">Nom complet</label>
              <input className="input" placeholder="Jean Dupont" value={form.nom_complet}
                onChange={e => setForm(f => ({ ...f, nom_complet: e.target.value }))} />
            </div>
            <div>
              <label className="label">Email *</label>
              <input className="input" type="email" value={form.email}
                onChange={e => setForm(f => ({ ...f, email: e.target.value }))} />
            </div>
            <div>
              <label className="label">Rôle *</label>
              <select className="input" value={form.role} onChange={e => setForm(f => ({ ...f, role: e.target.value }))}>
                {ROLES.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
              </select>
            </div>
            <div>
              <label className="label">{editUser ? 'Nouveau mot de passe (laisser vide = inchangé)' : 'Mot de passe *'}</label>
              <input className="input" type="password" value={form.password}
                onChange={e => setForm(f => ({ ...f, password: e.target.value }))} />
            </div>
            {editUser && (
              <div className="flex items-center gap-3 mt-6">
                <label className="label mb-0">Compte actif</label>
                <input type="checkbox" checked={form.actif}
                  onChange={e => setForm(f => ({ ...f, actif: e.target.checked }))} className="w-4 h-4" />
              </div>
            )}
          </div>
          <div className="flex gap-3">
            <button onClick={sauvegarder} disabled={saving} className="btn-primary">
              {saving ? 'Enregistrement...' : '💾 Enregistrer'}
            </button>
            <button onClick={() => setShowForm(false)} className="btn-secondary">Annuler</button>
          </div>
        </div>
      )}

      {/* Liste */}
      {loading ? (
        <div className="text-center text-gray-400 py-8">Chargement...</div>
      ) : (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-gray-500 border-b">
                <th className="pb-3">Utilisateur</th>
                <th className="pb-3">Email</th>
                <th className="pb-3">Rôle</th>
                <th className="pb-3">Statut</th>
                <th className="pb-3">Dernière connexion</th>
                <th className="pb-3">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {users.map(u => {
                const ri = roleInfo(u.role);
                return (
                  <tr key={u.id} className={`hover:bg-gray-50 ${!u.actif ? 'opacity-50' : ''}`}>
                    <td className="py-3">
                      <div className="font-medium">{u.nom_complet || u.login}</div>
                      <div className="text-xs text-gray-400">{u.login}</div>
                    </td>
                    <td className="py-3 text-gray-600">{u.email}</td>
                    <td className="py-3">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${ri.color}`}>{ri.label}</span>
                    </td>
                    <td className="py-3">
                      <button onClick={() => toggleActif(u)}
                        className={`px-2 py-0.5 rounded text-xs font-medium ${u.actif ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-500'}`}>
                        {u.actif ? '✅ Actif' : '⏸ Inactif'}
                      </button>
                    </td>
                    <td className="py-3 text-gray-500 text-xs">
                      {u.derniere_connexion ? new Date(u.derniere_connexion).toLocaleDateString('fr-FR') : '—'}
                    </td>
                    <td className="py-3">
                      <div className="flex gap-2">
                        <button onClick={() => ouvrir(u)} className="text-blue-600 hover:text-blue-800 text-xs">✏️ Modifier</button>
                        <button onClick={() => supprimer(u)} className="text-red-400 hover:text-red-600 text-xs">🗑️</button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
