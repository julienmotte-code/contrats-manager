import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

const MENU_COMPLET = [
  { path: '/', label: 'Tableau de bord', icon: '🏠', droit: null },
  { type: 'separator', label: 'Commandes' },
  { path: '/commandes/nouvelles', label: 'Nouvelles commandes', icon: '🆕', droit: 'commandes' },
  { path: '/commandes/a-planifier', label: 'À planifier', icon: '📅', droit: 'commandes' },
  { path: '/commandes/planifiees', label: 'Planifiées', icon: '✅', droit: 'commandes' },
  { path: '/commandes/a-traiter', label: 'À traiter', icon: '🛒', droit: 'commandes' },
  { path: '/mes-prestations', label: 'Mes prestations', icon: '📋', droit: 'commandes' },
  { type: 'separator', label: 'Contrats' },
  { path: '/contrats', label: 'Liste des contrats', icon: '📄', droit: null },
  { path: '/contrats/tunnel?mode=nouveau', label: 'Nouveau contrat', icon: '➕', droit: 'contrats_ecriture' },
  { path: '/contrats-a-creer', label: 'Contrats à créer', icon: '📝', droit: 'commandes' },
  { path: '/renouvellements', label: 'Renouvellements', icon: '🔄', droit: null },
  { type: 'separator', label: 'Gestion' },
  { path: '/clients', label: 'Clients', icon: '🏢', droit: null },
  { path: '/facturation', label: 'Facturation', icon: '💶', droit: 'facturation' },
  { path: '/indices', label: 'Indices Syntec', icon: '📈', droit: 'indices' },
  { type: 'separator', label: 'Administration' },
  { path: '/parametres', label: 'Paramètres', icon: '⚙️', droit: 'parametres' },
  { path: '/formateurs', label: 'Formateurs', icon: '👨‍🏫', droit: 'utilisateurs' },
  { path: '/utilisateurs', label: 'Utilisateurs', icon: '👥', droit: 'utilisateurs' },
];

export default function Layout({ children }) {
  const { user, droits, logout } = useAuth();
  const location = useLocation();

  const menu = MENU_COMPLET.filter(item => {
    if (item.type === 'separator') return true;
    return !item.droit || (droits && droits[item.droit]);
  });

  return (
    <div className="min-h-screen flex bg-gray-50">
      <aside className="w-64 bg-blue-900 text-white flex flex-col fixed h-full z-10">
        <div className="p-5 border-b border-blue-800">
          <h1 className="text-lg font-bold">📋 Gestion Contrats</h1>
          <p className="text-blue-300 text-xs mt-1">Module Karlia</p>
        </div>

        <nav className="flex-1 p-4 space-y-1 overflow-y-auto">
          {menu.map((item, idx) => (
            item.type === 'separator' ? (
              <div key={idx} className="pt-4 pb-2 px-3">
                <span className="text-xs font-semibold text-blue-400 uppercase tracking-wider">
                  {item.label}
                </span>
              </div>
            ) : (
              <Link 
                key={item.path} 
                to={item.path}
                className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
                  location.pathname === item.path || 
                  (item.path !== '/' && location.pathname.startsWith(item.path.split('?')[0]))
                    ? 'bg-blue-700 text-white font-medium' 
                    : 'text-blue-200 hover:bg-blue-800 hover:text-white'
                }`}
              >
                <span>{item.icon}</span>
                <span>{item.label}</span>
              </Link>
            )
          ))}
        </nav>

        <div className="p-4 border-t border-blue-800">
          <div className="text-sm text-blue-300 mb-2">
            <div className="font-medium text-white">{user?.nom_complet}</div>
            <div className="text-xs">{user?.role}</div>
          </div>
          <button 
            onClick={logout} 
            className="w-full text-left text-xs text-blue-400 hover:text-white transition-colors"
          >
            🚪 Se déconnecter
          </button>
        </div>
      </aside>

      <main className="ml-64 flex-1 p-8 min-h-screen">
        {children}
      </main>
    </div>
  );
}
