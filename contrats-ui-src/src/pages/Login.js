import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
export default function Login() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();
  const handleSubmit = async (e) => {
    e.preventDefault(); setError(''); setLoading(true);
    try { await login(username, password); navigate('/'); }
    catch { setError('Identifiants incorrects'); }
    finally { setLoading(false); }
  };
  return (
    <div className="min-h-screen bg-blue-900 flex items-center justify-center">
      <div className="bg-white rounded-2xl shadow-2xl p-8 w-full max-w-md">
        <div className="text-center mb-8">
          <div className="text-5xl mb-4">📋</div>
          <h1 className="text-2xl font-bold text-gray-900">Gestion des Contrats</h1>
          <p className="text-gray-500 text-sm mt-1">Module complémentaire Karlia</p>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div><label className="label">Identifiant</label><input className="input" type="text" value={username} onChange={e => setUsername(e.target.value)} placeholder="Votre login" required /></div>
          <div><label className="label">Mot de passe</label><input className="input" type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="Votre mot de passe" required /></div>
          {error && <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm">{error}</div>}
          <button type="submit" disabled={loading} className="btn-primary w-full py-3 text-base">{loading ? 'Connexion...' : 'Se connecter'}</button>
        </form>
      </div>
    </div>
  );
}
