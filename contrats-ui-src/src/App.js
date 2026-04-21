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

function PrivateRoute({ children }) {
  const { user, loading } = useAuth();
  if (loading) return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="text-gray-400 text-lg">Chargement...</div>
    </div>
  );
  if (!user) return <Navigate to="/login" replace />;
  return <Layout>{children}</Layout>;
}

function AppRoutes() {
  const { user } = useAuth();
  return (
    <Routes>
      <Route path="/login" element={user ? <Navigate to="/" replace /> : <Login />} />
      <Route path="/" element={<PrivateRoute><Dashboard /></PrivateRoute>} />
      <Route path="/contrats" element={<PrivateRoute><Contrats /></PrivateRoute>} />
      <Route path="/contrats/nouveau" element={<PrivateRoute><NouveauContrat /></PrivateRoute>} />
      <Route path="/contrats/tunnel" element={<PrivateRoute><TunnelContrat /></PrivateRoute>} />
      <Route path="/contrats/:id" element={<PrivateRoute><DetailContrat /></PrivateRoute>} />
      <Route path="/contrats/:id/modifier" element={<PrivateRoute><ModifierContrat /></PrivateRoute>} />
      <Route path="/renouvellements" element={<PrivateRoute><Renouvellements /></PrivateRoute>} />
      <Route path="/facturation" element={<PrivateRoute><Facturation /></PrivateRoute>} />
      <Route path="/indices" element={<PrivateRoute><Indices /></PrivateRoute>} />
      <Route path="/clients" element={<PrivateRoute><Clients /></PrivateRoute>} />
      <Route path="/parametres" element={<PrivateRoute><Parametres /></PrivateRoute>} />
      <Route path="/utilisateurs" element={<PrivateRoute><Utilisateurs /></PrivateRoute>} />
      <Route path="/commandes/nouvelles" element={<PrivateRoute><NouvellesCommandes /></PrivateRoute>} />
      <Route path="/commandes/a-planifier" element={<PrivateRoute><CommandesAPlanifier /></PrivateRoute>} />
      <Route path="/commandes/planifiees" element={<PrivateRoute><CommandesPlanifiees /></PrivateRoute>} />
      <Route path="/commandes/terminees" element={<PrivateRoute><CommandesTerminees /></PrivateRoute>} />
      <Route path="/contrats-a-creer" element={<PrivateRoute><ContratsACreer /></PrivateRoute>} />
      <Route path="/formateurs" element={<PrivateRoute><Formateurs /></PrivateRoute>} />
      <Route path="/mes-prestations" element={<PrivateRoute><MesPrestations /></PrivateRoute>} />
      <Route path="/chorus-pro" element={<PrivateRoute><ChorusProPage /></PrivateRoute>} />
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
