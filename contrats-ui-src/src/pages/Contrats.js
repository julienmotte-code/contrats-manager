import React, { useState, useEffect, useCallback } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { contratsAPI } from '../services/api';
import { useAuth } from '../context/AuthContext';
import { format } from 'date-fns';
import api from '../services/api';

// Familles accessibles au technicien
const FAMILLES_TECHNICIEN = ['MAINTENANCE', 'DIGITECH', 'KIWI_BACKUP'];

const ONGLETS = [
  { key: '',             label: 'Tous',        color: 'gray' },
  { key: 'EN_COURS',    label: 'En cours',     color: 'green' },
  { key: 'A_RENOUVELER',label: 'À renouveler', color: 'orange' },
  { key: 'BROUILLON',   label: 'Brouillon',    color: 'blue' },
  { key: 'TERMINE',     label: 'Terminés',     color: 'gray' },
];

function StatutBadge({ statut }) {
  const map = {
    EN_COURS:     <span className="badge-green">En cours</span>,
    A_RENOUVELER: <span className="badge-orange">À renouveler</span>,
    TERMINE:      <span className="badge-gray">Terminé</span>,
    BROUILLON:    <span className="badge-blue">Brouillon</span>,
  };
  return map[statut] || <span className="badge-gray">{statut}</span>;
}

export default function Contrats() {
  const { user } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const [contrats, setContrats] = useState([]);
  const [total, setTotal] = useState(0);
  const [compteurs, setCompteurs] = useState({});
  const [loading, setLoading] = useState(true);
  const [recherche, setRecherche] = useState('');
  const [ongletActif, setOngletActif] = useState('');
  const [page, setPage] = useState(0);
  const [famillesDisponibles, setFamillesDisponibles] = useState([]);
  const limit = 20;

  const isTechnicien = user?.role === 'TECHNICIEN';

  // Lire le filtre famille depuis l'URL ou le state
  const [filtreFamille, setFiltreFamille] = useState(searchParams.get('famille') || '');

  // Charger les familles disponibles
  useEffect(() => {
    api.get('/api/indices/familles').then(r => {
      setFamillesDisponibles(r.data.data || []);
    }).catch(() => {});
  }, []);

  // Calculer le paramètre familles pour l'API
  const famillesParam = isTechnicien
    ? FAMILLES_TECHNICIEN.join(',')
    : filtreFamille || undefined;

  const chargerCompteurs = useCallback(() => {
    const statuts = ['EN_COURS', 'A_RENOUVELER', 'BROUILLON', 'TERMINE'];
    Promise.all(
      statuts.map(s =>
        contratsAPI.liste({ statut: s, limit: 1, offset: 0, familles: famillesParam })
          .then(r => ({ statut: s, total: r.data.total || 0 }))
          .catch(() => ({ statut: s, total: 0 }))
      )
    ).then(results => {
      const c = {};
      results.forEach(r => { c[r.statut] = r.total; });
      c[''] = Object.values(c).reduce((a, b) => a + b, 0);
      setCompteurs(c);
    });
  }, [famillesParam]);

  const charger = useCallback(() => {
    setLoading(true);
    contratsAPI.liste({
      recherche: recherche || undefined,
      statut: ongletActif || undefined,
      limit,
      offset: page * limit,
      familles: famillesParam,
    })
      .then(r => {
        setContrats(r.data.data || []);
        setTotal(r.data.total || 0);
      })
      .finally(() => setLoading(false));
  }, [ongletActif, page, recherche, famillesParam]);

  useEffect(() => { chargerCompteurs(); }, [chargerCompteurs]);
  useEffect(() => { charger(); }, [charger]);

  // Synchroniser le filtre famille avec l'URL
  const changerFamille = (code) => {
    setFiltreFamille(code);
    setPage(0);
    if (code) {
      setSearchParams({ famille: code });
    } else {
      setSearchParams({});
    }
  };

  const handleRecherche = (e) => {
    e.preventDefault();
    setPage(0);
    charger();
  };

  const changerOnglet = (key) => {
    setOngletActif(key);
    setPage(0);
    setRecherche('');
  };

  const ongletStyle = (onglet) => {
    const actif = onglet.key === ongletActif;
    const base = 'flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors whitespace-nowrap cursor-pointer';
    if (!actif) return `${base} border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300`;
    const colors = {
      green:  'border-green-500 text-green-700',
      orange: 'border-orange-500 text-orange-700',
      blue:   'border-blue-500 text-blue-700',
      gray:   'border-gray-700 text-gray-900',
    };
    return `${base} ${colors[onglet.color] || colors.gray}`;
  };

  const badgeStyle = (onglet) => {
    const actif = onglet.key === ongletActif;
    if (!actif) return 'bg-gray-100 text-gray-500 text-xs rounded-full px-2 py-0.5 font-medium';
    const colors = {
      green:  'bg-green-100 text-green-700',
      orange: 'bg-orange-100 text-orange-700',
      blue:   'bg-blue-100 text-blue-700',
      gray:   'bg-gray-200 text-gray-700',
    };
    return `${colors[onglet.color] || colors.gray} text-xs rounded-full px-2 py-0.5 font-medium`;
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">
            {isTechnicien ? 'Contrats techniques' : 'Contrats'}
            {filtreFamille && !isTechnicien && (
              <span className="text-lg font-normal text-gray-500 ml-2">
                — {famillesDisponibles.find(f => f.code === filtreFamille)?.label || filtreFamille}
              </span>
            )}
          </h1>
          <p className="text-gray-500 text-sm mt-1">
            {total} contrat(s)
            {isTechnicien && ' — Maintenance, Digitech, Kiwi Backup'}
          </p>
        </div>
        {!isTechnicien && (
          <Link to="/contrats/nouveau" className="btn-primary">➕ Nouveau contrat</Link>
        )}
      </div>

      <div className="border-b border-gray-200">
        <nav className="flex gap-1 overflow-x-auto">
          {ONGLETS.map(onglet => (
            <button
              key={onglet.key}
              onClick={() => changerOnglet(onglet.key)}
              className={ongletStyle(onglet)}
            >
              {onglet.label}
              {compteurs[onglet.key] !== undefined && (
                <span className={badgeStyle(onglet)}>
                  {compteurs[onglet.key]}
                </span>
              )}
            </button>
          ))}
        </nav>
      </div>

      <div className="card">
        <div className="flex gap-3 items-end">
          <form onSubmit={handleRecherche} className="flex gap-3 flex-1">
            <input
              className="input flex-1"
              placeholder="🔍 Rechercher par numéro, client..."
              value={recherche}
              onChange={e => setRecherche(e.target.value)}
            />
            <button type="submit" className="btn-primary">Rechercher</button>
            {recherche && (
              <button type="button" className="btn-secondary" onClick={() => { setRecherche(''); setPage(0); }}>
                ✕
              </button>
            )}
          </form>
          {!isTechnicien && (
            <div className="flex items-center gap-2">
              <select
                className="input py-2 text-sm"
                value={filtreFamille}
                onChange={e => changerFamille(e.target.value)}
              >
                <option value="">Toutes les familles</option>
                {famillesDisponibles.map(f => (
                  <option key={f.code} value={f.code}>{f.label}</option>
                ))}
              </select>
              {filtreFamille && (
                <button
                  type="button"
                  className="text-gray-400 hover:text-gray-600 text-sm"
                  onClick={() => changerFamille('')}
                  title="Réinitialiser le filtre"
                >
                  ✕
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="card overflow-x-auto p-0">
        {loading ? (
          <div className="text-center text-gray-400 py-12">Chargement...</div>
        ) : contrats.length === 0 ? (
          <div className="text-center text-gray-400 py-12">
            Aucun contrat
            {ongletActif && ` dans "${ONGLETS.find(o => o.key === ongletActif)?.label}"`}
            {recherche && ` pour "${recherche}"`}
            {filtreFamille && ` (famille: ${filtreFamille})`}
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-gray-500 border-b border-gray-200 bg-gray-50">
                <th className="px-4 py-3 font-medium">N° Contrat</th>
                <th className="px-4 py-3 font-medium">Client</th>
                <th className="px-4 py-3 font-medium">Famille</th>
                <th className="px-4 py-3 font-medium">Début</th>
                <th className="px-4 py-3 font-medium">Fin</th>
                <th className="px-4 py-3 font-medium text-right">Montant annuel HT</th>
                <th className="px-4 py-3 font-medium text-center">Statut</th>
                <th className="px-4 py-3 font-medium text-center">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {contrats.map(c => (
                <tr key={c.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3 font-medium text-gray-900">{c.numero_contrat}</td>
                  <td className="px-4 py-3 text-gray-700">{c.client_nom}</td>
                  <td className="px-4 py-3 text-gray-600 text-xs">{c.famille_contrat || '-'}</td>
                  <td className="px-4 py-3 text-gray-600">
                    {c.date_debut ? format(new Date(c.date_debut + 'T12:00:00'), 'dd/MM/yyyy') : '-'}
                  </td>
                  <td className="px-4 py-3 text-gray-600">
                    {c.date_fin ? format(new Date(c.date_fin + 'T12:00:00'), 'dd/MM/yyyy') : '-'}
                  </td>
                  <td className="px-4 py-3 text-right font-medium text-gray-900">
                    {c.montant_annuel_ht?.toLocaleString('fr-FR', { minimumFractionDigits: 2 })} €
                  </td>
                  <td className="px-4 py-3 text-center"><StatutBadge statut={c.statut} /></td>
                  <td className="px-4 py-3 text-center">
                    <Link to={`/contrats/${c.id}`} className="text-blue-600 hover:text-blue-800 font-medium">
                      👁 Voir
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {total > limit && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-gray-200 bg-gray-50">
            <span className="text-sm text-gray-600">
              {page * limit + 1}–{Math.min((page + 1) * limit, total)} sur {total}
            </span>
            <div className="flex gap-2">
              <button className="btn-secondary py-1 px-3 text-xs" disabled={page === 0} onClick={() => setPage(p => p - 1)}>← Préc.</button>
              <button className="btn-secondary py-1 px-3 text-xs" disabled={(page + 1) * limit >= total} onClick={() => setPage(p => p + 1)}>Suiv. →</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
