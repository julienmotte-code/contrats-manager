import React, { useState } from 'react';
import { Navigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import api from '../services/api';
import { useAuth } from '../context/AuthContext';

const ROLES_AUTORISES = ['ADMIN', 'GESTIONNAIRE'];

export default function TransfertSage() {
  const { user } = useAuth();
  const [fichier, setFichier] = useState(null);
  const [inclureBanque, setInclureBanque] = useState(false);
  const [enCours, setEnCours] = useState(false);
  const [resultat, setResultat] = useState(null);

  // Garde de rôle au niveau de la page (en plus du menu) : données financières
  if (user && !ROLES_AUTORISES.includes(user.role)) {
    return <Navigate to="/" replace />;
  }

  const onSelect = (e) => {
    const f = e.target.files && e.target.files[0] ? e.target.files[0] : null;
    setResultat(null);
    if (f && !f.name.toLowerCase().endsWith('.xlsx')) {
      toast.error('Sélectionnez un export Excel (.xlsx) de Karlia.');
      setFichier(null);
      e.target.value = '';
      return;
    }
    setFichier(f);
  };

  const preparer = async () => {
    if (!fichier) { toast.error('Choisissez d\'abord un fichier.'); return; }
    setEnCours(true);
    setResultat(null);
    try {
      const fd = new FormData();
      fd.append('fichier', fichier);
      fd.append('inclure_banque', inclureBanque ? 'true' : 'false');
      const { data } = await api.post('/api/comptabilite/transfert-sage/convertir', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setResultat(data);
      toast.success(data.recap.nb_lignes + ' ecriture(s) preparee(s).');
    } catch (err) {
      const msg = (err.response && err.response.data && err.response.data.detail)
        ? err.response.data.detail : 'Echec de la conversion.';
      toast.error(msg);
    } finally {
      setEnCours(false);
    }
  };

  const telecharger = () => {
    if (!resultat) return;
    // contenu encode latin-1 -> reconstruire les octets bruts depuis le base64 (pas d'UTF-8)
    const bin = atob(resultat.contenu_base64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    const blob = new Blob([bytes], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = resultat.nom_fichier;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const recap = resultat ? resultat.recap : null;

  return (
    <div className="max-w-3xl">
      <h1 className="text-2xl font-bold text-gray-800 mb-1">Transfert Sage</h1>
      <p className="text-gray-500 mb-6">
        Convertit un export comptable Karlia (FEC, .xlsx) en fichier d'import Sage.
      </p>

      <div className="bg-white rounded-xl shadow p-6 space-y-5">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Fichier d'export Karlia (.xlsx)
          </label>
          <input
            type="file"
            accept=".xlsx"
            onChange={onSelect}
            className="block w-full text-sm text-gray-600 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100"
          />
          {fichier && (
            <p className="text-xs text-gray-500 mt-1">
              Selectionne : {fichier.name} ({Math.round(fichier.size / 1024)} Ko)
            </p>
          )}
        </div>

        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input
            type="checkbox"
            checked={inclureBanque}
            onChange={(e) => setInclureBanque(e.target.checked)}
          />
          Inclure les ecritures de banque
        </label>

        <button
          onClick={preparer}
          disabled={!fichier || enCours}
          className="px-4 py-2.5 rounded-lg bg-blue-700 text-white text-sm font-medium hover:bg-blue-800 disabled:opacity-50"
        >
          {enCours ? 'Preparation...' : 'Preparer le fichier Sage'}
        </button>
      </div>

      {recap && (
        <div className="bg-white rounded-xl shadow p-6 mt-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-gray-800">Recapitulatif</h2>
            <button
              onClick={telecharger}
              className="px-4 py-2 rounded-lg bg-green-600 text-white text-sm font-medium hover:bg-green-700"
            >
              Telecharger {resultat.nom_fichier}
            </button>
          </div>

          <div className="grid grid-cols-2 gap-3 text-sm mb-4">
            <div><span className="text-gray-500">Ecritures :</span> <b>{recap.nb_lignes}</b></div>
            <div><span className="text-gray-500">Periode :</span> <b>{recap.periode_min} -&gt; {recap.periode_max}</b></div>
            <div><span className="text-gray-500">Total debit :</span> <b>{recap.total_debit.toFixed(2)} EUR</b></div>
            <div><span className="text-gray-500">Total credit :</span> <b>{recap.total_credit.toFixed(2)} EUR</b></div>
            <div className="col-span-2">
              <span className="text-gray-500">Equilibre :</span>{' '}
              {recap.equilibre
                ? <span className="text-green-700 font-medium">equilibre OK</span>
                : <span className="text-red-700 font-medium">desequilibre</span>}
              {recap.banque_incluse && <span className="ml-3 text-xs text-gray-500">(banque incluse)</span>}
            </div>
          </div>

          <table className="w-full text-sm border-t">
            <thead>
              <tr className="text-left text-gray-500">
                <th className="py-2">Journal Sage</th>
                <th className="py-2">Karlia</th>
                <th className="py-2 text-right">Ecritures</th>
                <th className="py-2 text-right">Debit</th>
                <th className="py-2 text-right">Credit</th>
              </tr>
            </thead>
            <tbody>
              {recap.journaux.map((j) => (
                <tr key={j.code_karlia} className="border-t">
                  <td className="py-2 font-medium">{j.code_sage}</td>
                  <td className="py-2 text-gray-500">{j.code_karlia}</td>
                  <td className="py-2 text-right">{j.nb_ecritures}</td>
                  <td className="py-2 text-right">{j.total_debit.toFixed(2)} EUR</td>
                  <td className="py-2 text-right">{j.total_credit.toFixed(2)} EUR</td>
                </tr>
              ))}
            </tbody>
          </table>

          <p className="text-xs text-gray-400 mt-4">
            Verifiez que le nombre d'ecritures par journal correspond a ce que vous attendez
            avant d'importer le fichier dans Sage.
          </p>
        </div>
      )}
    </div>
  );
}
