import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
const MENU_COMPLET = [
  { path: '/', label: 'Tableau de bord', icon: '🏠', droit: null },
  { path: '/contrats', label: 'Contrats', icon: '📄', droit: null },
  { path: '/clients', label: 'Clients', icon: '🏢', droit: null },
  { path: '/contrats/tunnel?mode=nouveau', label: 'Nouveau contrat', icon: '➕', droit: 'contrats_ecriture' },
  { path: '/renouvellements', label: 'Renouvellements', icon: '🔄', droit: null },
  { path: '/facturation', label: 'Facturation', icon: '💶', droit: 'facturation' },
  { path: '/indices', label: 'Indices Syntec', icon: '📈', droit: 'indices' },
  { path: '/parametres', label: 'Paramètres', icon: '⚙️', droit: 'parametres' },
  { path: '/utilisateurs', label: 'Utilisateurs', icon: '👥', droit: 'utilisateurs' },
];
export default function Layout({ children }) {
  const { user, droits, logout } = useAuth();
  const location = useLocation();
  const menu = MENU_COMPLET.filter(item => !item.droit || (droits && droits[item.droit]));
  return (
    <div className="min-h-screen flex bg-gray-50">
      <aside className="w-64 bg-blue-900 text-white flex flex-col fixed h-full z-10">
        <div className="p-5 border-b border-blue-800">
          <h1 className="text-lg font-bold">📋 Gestion Contrats</h1>
          <p className="text-blue-300 text-xs mt-1">Module Karlia</p>
        </div>
        <nav className="flex-1 p-4 space-y-1">
          {menu.map(item => (
            <Link key={item.path} to={item.path}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${location.pathname === item.path ? 'bg-blue-700 text-white font-medium' : 'text-blue-200 hover:bg-blue-800 hover:text-white'}`}>
              <span>{item.icon}</span><span>{item.label}</span>
            </Link>
          ))}
        </nav>
        <div className="p-4 border-t border-blue-800">
          <div className="text-sm text-blue-300 mb-2">
            <div className="font-medium text-white">{user?.nom_complet}</div>
            <div className="text-xs">{user?.role}</div>
          </div>
          <button onClick={logout} className="w-full text-left text-xs text-blue-400 hover:text-white transition-colors">🚪 Se déconnecter</button>
        </div>
      </aside>
      <main className="ml-64 flex-1 p-8 min-h-screen">{children}</main>
    </div>
  );
}
