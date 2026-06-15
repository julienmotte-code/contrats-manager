import axios from 'axios';
const api = axios.create({ baseURL: '' });
api.interceptors.request.use(config => {
  const token = localStorage.getItem('token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});
api.interceptors.response.use(r => r, err => {
  if (err.response?.status === 401) { localStorage.removeItem('token'); window.location.href = '/login'; }
  return Promise.reject(err);
});
export const authAPI = {
  login: (username, password) => { const form = new URLSearchParams(); form.append('username', username); form.append('password', password); return api.post('/api/auth/login', form, { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } }); },
  me: () => api.get('/api/auth/me'),
};
export const clientsAPI = {
  liste: (params) => api.get('/api/clients', { params }),
  recherche: (q) => api.get('/api/clients/search', { params: { q } }),
  creer: (data) => api.post('/api/clients', data),
  synchro: () => api.post('/api/clients/synchro'),
};
export const contratsAPI = {
  liste: (params) => api.get('/api/contrats', { params }),
  detail: (id) => api.get(`/api/contrats/${id}`),
  creer: (data) => api.post('/api/contrats', data),
  valider: (id) => api.post(`/api/contrats/${id}/valider`),
  terminer: (id, motif) => api.post(`/api/contrats/${id}/terminer`, null, { params: { motif } }),
  renouveler: (id, data) => api.post(`/api/contrats/${id}/renouveler`, data),
  renouvelerLot: (data) => api.post('/api/contrats/renouveler-lot', data),
  renouvellements: (params) => api.get('/api/contrats/renouvellements', { params }),
  facturerBrouillon: (id) => api.post(`/api/contrats/${id}/facturer-brouillon`),
};
export const produitsAPI = { liste: (params) => api.get('/api/produits', { params }) };
export const indicesAPI = {
  liste: () => api.get('/api/indices'),
  creer: (data) => api.post('/api/indices', data),
  courant: () => api.get('/api/indices/courant'),
  supprimer: (id) => api.delete(`/api/indices/${id}`),
};
export const facturationAPI = {
  apercu: (annee) => api.get(`/api/facturation/apercu/${annee}`),
  lancer: (data) => api.post('/api/facturation/lancer', data),
};
export const dashboardAPI = {
  stats: () => api.get('/api/dashboard/stats'),
};
export const caAPI = {
  comparatif: (params) => api.get('/api/ca/comparatif', { params }),
  rafraichirKarlia: () => api.post('/api/ca/rafraichir-karlia'),
};
export const facturesFournisseursAPI = {
  facturables: (params) => api.get('/api/factures-fournisseurs/facturables', { params }),
  liste: (params) => api.get('/api/factures-fournisseurs', { params }),
  detail: (id) => api.get(`/api/factures-fournisseurs/${id}`),
  creer: (data) => api.post('/api/factures-fournisseurs', data),
  modifier: (id, data) => api.put(`/api/factures-fournisseurs/${id}`, data),
  valider: (id) => api.post(`/api/factures-fournisseurs/${id}/valider`),
  supprimer: (id) => api.delete(`/api/factures-fournisseurs/${id}`),
};
export default api;
