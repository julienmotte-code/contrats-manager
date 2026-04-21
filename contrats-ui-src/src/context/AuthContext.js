import React, { createContext, useContext, useState, useEffect } from 'react';
import { authAPI } from '../services/api';

const AuthContext = createContext(null);

// Droits par défaut selon le rôle
const getDroitsByRole = (role) => {
  switch (role) {
    case 'ADMIN':
      return {
        contrats_ecriture: true, contrats_lecture: true, facturation: true, indices: true, commandes: true,
        parametres: true, utilisateurs: true, formateurs: true, toutes_prestations: true
      };
    case 'GESTIONNAIRE':
      return {
        contrats_ecriture: true, contrats_lecture: true, facturation: true, indices: true, commandes: true,
        parametres: false, utilisateurs: false, formateurs: true, toutes_prestations: true
      };
    case 'TECHNICIEN':
      return {
        contrats_ecriture: false, contrats_lecture: true, facturation: false, indices: false, commandes: false,
        parametres: false, utilisateurs: false, formateurs: false, toutes_prestations: false
      };
    case 'FORMATEUR':
      return {
        contrats_ecriture: false, contrats_lecture: false, facturation: false, indices: false, commandes: false,
        parametres: false, utilisateurs: false, formateurs: false, toutes_prestations: false
      };
    default:
      return {
        contrats_ecriture: false, contrats_lecture: false, facturation: false, indices: false, commandes: false,
        parametres: false, utilisateurs: false, formateurs: false, toutes_prestations: false
      };
  }
};

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [droits, setDroits] = useState({
    contrats_ecriture: true, contrats_lecture: true, facturation: true, indices: true, commandes: true,
    parametres: true, utilisateurs: true, formateurs: true, toutes_prestations: true
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem('token');
    if (token) {
      authAPI.me()
        .then(r => {
          setUser(r.data);
          setDroits(getDroitsByRole(r.data.role));
        })
        .catch(() => localStorage.removeItem('token'))
        .finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, []);

  const login = async (username, password) => {
    const r = await authAPI.login(username, password);
    localStorage.setItem('token', r.data.access_token);
    const userData = {
      login: username,
      nom_complet: r.data.nom_complet,
      role: r.data.role,
      formateur_id: r.data.formateur_id
    };
    setUser(userData);
    setDroits(getDroitsByRole(r.data.role));
    return r.data;
  };

  const logout = () => {
    localStorage.removeItem('token');
    setUser(null);
    window.location.href = '/login';
  };

  return (
    <AuthContext.Provider value={{ user, droits, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
