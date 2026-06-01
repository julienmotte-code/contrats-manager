import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Box, Paper, Typography, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, Checkbox, Chip, TextField, InputAdornment,
  CircularProgress, Alert, Tooltip, Button, Snackbar
} from '@mui/material';
import {
  Search as SearchIcon, Receipt as FactureIcon, ReceiptLong as TitleIcon
} from '@mui/icons-material';
import api from '../services/api';

// L'écran historique "Terminées" listait des COMMANDES au statut 'deployee'.
// Depuis la refonte par lignes (v3.5.0), il liste des LIGNES routées
// 'facturation_directe' non encore facturées (cf. backend
// GET /api/commandes/lignes-a-facturer). La route /commandes/terminees est
// CONSERVÉE (liens existants), seul le titre et l'intention changent.
//
// Contraintes métier (v3.5.0) :
//  - une facture Karlia = un seul CLIENT (id_customer unique) ;
//  - une facture = une seule COMMANDE (mono-commande, simplicité + lien
//    id_opportunity sans ambiguïté). Le backend revalide les deux (double
//    sécurité). On regroupe visuellement par client puis par commande, et on
//    n'autorise la facturation que d'une sélection mono-commande.

// Chargement en une fois : le regroupement par client/commande serait incohérent
// si un groupe était coupé entre deux pages. 1000 = plafond actuel du backend ;
// au-delà, prévoir une pagination côté serveur.
const PAGE_SIZE = 1000;

export default function CommandesTerminees() {
  const [lignes, setLignes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [facturant, setFacturant] = useState(false);
  // Set des ligne_ids cochés
  const [selected, setSelected] = useState(() => new Set());

  const fetchLignes = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/api/commandes/lignes-a-facturer', {
        params: { page: 1, page_size: PAGE_SIZE, search: search || undefined }
      });
      setLignes(res.data.items || []);
      setSelected(new Set());
      setError(null);
    } catch (err) {
      setError('Erreur lors du chargement des lignes à facturer');
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [search]);

  useEffect(() => { fetchLignes(); }, [fetchLignes]);

  const formatMontant = (montant) => {
    if (montant === null || montant === undefined || montant === '') return '-';
    return new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR' }).format(Number(montant));
  };
  const num = (v) => (v === null || v === undefined || v === '' ? 0 : Number(v));

  // ── Regroupement par CLIENT puis par COMMANDE ──────────────────────────────
  // Tri : client_nom → commande_reference → ordre. Structure :
  //   [{ customer_id, client_nom, commandes: [{ commande_id, commande_reference,
  //      lignes: [...] }] }]
  const groupes = useMemo(() => {
    const sorted = [...lignes].sort((a, b) => {
      const cn = (a.client_nom || '').localeCompare(b.client_nom || '');
      if (cn !== 0) return cn;
      const cr = (a.commande_reference || '').localeCompare(b.commande_reference || '');
      if (cr !== 0) return cr;
      return (a.ordre ?? 0) - (b.ordre ?? 0);
    });
    const clients = new Map();
    for (const l of sorted) {
      const ckey = l.karlia_customer_id ?? `nc-${l.commande_id}`;
      if (!clients.has(ckey)) {
        clients.set(ckey, { customer_id: l.karlia_customer_id, client_nom: l.client_nom, commandes: new Map() });
      }
      const cmdMap = clients.get(ckey).commandes;
      if (!cmdMap.has(l.commande_id)) {
        cmdMap.set(l.commande_id, {
          commande_id: l.commande_id, commande_reference: l.commande_reference, lignes: []
        });
      }
      cmdMap.get(l.commande_id).lignes.push(l);
    }
    return Array.from(clients.values()).map(c => ({
      ...c,
      commandes: Array.from(c.commandes.values()),
      lignes: Array.from(c.commandes.values()).flatMap(cmd => cmd.lignes),
    }));
  }, [lignes]);

  // ── Sélection ────────────────────────────────────────────────────────────
  const toggleLine = (ligneId) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(ligneId)) next.delete(ligneId); else next.add(ligneId);
      return next;
    });
  };

  const toggleSet = (ids) => {
    const allSelected = ids.every(id => selected.has(id));
    setSelected(prev => {
      const next = new Set(prev);
      if (allSelected) ids.forEach(id => next.delete(id));
      else ids.forEach(id => next.add(id));
      return next;
    });
  };

  const setState = (ids) => {
    const nb = ids.filter(id => selected.has(id)).length;
    return { all: nb === ids.length && nb > 0, some: nb > 0 && nb < ids.length };
  };

  // ── Synthèse sélection ───────────────────────────────────────────────────
  const selectedLignes = useMemo(
    () => lignes.filter(l => selected.has(l.ligne_id)),
    [lignes, selected]
  );
  const clientsSelectionnes = useMemo(
    () => new Set(selectedLignes.map(l => l.karlia_customer_id)),
    [selectedLignes]
  );
  const commandesSelectionnees = useMemo(
    () => new Set(selectedLignes.map(l => l.commande_id)),
    [selectedLignes]
  );
  const totalHT = selectedLignes.reduce((s, l) => s + num(l.montant_ht), 0);
  const totalTTC = selectedLignes.reduce((s, l) => s + num(l.montant_ttc), 0);
  const monoClient = clientsSelectionnes.size === 1;
  const monoCommande = commandesSelectionnees.size === 1;
  const canFacturer = selectedLignes.length > 0 && monoClient && monoCommande && !facturant;

  // Tooltip d'explication quand le bouton est désactivé pour cause de sélection
  // trop large. Mono-commande prioritaire (c'est la contrainte la plus stricte).
  let tooltipBloquant = '';
  if (commandesSelectionnees.size > 1) {
    tooltipBloquant = `Une facture ne peut couvrir qu'une seule commande à la fois. `
      + `Sélection actuelle : ${commandesSelectionnees.size} commandes. `
      + `Ne cochez que les lignes d'une même commande.`;
  } else if (clientsSelectionnes.size > 1) {
    tooltipBloquant = `Une facture Karlia ne peut couvrir qu'un seul client. `
      + `Sélection actuelle : ${clientsSelectionnes.size} clients différents. `
      + `Décochez les lignes des autres clients.`;
  }

  const handleFacturer = async () => {
    if (!canFacturer) return;
    setFacturant(true);
    setError(null);
    const ligneIds = selectedLignes.map(l => l.ligne_id);
    try {
      const res = await api.post('/api/commandes/facturer-lignes', { ligne_ids: ligneIds });
      const data = res.data || {};
      const ref = data.facture_karlia_ref || data.facture_karlia_id || '';
      setSuccess(
        `Facture brouillon créée dans Karlia (${data.nb_lignes_facturees ?? ligneIds.length} ligne(s)`
        + `${ref ? `, réf ${ref}` : ''}).`
      );
      // Retirer les lignes facturées de la liste affichée + vider la sélection.
      const facturees = new Set(data.ligne_ids || ligneIds);
      setLignes(prev => prev.filter(l => !facturees.has(l.ligne_id)));
      setSelected(new Set());
    } catch (err) {
      setError(err.response?.data?.detail || 'Erreur lors de la facturation');
    } finally {
      setFacturant(false);
    }
  };

  const truncate = (s, n = 70) => (s && s.length > n ? `${s.slice(0, n)}…` : (s || ''));

  return (
    <Box sx={{ p: 3, pb: selectedLignes.length > 0 ? 12 : 3 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h4" sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <TitleIcon color="success" /> Lignes à facturer
        </Typography>
        <Chip label={`${lignes.length} ligne(s)`} color="success" />
      </Box>

      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>{error}</Alert>}

      <Paper sx={{ mb: 2, p: 2 }}>
        <TextField
          size="small"
          placeholder="Rechercher par client ou référence..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          InputProps={{
            startAdornment: <InputAdornment position="start"><SearchIcon /></InputAdornment>
          }}
          sx={{ width: 350 }}
        />
      </Paper>

      <TableContainer component={Paper}>
        <Table size="small">
          <TableHead>
            <TableRow sx={{ backgroundColor: 'grey.100' }}>
              <TableCell padding="checkbox" />
              <TableCell>Commande</TableCell>
              <TableCell>Ligne</TableCell>
              <TableCell align="right">Qté</TableCell>
              <TableCell align="right">PU HT</TableCell>
              <TableCell align="right">Montant HT</TableCell>
              <TableCell align="right">Montant TTC</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={7} align="center" sx={{ py: 4 }}><CircularProgress /></TableCell>
              </TableRow>
            ) : lignes.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} align="center" sx={{ py: 4 }}>Aucune ligne à facturer</TableCell>
              </TableRow>
            ) : (
              groupes.map((groupe) => {
                const clientIds = groupe.lignes.map(l => l.ligne_id);
                const cs = setState(clientIds);
                const clientKey = groupe.customer_id ?? `nc-${groupe.commandes[0].commande_id}`;
                return (
                  <React.Fragment key={clientKey}>
                    {/* Sous-en-tête CLIENT */}
                    <TableRow sx={{ backgroundColor: 'grey.100' }}>
                      <TableCell padding="checkbox">
                        <Checkbox
                          size="small"
                          checked={cs.all}
                          indeterminate={cs.some}
                          onChange={() => toggleSet(clientIds)}
                        />
                      </TableCell>
                      <TableCell colSpan={6}>
                        <Typography variant="subtitle2" sx={{ fontWeight: 'bold' }}>
                          {groupe.client_nom || 'Client inconnu'}
                          {' '}
                          <Chip label={`${groupe.lignes.length} ligne(s)`} size="small" variant="outlined" sx={{ ml: 1 }} />
                          {groupe.commandes.length > 1 && (
                            <Chip label={`${groupe.commandes.length} commandes`} size="small" color="info" variant="outlined" sx={{ ml: 1 }} />
                          )}
                          {groupe.customer_id == null && (
                            <Chip label="client Karlia non renseigné" size="small" color="warning" sx={{ ml: 1 }} />
                          )}
                        </Typography>
                      </TableCell>
                    </TableRow>

                    {/* Sous-groupes COMMANDE */}
                    {groupe.commandes.map((cmd) => {
                      const cmdIds = cmd.lignes.map(l => l.ligne_id);
                      const cmdS = setState(cmdIds);
                      return (
                        <React.Fragment key={cmd.commande_id}>
                          <TableRow sx={{ backgroundColor: 'grey.50' }}>
                            <TableCell padding="checkbox">
                              <Checkbox
                                size="small"
                                checked={cmdS.all}
                                indeterminate={cmdS.some}
                                onChange={() => toggleSet(cmdIds)}
                              />
                            </TableCell>
                            <TableCell colSpan={6}>
                              <Chip label={cmd.commande_reference || '-'} size="small" color="primary" variant="outlined" />
                              <Box component="span" sx={{ color: 'text.secondary', ml: 1, fontSize: 13 }}>
                                {cmd.lignes.length} ligne(s)
                              </Box>
                            </TableCell>
                          </TableRow>
                          {cmd.lignes.map((l) => (
                            <TableRow key={l.ligne_id} hover selected={selected.has(l.ligne_id)}>
                              <TableCell padding="checkbox">
                                <Checkbox
                                  size="small"
                                  checked={selected.has(l.ligne_id)}
                                  onChange={() => toggleLine(l.ligne_id)}
                                />
                              </TableCell>
                              <TableCell>
                                <Chip label={l.commande_reference || '-'} size="small" variant="outlined" />
                              </TableCell>
                              <TableCell>
                                <Tooltip title={l.designation || ''}>
                                  <Typography variant="body2">
                                    <Box component="span" sx={{ color: 'text.secondary', mr: 1 }}>
                                      #{l.ordre ?? '-'}
                                    </Box>
                                    {truncate(l.designation)}
                                  </Typography>
                                </Tooltip>
                              </TableCell>
                              <TableCell align="right">{num(l.quantite)}</TableCell>
                              <TableCell align="right">{formatMontant(l.prix_unitaire_ht)}</TableCell>
                              <TableCell align="right">{formatMontant(l.montant_ht)}</TableCell>
                              <TableCell align="right">{formatMontant(l.montant_ttc)}</TableCell>
                            </TableRow>
                          ))}
                        </React.Fragment>
                      );
                    })}
                  </React.Fragment>
                );
              })
            )}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Barre flottante de sélection */}
      {selectedLignes.length > 0 && (
        <Paper
          elevation={6}
          sx={{
            position: 'fixed', bottom: 0, left: 0, right: 0, zIndex: 1200,
            p: 2, display: 'flex', alignItems: 'center', gap: 3,
            borderTop: '1px solid', borderColor: 'divider'
          }}
        >
          <Box>
            <Typography variant="subtitle1" sx={{ fontWeight: 'bold' }}>
              {selectedLignes.length} ligne(s) sélectionnée(s)
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Total HT {formatMontant(totalHT)} · Total TTC {formatMontant(totalTTC)}
            </Typography>
          </Box>
          {commandesSelectionnees.size > 1 && (
            <Chip color="error" label={`${commandesSelectionnees.size} commandes`} />
          )}
          {commandesSelectionnees.size <= 1 && clientsSelectionnes.size > 1 && (
            <Chip color="error" label={`${clientsSelectionnes.size} clients différents`} />
          )}
          <Box sx={{ flexGrow: 1 }} />
          <Tooltip title={tooltipBloquant}>
            {/* span requis : Tooltip ne s'affiche pas sur un bouton désactivé */}
            <span>
              <Button
                variant="contained"
                color="success"
                startIcon={facturant ? <CircularProgress size={18} color="inherit" /> : <FactureIcon />}
                disabled={!canFacturer}
                onClick={handleFacturer}
              >
                Facturer la sélection (brouillon Karlia)
              </Button>
            </span>
          </Tooltip>
        </Paper>
      )}

      <Snackbar
        open={!!success}
        autoHideDuration={6000}
        onClose={() => setSuccess(null)}
        anchorOrigin={{ vertical: 'top', horizontal: 'center' }}
      >
        <Alert severity="success" onClose={() => setSuccess(null)} sx={{ width: '100%' }}>
          {success}
        </Alert>
      </Snackbar>
    </Box>
  );
}
