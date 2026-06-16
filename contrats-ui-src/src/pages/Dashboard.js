import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import api, { dashboardAPI, indicesAPI } from '../services/api';
import { format } from 'date-fns';
import { fr } from 'date-fns/locale';
import { useAuth } from '../context/AuthContext';

// ─── Libellés et icônes par famille de contrat ────────────────
const FAMILLE_META = {
  COSOLUCE:        { icon: '🏛️', color: 'bg-blue-50 text-blue-700 border-blue-200' },
  MAINTENANCE:     { icon: '🛠️', color: 'bg-amber-50 text-amber-700 border-amber-200' },
  KIWI_BACKUP:     { icon: '💾', color: 'bg-purple-50 text-purple-700 border-purple-200' },
  DIGITECH:        { icon: '💻', color: 'bg-cyan-50 text-cyan-700 border-cyan-200' },
  AUTRE:           { icon: '📦', color: 'bg-gray-50 text-gray-700 border-gray-200' },
  CANTINE:         { icon: '🍽️', color: 'bg-orange-50 text-orange-700 border-orange-200' },
  ASSISTANCE_TEL:  { icon: '📞', color: 'bg-green-50 text-green-700 border-green-200' },
};
const FAMILLE_DEFAULT = { icon: '📄', color: 'bg-slate-50 text-slate-700 border-slate-200' };

// ─── Statuts de commande (libellé + couleur + lien) ──────────
const STATUT_COMMANDE = {
  nouvelles:   { label: 'Nouvelles',   color: 'bg-blue-50 text-blue-700',   link: '/commandes/nouvelles',   icon: '🆕' },
  a_planifier: { label: 'À planifier', color: 'bg-amber-50 text-amber-700', link: '/commandes/a-planifier', icon: '📅' },
  planifiees:  { label: 'Planifiées',  color: 'bg-green-50 text-green-700', link: '/commandes/planifiees',  icon: '✅' },
};

// ─── Composants ──────────────────────────────────────────────
function KPI({ label, value, icon, color }) {
  return (
    <div className="card flex items-center gap-4">
      <div className={`text-3xl p-3 rounded-xl ${color}`}>{icon}</div>
      <div>
        <div className="text-2xl font-bold text-gray-900">{value}</div>
        <div className="text-sm text-gray-500">{label}</div>
      </div>
    </div>
  );
}

function FamilleCard({ famille }) {
  const meta = FAMILLE_META[famille.code] || FAMILLE_DEFAULT;
  const montant = (famille.montant_annuel_ht || 0).toLocaleString('fr-FR', { maximumFractionDigits: 0 });
  // Un avenant = numéro de contrat commençant par "AV". Le gros chiffre
  // affiche les contrats HORS avenants ; les avenants sont en mention secondaire.
  const nbContrats = famille.nb_contrats != null ? famille.nb_contrats : famille.total;
  const nbAvenants = famille.nb_avenants || 0;
  return (
    <Link
      to={`/contrats?famille=${encodeURIComponent(famille.code)}`}
      className={`block p-4 rounded-xl border transition-all hover:shadow-md ${meta.color}`}
    >
      <div className="flex items-center justify-between mb-2">
        <span className="text-2xl">{meta.icon}</span>
        <span className="text-2xl font-bold">{nbContrats}</span>
      </div>
      <div className="text-sm font-medium truncate">{famille.label}</div>
      <div className="flex items-center justify-between gap-2 mt-1">
        <span className="text-xs opacity-75">{montant} € HT/an</span>
        {nbAvenants > 0 && (
          <span className="text-xs font-medium opacity-90 whitespace-nowrap">
            + {nbAvenants} avenant{nbAvenants > 1 ? 's' : ''}
          </span>
        )}
      </div>
    </Link>
  );
}

function CommandeStatutCard({ statut, count }) {
  const meta = STATUT_COMMANDE[statut] || { label: statut, color: 'bg-gray-50 text-gray-700', link: '/', icon: '📋' };
  return (
    <Link
      to={meta.link}
      className={`block p-4 rounded-xl transition-all hover:shadow-md ${meta.color}`}
    >
      <div className="flex items-center justify-between mb-2">
        <span className="text-2xl">{meta.icon}</span>
        <span className="text-2xl font-bold">{count}</span>
      </div>
      <div className="text-sm font-medium">{meta.label}</div>
    </Link>
  );
}

// Pastille d'état d'une étape de synchro
function Etape({ label, etat }) {
  const icone = etat === 'ok' ? '✓' : etat === 'erreur' ? '✗' : etat === 'cours' ? '⏳' : '○';
  const couleur = etat === 'ok' ? 'text-green-600' : etat === 'erreur' ? 'text-red-600' : etat === 'cours' ? 'text-blue-600' : 'text-gray-400';
  return (
    <div className={`flex items-center gap-2 text-sm ${couleur}`}>
      <span className="w-4 text-center">{icone}</span>
      <span>{label}{etat === 'cours' ? '…' : ''}</span>
    </div>
  );
}

// ─── Bannière SIRET repliable (intitulé + 3 lignes max) ──────
const LIMITE_SIRET = 3;

function BanniereSiret({ titre, intro, items, couleur, renduLigne }) {
  const [ouvert, setOuvert] = useState(false);
  const palette = couleur === 'red'
    ? { border: 'border-red-300', bg: 'bg-red-50', text: 'text-red-700' }
    : { border: 'border-amber-300', bg: 'bg-amber-50', text: 'text-amber-700' };
  const visibles = ouvert ? items : items.slice(0, LIMITE_SIRET);
  const reste = items.length - LIMITE_SIRET;
  return (
    <div className={`rounded-lg border ${palette.border} ${palette.bg} p-4`}>
      <p className={`font-semibold ${palette.text} mb-1`}>{titre}</p>
      {intro && <p className={`text-sm ${palette.text} mb-1`}>{intro}</p>}
      <ul className={`list-disc pl-5 space-y-0.5 text-sm ${palette.text}`}>
        {visibles.map((e, i) => <li key={i}>{renduLigne(e)}</li>)}
      </ul>
      {reste > 0 && (
        <button
          type="button"
          onClick={() => setOuvert(!ouvert)}
          className={`mt-2 text-sm font-medium underline ${palette.text}`}
        >
          {ouvert ? 'Afficher moins' : `Afficher plus (${reste} de plus)`}
        </button>
      )}
    </div>
  );
}

// ─── Page Dashboard ──────────────────────────────────────────
export default function Dashboard() {
  const { user } = useAuth();
  const peutSynchro = ['ADMIN', 'GESTIONNAIRE'].includes(user?.role);

  const [stats, setStats] = useState(null);
  const [indice, setIndice] = useState(null);
  const [loading, setLoading] = useState(true);
  const [synchroInfo, setSynchroInfo] = useState(null);
  const [synchroLoading, setSynchroLoading] = useState(false);
  const [etapes, setEtapes] = useState(null);

  const chargerStats = () => {
    dashboardAPI.stats()
      .then(r => setStats(r.data))
      .catch(e => console.error('Erreur stats dashboard:', e));
  };

  useEffect(() => {
    // 1. Date de dernière synchro Karlia (lecture seule, ne déclenche rien)
    api.get('/api/synchro/statut')
      .then(r => setSynchroInfo(r.data))
      .catch(() => {});

    // 2. Stats dashboard (appel principal)
    dashboardAPI.stats()
      .then(r => setStats(r.data))
      .catch(e => console.error('Erreur stats dashboard:', e))
      .finally(() => setLoading(false));

    // 3. Indice Syntec courant (indépendant)
    indicesAPI.courant()
      .then(r => setIndice(r.data))
      .catch(() => {});
  }, []);

  const lancerSynchro = async () => {
    setSynchroLoading(true);
    const init = { clients: 'cours', commandes: 'attente', factures: 'attente' };
    setEtapes(init);
    const opts = { timeout: 360000 };

    // Étape 1 : clients + articles
    try {
      await api.post('/api/synchro/lancer', null, opts);
      setEtapes(e => ({ ...e, clients: 'ok', commandes: 'cours' }));
    } catch (err) {
      console.error(err);
      setEtapes(e => ({ ...e, clients: 'erreur', commandes: 'cours' }));
    }

    // Étape 2 : bons de commande
    try {
      await api.post('/api/commandes/sync?force_full=false', null, opts);
      setEtapes(e => ({ ...e, commandes: 'ok', factures: 'cours' }));
    } catch (err) {
      console.error(err);
      setEtapes(e => ({ ...e, commandes: 'erreur', factures: 'cours' }));
    }

    // Étape 3 : factures Karlia (récupération pour Chorus)
    try {
      await api.post('/api/chorus/synchro-factures', null, opts);
      setEtapes(e => ({ ...e, factures: 'ok' }));
    } catch (err) {
      console.error(err);
      setEtapes(e => ({ ...e, factures: 'erreur' }));
    }

    // Rafraîchir la date de dernière synchro + les stats
    try {
      const r = await api.get('/api/synchro/statut');
      setSynchroInfo(r.data);
    } catch (_) {}
    chargerStats();
    setSynchroLoading(false);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400 text-lg">
        Chargement...
      </div>
    );
  }

  const contratsFamilles = stats?.contrats_par_famille || [];
  const commandes = stats?.commandes_par_statut || {};
  const totalContrats = stats?.total_contrats || 0;
  const caAnnuel = stats?.ca_annuel_ht || 0;
  const aRenouveler = stats?.a_renouveler_ce_mois || 0;

  return (
    <div className="space-y-6">
      {/* Bannière anomalies SIRET (dernière synchro Karlia) */}
      {stats?.siret_errors?.length > 0 && (() => {
        const malformed = stats.siret_errors.filter(e => e.type === 'malformed');
        const missing = stats.siret_errors.filter(e => e.type === 'missing');
        return (
          <div className="mb-4 space-y-3">
            {malformed.length > 0 && (
              <BanniereSiret
                couleur="red"
                titre={`SIRET mal formaté dans Karlia : ${malformed.length} client(s) non synchronisé(s)`}
                items={malformed}
                renduLigne={(e) => (
                  <>Le SIRET « {e.siret} » du client {e.nom} est mal formaté dans Karlia : sa fiche n'est plus
                  synchronisée. Corriger dans Karlia puis relancer la synchronisation.</>
                )}
              />
            )}
            {missing.length > 0 && (
              <BanniereSiret
                couleur="amber"
                titre={`SIRET manquant dans Karlia : ${missing.length} client(s) à compléter`}
                intro="Ces fiches sont synchronisées mais sans SIRET. À renseigner dans Karlia pour la facturation / Chorus Pro :"
                items={missing}
                renduLigne={(e) => e.nom}
              />
            )}
          </div>
        );
      })()}

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Tableau de bord</h1>
          <p className="text-gray-500 text-sm mt-1">{format(new Date(), "EEEE d MMMM yyyy", { locale: fr })}</p>
        </div>
        <div className="flex gap-3">
          <Link to="/contrats/tunnel?mode=nouveau" className="btn-primary">➕ Nouveau contrat</Link>
          <Link to="/indices" className="btn-secondary">📈 Saisir un indice</Link>
        </div>
      </div>

      {/* Bandeau synchro */}
      {peutSynchro && (
        <div className="bg-white border border-gray-200 rounded-xl px-5 py-3 flex items-center justify-between">
          <div className="text-sm text-gray-500">
            🔄 Dernière synchronisation Karlia :
            <span className="font-medium text-gray-700 ml-1">{synchroInfo?.derniere_synchro || 'Inconnue'}</span>
            {synchroInfo?.stats && <span className="text-gray-400 ml-2">({synchroInfo.stats})</span>}
          </div>
          <button onClick={lancerSynchro} disabled={synchroLoading} className="btn-secondary text-sm py-1.5">
            {synchroLoading ? '⏳ Synchronisation...' : '🔄 Synchroniser maintenant'}
          </button>
        </div>
      )}

      {/* Déroulé synchro en direct */}
      {peutSynchro && etapes && (
        <div className="bg-white border border-gray-200 rounded-xl px-5 py-3 space-y-1">
          <div className="text-xs font-medium text-gray-500 mb-1">Synchronisation en cours</div>
          <Etape label="Clients et articles" etat={etapes.clients} />
          <Etape label="Bons de commande" etat={etapes.commandes} />
          <Etape label="Factures" etat={etapes.factures} />
        </div>
      )}

      {/* KPI globaux */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <KPI
          label="Contrats actifs"
          value={totalContrats}
          icon="📄"
          color="bg-blue-50"
        />
        <KPI
          label="CA facturé HT (année en cours)"
          value={`${caAnnuel.toLocaleString('fr-FR', { maximumFractionDigits: 0 })} €`}
          icon="💶"
          color="bg-green-50"
        />
        <KPI
          label="À renouveler ce mois"
          value={aRenouveler}
          icon="⚠️"
          color="bg-orange-50"
        />
      </div>

      {stats?.ca_karlia_refreshed_at && (
        <p className="text-xs text-gray-400 mt-1">
          CA facturé (année en cours) — données Karlia du{' '}
          {new Date(stats.ca_karlia_refreshed_at).toLocaleString('fr-FR')}
          {stats.ca_karlia_stale && ' (non rafraîchi — Karlia indisponible)'}
        </p>
      )}

      {/* Contrats par famille */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-gray-900">📂 Contrats par famille</h2>
          <Link to="/contrats" className="text-blue-600 text-sm hover:underline">Voir tous les contrats →</Link>
        </div>
        {contratsFamilles.length === 0 ? (
          <p className="text-center text-gray-400 py-8 text-sm italic">Aucun contrat actif</p>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
            {contratsFamilles.map(f => (
              <FamilleCard key={f.code} famille={f} />
            ))}
          </div>
        )}
      </div>

      {/* État des commandes */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-gray-900">📦 État des commandes</h2>
          <span className="text-sm text-gray-500">
            {commandes.total || 0} commande{(commandes.total || 0) > 1 ? 's' : ''} au total
          </span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <CommandeStatutCard statut="nouvelles"   count={commandes.nouvelles   || 0} />
          <CommandeStatutCard statut="a_planifier" count={commandes.a_planifier || 0} />
          <CommandeStatutCard statut="planifiees"  count={commandes.planifiees  || 0} />
        </div>
      </div>

      {/* Dernier indice Syntec */}
      {indice?.indice && (
        <div className="card">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="font-semibold text-gray-900">📈 Dernier indice Syntec</h2>
              <p className="text-sm text-gray-500 mt-1">
                {indice.indice.mois} {indice.indice.annee} — Valeur :{' '}
                <span className="font-bold text-gray-900">{indice.indice.valeur}</span>
              </p>
            </div>
            <Link to="/indices" className="text-blue-600 text-sm hover:underline">Gérer les indices →</Link>
          </div>
        </div>
      )}
    </div>
  );
}
