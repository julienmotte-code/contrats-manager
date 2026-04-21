import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Toaster } from 'react-hot-toast';
import { AuthProvider, useAuth } from './context/AuthContext';
import Layout from './components/Layout';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import Contrats from './pages/Contrats';
import NouveauContrat from './pages/NouveauContrat';
import TunnelContrat from './pages/TunnelContrat';
import DetailContrat from './pages/DetailContrat';
import Indices from './pages/Indices';
import Facturation from './pages/Facturation';
import Renouvellements from './pages/Renouvellements';
import Parametres from './pages/Parametres';
import Utilisateurs from './pages/Utilisateurs';
import Clients from './pages/Clients';
import ModifierContrat from './pages/ModifierContrat';
import NouvellesCommandes from './pages/NouvellesCommandes';
import CommandesAPlanifier from './pages/CommandesAPlanifier';
import CommandesPlanifiees from './pages/CommandesPlanifiees';
import CommandesTerminees from './pages/CommandesTerminees';
import ContratsACreer from './pages/ContratsACreer';
import Formateurs from './pages/Formateurs';
import MesPrestations from './pages/MesPrestations';
import ChorusProPage from './pages/ChorusProPage';

function getForbiddenRedirect(user) {
  if (user?.role === 'FORMATEUR') return '/mes-prestations';
  return '/';
}

function PrivateRoute({ children, allow }) {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-gray-400 text-lg">Chargement...</div>
      </div>
    );
  }

  if (!user) return <Navigate to="/login" replace />;
  if (allow && !allow(user)) return <Navigate to={getForbiddenRedirect(user)} replace />;

  return <Layout>{children}</Layout>;
}

function AppRoutes() {
  const { user } = useAuth();
  const isNotFormateur = (u) => u?.role !== 'FORMATEUR';

  return (
    <Routes>
      <Route path="/login" element={user ? <Navigate to="/" replace /> : <Login />} />
      <Route path="/" element={<PrivateRoute><Dashboard /></PrivateRoute>} />
      <Route path="/contrats" element={<PrivateRoute allow={isNotFormateur}><Contrats /></PrivateRoute>} />
      <Route path="/contrats/nouveau" element={<PrivateRoute allow={isNotFormateur}><NouveauContrat /></PrivateRoute>} />
      <Route path="/contrats/tunnel" element={<PrivateRoute allow={isNotFormateur}><TunnelContrat /></PrivateRoute>} />
      <Route path="/contrats/:id" element={<PrivateRoute allow={isNotFormateur}><DetailContrat /></PrivateRoute>} />
      <Route path="/contrats/:id/modifier" element={<PrivateRoute allow={isNotFormateur}><ModifierContrat /></PrivateRoute>} />
      <Route path="/renouvellements" element={<PrivateRoute allow={isNotFormateur}><Renouvellements /></PrivateRoute>} />
      <Route path="/facturation" element={<PrivateRoute allow={isNotFormateur}><Facturation /></PrivateRoute>} />
      <Route path="/indices" element={<PrivateRoute allow={isNotFormateur}><Indices /></PrivateRoute>} />
      <Route path="/clients" element={<PrivateRoute allow={isNotFormateur}><Clients /></PrivateRoute>} />
      <Route path="/parametres" element={<PrivateRoute allow={isNotFormateur}><Parametres /></PrivateRoute>} />
      <Route path="/utilisateurs" element={<PrivateRoute allow={isNotFormateur}><Utilisateurs /></PrivateRoute>} />
      <Route path="/commandes/nouvelles" element={<PrivateRoute allow={isNotFormateur}><NouvellesCommandes /></PrivateRoute>} />
      <Route path="/commandes/a-planifier" element={<PrivateRoute allow={isNotFormateur}><CommandesAPlanifier /></PrivateRoute>} />
      <Route path="/commandes/planifiees" element={<PrivateRoute allow={isNotFormateur}><CommandesPlanifiees /></PrivateRoute>} />
      <Route path="/commandes/terminees" element={<PrivateRoute allow={isNotFormateur}><CommandesTerminees /></PrivateRoute>} />
      <Route path="/contrats-a-creer" element={<PrivateRoute allow={isNotFormateur}><ContratsACreer /></PrivateRoute>} />
      <Route path="/formateurs" element={<PrivateRoute allow={isNotFormateur}><Formateurs /></PrivateRoute>} />
      <Route path="/mes-prestations" element={<PrivateRoute><MesPrestations /></PrivateRoute>} />
      <Route path="/chorus-pro" element={<PrivateRoute allow={isNotFormateur}><ChorusProPage /></PrivateRoute>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Toaster position="top-right" toastOptions={{ duration: 4000 }} />
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  );
}
