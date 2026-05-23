import React, { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import api from '../services/api';
import { useAuth } from '../context/AuthContext';
import { format } from 'date-fns';
import { fr } from 'date-fns/locale';

const TUILES = [
  { key: 'a_planifier', label: 'À planifier', icon: '📅', color: 'bg-amber-50 text-amber-700', to: '/mes-prestations?tab=a_planifier' },
  { key: 'planifiees',  label: 'Planifiées',  icon: '🗓️', color: 'bg-blue-50 text-blue-700',   to: '/mes-prestations?tab=planifiee' },
  { key: 'realisees',   label: 'Réalisées',   icon: '✅', color: 'bg-green-50 text-green-700',  to: '/mes-prestations?tab=realisee' },
];

function PrestationCard({ tuile, count }) {
  return (
    <Link to={tuile.to} className={`block p-4 rounded-xl transition-all hover:shadow-md ${tuile.color}`}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-2xl">{tuile.icon}</span>
        <span className="text-2xl font-bold">{count}</span>
      </div>
      <div className="text-sm font-medium">{tuile.label}</div>
    </Link>
  );
}

export default function DashboardFormateur() {
  const { user } = useAuth();
  const [stats, setStats] = useState({ a_planifier: 0, planifiees: 0, realisees: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchStats = useCallback(async () => {
    if (!user?.formateur_id) {
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const res = await api.get(`/api/prestations/formateur/${user.formateur_id}`);
      setStats({
        a_planifier: res.data.a_planifier || 0,
        planifiees: res.data.planifiees || 0,
        realisees: res.data.realisees || 0,
      });
      setError(null);
    } catch (err) {
      console.error('Erreur chargement prestations:', err);
      setError('Erreur lors du chargement des prestations');
    } finally {
      setLoading(false);
    }
  }, [user?.formateur_id]);

  useEffect(() => {
    fetchStats();
  }, [fetchStats]);

  if ((user?.role === 'FORMATEUR' || user?.role === 'TECHNICIEN') && !user?.formateur_id) {
    return (
      <div className="space-y-6">
        <div className="card bg-amber-50 border-amber-200 text-amber-800">
          Votre compte n'est pas associé à un profil formateur. Contactez un administrateur.
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400 text-lg">
        Chargement...
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Tableau de bord</h1>
        <p className="text-gray-500 text-sm mt-1">{format(new Date(), "EEEE d MMMM yyyy", { locale: fr })}</p>
      </div>

      {error && (
        <div className="card bg-red-50 border-red-200 text-red-700 text-sm">{error}</div>
      )}

      <div className="card">
        <h2 className="font-semibold text-gray-900 mb-4">📋 Mes prestations</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {TUILES.map(t => <PrestationCard key={t.key} tuile={t} count={stats[t.key]} />)}
        </div>
      </div>
    </div>
  );
}
