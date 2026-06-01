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

// Écran "Terminées" (route /commandes/terminees conservée).
// Depuis v3.10.0, il liste des ÉLÉMENTS facturables UNIFIÉS renvoyés par
// GET /api/commandes/lignes-a-facturer :
//   - type 'ligne'      : ligne de commande routée 'facturation_directe' ;
//   - type 'prestation' : prestation réalisée (prix dérivé de la ligne parente).
// Chaque élément : { type, id, commande_id, commande_reference,
//   karlia_customer_id, client_nom, designation, quantite, prix_unitaire_ht,
//   taux_tva, montant_ht, montant_ttc, date_acceptation, ordre }.
//
// Contraintes métier :
//  - une facture Karlia = un seul CLIENT (implicite via mono-commande) ;
//  - une facture = une seule COMMANDE (mono-commande strict). Le backend
//    revalide (double sécurité). Sélection mixte ligne+prestation autorisée
//    tant qu'elles sont de la MÊME commande.

// Chargement en une fois : le regroupement client/commande serait incohérent
// si un groupe était coupé entre deux pages. 1000 = plafond actuel du backend.
const PAGE_SIZE = 1000;

// Identifiant composé anti-collision entre les deux types.
const elKey = (e) => `${e.type}:${e.id}`;

const TYPE_LABEL = { ligne: 'Ligne', prestation: 'Prestation' };
const TYPE_COLOR = { ligne: 'primary', prestation: 'secondary' };

export default function CommandesTerminees() {
  const [elements, setElements] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [facturant, setFacturant] = useState(false);
  // Set des clés composées `${type}:${id}` cochées.
  const [selected, setSelected] = useState(() => new Set());

  const fetchElements = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/api/commandes/lignes-a-facturer', {
        params: { page: 1, page_size: PAGE_SIZE, search: search || undefined }
      });
      setElements(res.data.items || []);
      setSelected(new Set());
      setError(null);
    } catch (err) {
      setError('Erreur lors du chargement des éléments à facturer');
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [search]);

  useEffect(() => { fetchElements(); }, [fetchElements]);

  const formatMontant = (montant) => {
    if (montant === null || montant === undefined || montant === '') return '-';
    return new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR' }).format(Number(montant));
  };
  const num = (v) => (v === null || v === undefined || v === '' ? 0 : Number(v));

  // ── Regroupement par CLIENT puis par COMMANDE ──────────────────────────────
  const groupes = useMemo(() => {
    const sorted = [...elements].sort((a, b) => {
      const cn = (a.client_nom || '').localeCompare(b.client_nom || '');
      if (cn !== 0) return cn;
      const cr = (a.commande_reference || '').localeCompare(b.commande_reference || '');
      if (cr !== 0) return cr;
      return (a.ordre ?? 0) - (b.ordre ?? 0);
    });
    const clients = new Map();
    for (const el of sorted) {
      const ckey = el.karlia_customer_id ?? `nc-${el.commande_id}`;
      if (!clients.has(ckey)) {
        clients.set(ckey, { customer_id: el.karlia_customer_id, client_nom: el.client_nom, commandes: new Map() });
      }
      const cmdMap = clients.get(ckey).commandes;
      if (!cmdMap.has(el.commande_id)) {
        cmdMap.set(el.commande_id, {
          commande_id: el.commande_id, commande_reference: el.commande_reference, elements: []
        });
      }
      cmdMap.get(el.commande_id).elements.push(el);
    }
    return Array.from(clients.values()).map(c => {
      const commandes = Array.from(c.commandes.values());
      return { ...c, commandes, elements: commandes.flatMap(cmd => cmd.elements) };
    });
  }, [elements]);

  // ── Sélection (clés composées) ─────────────────────────────────────────────
  const toggleElement = (el) => {
    const k = elKey(el);
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k); else next.add(k);
      return next;
    });
  };

  const toggleKeys = (keys) => {
    const allSelected = keys.every(k => selected.has(k));
    setSelected(prev => {
      const next = new Set(prev);
      if (allSelected) keys.forEach(k => next.delete(k));
      else keys.forEach(k => next.add(k));
      return next;
    });
  };

  const triState = (keys) => {
    const nb = keys.filter(k => selected.has(k)).length;
    return { all: nb === keys.length && nb > 0, some: nb > 0 && nb < keys.length };
  };

  // ── Synthèse sélection ───────────────────────────────────────────────────
  const selectedElements = useMemo(
    () => elements.filter(e => selected.has(elKey(e))),
    [elements, selected]
  );
  const commandesSelectionnees = useMemo(
    () => new Set(selectedElements.map(e => e.commande_id)),
    [selectedElements]
  );
  const nbLignes = selectedElements.filter(e => e.type === 'ligne').length;
  const nbPrestations = selectedElements.filter(e => e.type === 'prestation').length;
  const totalHT = selectedElements.reduce((s, e) => s + num(e.montant_ht), 0);
  const totalTTC = selectedElements.reduce((s, e) => s + num(e.montant_ttc), 0);
  const monoCommande = commandesSelectionnees.size === 1;
  const canFacturer = selectedElements.length > 0 && monoCommande && !facturant;

  const tooltipBloquant = commandesSelectionnees.size > 1
    ? `Une facture ne peut couvrir qu'une seule commande à la fois. `
      + `Sélection actuelle : ${commandesSelectionnees.size} commandes. `
      + `Ne cochez que les éléments d'une même commande.`
    : '';

  const handleFacturer = async () => {
    if (!canFacturer) return;
    setFacturant(true);
    setError(null);
    const payloadElements = selectedElements.map(e => ({ type: e.type, id: e.id }));
    try {
      const res = await api.post('/api/commandes/facturer-lignes', { elements: payloadElements });
      const data = res.data || {};
      const ref = data.facture_karlia_ref || data.facture_karlia_id || '';
      setSuccess(
        `Facture brouillon créée dans Karlia (${data.nb_elements_factures ?? payloadElements.length} élément(s)`
        + `${ref ? `, réf ${ref}` : ''}).`
      );
      // Retirer les éléments facturés (par clé composée) + vider la sélection.
      const facturees = new Set((data.elements || payloadElements).map(elKey));
      setElements(prev => prev.filter(e => !facturees.has(elKey(e))));
      setSelected(new Set());
    } catch (err) {
      setError(err.response?.data?.detail || 'Erreur lors de la facturation');
    } finally {
      setFacturant(false);
    }
  };

  const truncate = (s, n = 70) => (s && s.length > n ? `${s.slice(0, n)}…` : (s || ''));

  return (
    <Box sx={{ p: 3, pb: selectedElements.length > 0 ? 12 : 3 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h4" sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <TitleIcon color="success" /> Éléments à facturer
        </Typography>
        <Chip label={`${elements.length} élément(s)`} color="success" />
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
              <TableCell>Type</TableCell>
              <TableCell>Commande</TableCell>
              <TableCell>Désignation</TableCell>
              <TableCell align="right">Qté</TableCell>
              <TableCell align="right">PU HT</TableCell>
              <TableCell align="right">Montant HT</TableCell>
              <TableCell align="right">Montant TTC</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={8} align="center" sx={{ py: 4 }}><CircularProgress /></TableCell>
              </TableRow>
            ) : elements.length === 0 ? (
              <TableRow>
                <TableCell colSpan={8} align="center" sx={{ py: 4 }}>Aucun élément à facturer</TableCell>
              </TableRow>
            ) : (
              groupes.map((groupe) => {
                const clientKeys = groupe.elements.map(elKey);
                const cs = triState(clientKeys);
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
                          onChange={() => toggleKeys(clientKeys)}
                        />
                      </TableCell>
                      <TableCell colSpan={7}>
                        <Typography variant="subtitle2" sx={{ fontWeight: 'bold' }}>
                          {groupe.client_nom || 'Client inconnu'}
                          {' '}
                          <Chip label={`${groupe.elements.length} élément(s)`} size="small" variant="outlined" sx={{ ml: 1 }} />
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
                      const cmdKeys = cmd.elements.map(elKey);
                      const cmdS = triState(cmdKeys);
                      const totHTcmd = cmd.elements.reduce((s, e) => s + num(e.montant_ht), 0);
                      return (
                        <React.Fragment key={cmd.commande_id}>
                          <TableRow sx={{ backgroundColor: 'grey.50' }}>
                            <TableCell padding="checkbox">
                              <Checkbox
                                size="small"
                                checked={cmdS.all}
                                indeterminate={cmdS.some}
                                onChange={() => toggleKeys(cmdKeys)}
                              />
                            </TableCell>
                            <TableCell colSpan={7}>
                              <Chip label={cmd.commande_reference || '-'} size="small" color="primary" variant="outlined" />
                              <Box component="span" sx={{ color: 'text.secondary', ml: 1, fontSize: 13 }}>
                                {cmd.elements.length} élément(s) · {formatMontant(totHTcmd)} HT
                              </Box>
                            </TableCell>
                          </TableRow>
                          {cmd.elements.map((el) => {
                            const k = elKey(el);
                            return (
                              <TableRow key={k} hover selected={selected.has(k)}>
                                <TableCell padding="checkbox">
                                  <Checkbox
                                    size="small"
                                    checked={selected.has(k)}
                                    onChange={() => toggleElement(el)}
                                  />
                                </TableCell>
                                <TableCell>
                                  <Chip
                                    label={TYPE_LABEL[el.type] || el.type}
                                    size="small"
                                    color={TYPE_COLOR[el.type] || 'default'}
                                    variant="filled"
                                  />
                                </TableCell>
                                <TableCell>
                                  <Chip label={el.commande_reference || '-'} size="small" variant="outlined" />
                                </TableCell>
                                <TableCell>
                                  <Tooltip title={el.designation || ''}>
                                    <Typography variant="body2">
                                      <Box component="span" sx={{ color: 'text.secondary', mr: 1 }}>
                                        #{el.ordre ?? '-'}
                                      </Box>
                                      {truncate(el.designation)}
                                    </Typography>
                                  </Tooltip>
                                </TableCell>
                                <TableCell align="right">{num(el.quantite)}</TableCell>
                                <TableCell align="right">{formatMontant(el.prix_unitaire_ht)}</TableCell>
                                <TableCell align="right">{formatMontant(el.montant_ht)}</TableCell>
                                <TableCell align="right">{formatMontant(el.montant_ttc)}</TableCell>
                              </TableRow>
                            );
                          })}
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
      {selectedElements.length > 0 && (
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
              {nbLignes} ligne(s) + {nbPrestations} prestation(s) sélectionnée(s)
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Total HT {formatMontant(totalHT)} · Total TTC {formatMontant(totalTTC)}
            </Typography>
          </Box>
          {commandesSelectionnees.size > 1 && (
            <Chip color="error" label={`${commandesSelectionnees.size} commandes`} />
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
