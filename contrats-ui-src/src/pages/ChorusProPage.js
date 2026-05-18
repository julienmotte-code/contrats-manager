import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Paper, Typography, Button, Chip, IconButton, Tooltip,
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  Checkbox, TextField, InputAdornment, Alert, Snackbar, Dialog,
  DialogTitle, DialogContent, DialogActions, CircularProgress,
  FormControl, InputLabel, Select, MenuItem, Grid, Card, CardContent
} from '@mui/material';
import {
  Search as SearchIcon,
  Refresh as RefreshIcon,
  Send as SendIcon,
  CloudUpload as SyncIcon,
  CheckCircle as SuccessIcon,
  Error as ErrorIcon,
  HourglassEmpty as PendingIcon,
  Info as InfoIcon,
  Edit as EditIcon,
  Science as ScienceIcon
} from '@mui/icons-material';
import { format } from 'date-fns';
import { fr } from 'date-fns/locale';
import api from '../services/api';

const STATUT_LABELS = {
  NON_TRANSMISE: { label: 'Non transmise', color: 'default', icon: <PendingIcon fontSize="small" /> },
  EN_COURS: { label: 'En cours', color: 'info', icon: <CircularProgress size={14} /> },
  TRANSMISE: { label: 'Transmise', color: 'success', icon: <SuccessIcon fontSize="small" /> },
  ACCEPTEE: { label: 'Acceptée', color: 'success', icon: <SuccessIcon fontSize="small" /> },
  REJETEE: { label: 'Rejetée', color: 'error', icon: <ErrorIcon fontSize="small" /> },
  ERREUR: { label: 'Erreur', color: 'error', icon: <ErrorIcon fontSize="small" /> }
};

const formatMontant = (montant) => {
  if (montant === null || montant === undefined) return '-';
  return new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR' }).format(montant);
};

const formatDate = (dateStr) => {
  if (!dateStr) return '-';
  try {
    return format(new Date(dateStr + 'T12:00:00'), 'd MMM yyyy', { locale: fr });
  } catch {
    return dateStr;
  }
};

export default function ChorusProPage() {
  const [factures, setFactures] = useState([]);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [transmitting, setTransmitting] = useState(false);
  const [selected, setSelected] = useState([]);
  const [search, setSearch] = useState('');
  const [statutFilter, setStatutFilter] = useState('');
  const [stats, setStats] = useState(null);
  const [snackbar, setSnackbar] = useState({ open: false, message: '', severity: 'info' });
  const [editDialog, setEditDialog] = useState({ open: false, facture: null, siret: '', codeService: '' });
  const [testDialog, setTestDialog] = useState({ open: false, siret: '', codeService: '', running: false, result: null });

  const chargerFactures = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (statutFilter) params.append('statut', statutFilter);
      if (search) params.append('search', search);

      const response = await api.get(`/api/chorus/factures?${params}`);
      setFactures(response.data);
    } catch (error) {
      console.error('Erreur chargement factures:', error);
      setSnackbar({ open: true, message: 'Erreur lors du chargement des factures', severity: 'error' });
    } finally {
      setLoading(false);
    }
  }, [statutFilter, search]);

  const chargerStats = useCallback(async () => {
    try {
      const response = await api.get('/api/chorus/statistiques');
      setStats(response.data);
    } catch (error) {
      console.error('Erreur stats:', error);
    }
  }, []);

  useEffect(() => {
    chargerFactures();
    chargerStats();
  }, [chargerFactures, chargerStats]);

  const synchroniserKarlia = async () => {
    setSyncing(true);
    try {
      const response = await api.post('/api/chorus/synchro-factures');
      setSnackbar({
        open: true,
        message: response.data.message,
        severity: 'success'
      });
      chargerFactures();
      chargerStats();
    } catch (error) {
      setSnackbar({
        open: true,
        message: error.response?.data?.detail || 'Erreur lors de la synchronisation',
        severity: 'error'
      });
    } finally {
      setSyncing(false);
    }
  };

  const testerConnexion = async () => {
    try {
      const response = await api.get('/api/chorus/test-connexion');
      setSnackbar({
        open: true,
        message: response.data.ok ? `Connexion OK (${response.data.mode})` : `Erreur: ${response.data.error}`,
        severity: response.data.ok ? 'success' : 'error'
      });
    } catch (error) {
      setSnackbar({
        open: true,
        message: error.response?.data?.detail || 'Erreur test connexion',
        severity: 'error'
      });
    }
  };

  const transmettreFactures = async () => {
    if (selected.length === 0) {
      setSnackbar({ open: true, message: 'Sélectionnez au moins une facture', severity: 'warning' });
      return;
    }

    // Vérifier que toutes les factures ont un SIRET
    const facturesSansSiret = factures.filter(
      f => selected.includes(f.id) && !f.client_siret
    );
    if (facturesSansSiret.length > 0) {
      setSnackbar({
        open: true,
        message: `${facturesSansSiret.length} facture(s) sans SIRET. Veuillez compléter les SIRET avant transmission.`,
        severity: 'warning'
      });
      return;
    }

    setTransmitting(true);
    try {
      const response = await api.post('/api/chorus/transmettre', { facture_ids: selected });
      const { transmises, echecs } = response.data;

      let message = `${transmises} facture(s) transmise(s)`;
      if (echecs > 0) message += `, ${echecs} échec(s)`;

      setSnackbar({
        open: true,
        message,
        severity: echecs > 0 ? 'warning' : 'success'
      });

      setSelected([]);
      chargerFactures();
      chargerStats();
    } catch (error) {
      setSnackbar({
        open: true,
        message: error.response?.data?.detail || 'Erreur lors de la transmission',
        severity: 'error'
      });
    } finally {
      setTransmitting(false);
    }
  };

  const handleSelectAll = (event) => {
    if (event.target.checked) {
      const transmissibles = factures
        .filter(f => f.statut_chorus === 'NON_TRANSMISE' || f.statut_chorus === 'ERREUR' || f.statut_chorus === 'REJETEE')
        .map(f => f.id);
      setSelected(transmissibles);
    } else {
      setSelected([]);
    }
  };

  const handleSelect = (id) => {
    setSelected(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    );
  };

  const ouvrirEditSiret = (facture) => {
    setEditDialog({
      open: true,
      facture,
      siret: facture.client_siret || '',
      codeService: facture.client_code_service || ''
    });
  };

  const lancerTestSoumission = async () => {
    if (testDialog.siret.length !== 14 || !/^\d{14}$/.test(testDialog.siret)) {
      setSnackbar({ open: true, message: 'SIRET destinataire invalide (14 chiffres)', severity: 'warning' });
      return;
    }
    setTestDialog(prev => ({ ...prev, running: true, result: null }));
    try {
      const response = await api.post('/api/chorus/test-soumission', {
        destinataire_siret: testDialog.siret,
        destinataire_code_service: testDialog.codeService || null,
        montant_ht: 1.0,
        taux_tva: 20.0,
      });
      setTestDialog(prev => ({ ...prev, running: false, result: response.data }));
      setSnackbar({
        open: true,
        message: response.data.succes ? `Test ${response.data.numero_facture} OK` : `Test ${response.data.numero_facture} échoué`,
        severity: response.data.succes ? 'success' : 'error',
      });
      chargerFactures();
    } catch (error) {
      const detail = error.response?.data?.detail;
      const msg = typeof detail === 'object' ? (detail.message || JSON.stringify(detail)) : (detail || error.message);
      setTestDialog(prev => ({ ...prev, running: false, result: { succes: false, erreur: msg, http_status: error.response?.status } }));
      setSnackbar({ open: true, message: msg || 'Erreur test soumission', severity: 'error' });
    }
  };

  const sauvegarderSiret = async () => {
    try {
      await api.put(
        `/api/chorus/factures/${editDialog.facture.id}/siret`,
        null,
        { params: { siret: editDialog.siret, code_service: editDialog.codeService || undefined } }
      );
      setSnackbar({ open: true, message: 'SIRET mis à jour', severity: 'success' });
      setEditDialog({ open: false, facture: null, siret: '', codeService: '' });
      chargerFactures();
    } catch (error) {
      setSnackbar({
        open: true,
        message: error.response?.data?.detail || 'Erreur lors de la mise à jour',
        severity: 'error'
      });
    }
  };

  const facturesTransmissibles = factures.filter(
    f => f.statut_chorus === 'NON_TRANSMISE' || f.statut_chorus === 'ERREUR' || f.statut_chorus === 'REJETEE'
  );

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h4" gutterBottom sx={{ mb: 3 }}>
        Transmission Chorus Pro
      </Typography>

      {/* Statistiques */}
      {stats && stats.par_statut && stats.par_statut.length > 0 && (
        <Grid container spacing={2} sx={{ mb: 3 }}>
          {stats.par_statut.map((s) => {
            const statInfo = STATUT_LABELS[s.statut] || { label: s.statut, color: 'default' };
            return (
              <Grid item xs={6} sm={4} md={2} key={s.statut}>
                <Card variant="outlined">
                  <CardContent sx={{ textAlign: 'center', py: 1 }}>
                    <Chip
                      size="small"
                      label={statInfo.label}
                      color={statInfo.color}
                      sx={{ mb: 1 }}
                    />
                    <Typography variant="h5">{s.count}</Typography>
                    <Typography variant="caption" color="text.secondary">
                      {formatMontant(s.montant_total)}
                    </Typography>
                  </CardContent>
                </Card>
              </Grid>
            );
          })}
        </Grid>
      )}

      {/* Barre d'actions */}
      <Paper sx={{ p: 2, mb: 2 }}>
        <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', alignItems: 'center' }}>
          <Button
            variant="outlined"
            startIcon={syncing ? <CircularProgress size={18} /> : <SyncIcon />}
            onClick={synchroniserKarlia}
            disabled={syncing}
          >
            {syncing ? 'Synchronisation...' : 'Importer depuis Karlia'}
          </Button>

          <Button
            variant="contained"
            color="primary"
            startIcon={transmitting ? <CircularProgress size={18} color="inherit" /> : <SendIcon />}
            onClick={transmettreFactures}
            disabled={transmitting || selected.length === 0}
          >
            {transmitting ? 'Transmission...' : `Transmettre (${selected.length})`}
          </Button>

          <Button
            variant="text"
            startIcon={<InfoIcon />}
            onClick={testerConnexion}
          >
            Tester connexion
          </Button>

          <Button
            variant="outlined"
            color="warning"
            startIcon={<ScienceIcon />}
            onClick={() => setTestDialog({ open: true, siret: '', codeService: '', running: false, result: null })}
          >
            Test soumission
          </Button>

          <Box sx={{ flexGrow: 1 }} />

          <FormControl size="small" sx={{ minWidth: 150 }}>
            <InputLabel>Statut</InputLabel>
            <Select
              value={statutFilter}
              label="Statut"
              onChange={(e) => setStatutFilter(e.target.value)}
            >
              <MenuItem value="">Tous</MenuItem>
              <MenuItem value="NON_TRANSMISE">Non transmises</MenuItem>
              <MenuItem value="EN_COURS">En cours</MenuItem>
              <MenuItem value="TRANSMISE">Transmises</MenuItem>
              <MenuItem value="ACCEPTEE">Acceptées</MenuItem>
              <MenuItem value="REJETEE">Rejetées</MenuItem>
              <MenuItem value="ERREUR">Erreurs</MenuItem>
            </Select>
          </FormControl>

          <TextField
            size="small"
            placeholder="Rechercher..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && chargerFactures()}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon />
                </InputAdornment>
              )
            }}
            sx={{ width: 250 }}
          />

          <IconButton onClick={chargerFactures} disabled={loading}>
            <RefreshIcon />
          </IconButton>
        </Box>
      </Paper>

      {/* Tableau des factures */}
      <TableContainer component={Paper}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell padding="checkbox">
                <Checkbox
                  indeterminate={selected.length > 0 && selected.length < facturesTransmissibles.length}
                  checked={facturesTransmissibles.length > 0 && selected.length === facturesTransmissibles.length}
                  onChange={handleSelectAll}
                />
              </TableCell>
              <TableCell>N° Facture</TableCell>
              <TableCell>Client</TableCell>
              <TableCell>SIRET</TableCell>
              <TableCell align="right">Montant HT</TableCell>
              <TableCell>Date</TableCell>
              <TableCell>Statut</TableCell>
              <TableCell>Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={8} align="center" sx={{ py: 4 }}>
                  <CircularProgress />
                </TableCell>
              </TableRow>
            ) : factures.length === 0 ? (
              <TableRow>
                <TableCell colSpan={8} align="center" sx={{ py: 4 }}>
                  <Typography color="text.secondary">
                    Aucune facture. Cliquez sur "Importer depuis Karlia" pour synchroniser.
                  </Typography>
                </TableCell>
              </TableRow>
            ) : (
              factures.map((facture) => {
                const statInfo = STATUT_LABELS[facture.statut_chorus] || { label: facture.statut_chorus, color: 'default' };
                const isTransmissible = ['NON_TRANSMISE', 'ERREUR', 'REJETEE'].includes(facture.statut_chorus);

                return (
                  <TableRow
                    key={facture.id}
                    hover
                    selected={selected.includes(facture.id)}
                    sx={{
                      backgroundColor: !facture.client_siret && isTransmissible ? 'rgba(255, 152, 0, 0.1)' : undefined
                    }}
                  >
                    <TableCell padding="checkbox">
                      <Checkbox
                        checked={selected.includes(facture.id)}
                        onChange={() => handleSelect(facture.id)}
                        disabled={!isTransmissible}
                      />
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2" fontWeight="medium">
                        {facture.numero_facture}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2">{facture.client_nom || '-'}</Typography>
                    </TableCell>
                    <TableCell>
                      {facture.client_siret ? (
                        <Typography variant="body2" fontFamily="monospace">
                          {facture.client_siret}
                        </Typography>
                      ) : (
                        <Chip size="small" label="Manquant" color="warning" />
                      )}
                    </TableCell>
                    <TableCell align="right">
                      <Typography variant="body2" fontWeight="medium">
                        {formatMontant(facture.montant_ht)}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2">{formatDate(facture.date_facture)}</Typography>
                    </TableCell>
                    <TableCell>
                      <Tooltip title={facture.chorus_message_erreur || ''}>
                        <Chip
                          size="small"
                          icon={statInfo.icon}
                          label={statInfo.label}
                          color={statInfo.color}
                        />
                      </Tooltip>
                    </TableCell>
                    <TableCell>
                      {isTransmissible && (
                        <Tooltip title="Modifier SIRET">
                          <IconButton size="small" onClick={() => ouvrirEditSiret(facture)}>
                            <EditIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Dialog édition SIRET */}
      <Dialog open={editDialog.open} onClose={() => setEditDialog({ ...editDialog, open: false })}>
        <DialogTitle>Modifier le destinataire Chorus Pro</DialogTitle>
        <DialogContent sx={{ minWidth: 400, pt: 2 }}>
          <Typography variant="body2" color="text.secondary" gutterBottom>
            Facture : {editDialog.facture?.numero_facture}
          </Typography>
          <Typography variant="body2" color="text.secondary" gutterBottom sx={{ mb: 2 }}>
            Client : {editDialog.facture?.client_nom}
          </Typography>
          <TextField
            label="SIRET destinataire"
            fullWidth
            value={editDialog.siret}
            onChange={(e) => setEditDialog({ ...editDialog, siret: e.target.value })}
            inputProps={{ maxLength: 14 }}
            helperText="14 chiffres - SIRET de la collectivité"
            sx={{ mb: 2, mt: 1 }}
          />
          <TextField
            label="Code service (optionnel)"
            fullWidth
            value={editDialog.codeService}
            onChange={(e) => setEditDialog({ ...editDialog, codeService: e.target.value })}
            helperText="Code du service exécutant dans Chorus Pro"
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditDialog({ open: false, facture: null, siret: '', codeService: '' })}>
            Annuler
          </Button>
          <Button
            variant="contained"
            onClick={sauvegarderSiret}
            disabled={editDialog.siret.length !== 14}
          >
            Enregistrer
          </Button>
        </DialogActions>
      </Dialog>

      {/* Dialog Test soumission */}
      <Dialog
        open={testDialog.open}
        onClose={() => !testDialog.running && setTestDialog({ open: false, siret: '', codeService: '', running: false, result: null })}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>🧪 Soumission de test à Chorus Pro</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Construit une facture fictive (1,00 € HT, TVA 20 %, numéro <code>TEST-YYYYMMDD-HHMMSS</code>) et l'envoie via le même builder que la soumission réelle. Permet de valider le format du payload sans consommer de vrai numéro Karlia.
          </Typography>
          <TextField
            label="SIRET destinataire (14 chiffres)"
            fullWidth
            value={testDialog.siret}
            onChange={(e) => setTestDialog(prev => ({ ...prev, siret: e.target.value.replace(/\D/g, '').slice(0, 14) }))}
            inputProps={{ maxLength: 14 }}
            helperText="SIRET d'une vraie collectivité publique (l'envoi se fera en sandbox si le mode qualification est activé)"
            sx={{ mb: 2, mt: 1 }}
          />
          <TextField
            label="Code service exécutant (optionnel)"
            fullWidth
            value={testDialog.codeService}
            onChange={(e) => setTestDialog(prev => ({ ...prev, codeService: e.target.value }))}
            helperText="À ne renseigner que si le destinataire l'exige"
            sx={{ mb: 2 }}
          />
          {testDialog.result && (
            <Alert
              severity={testDialog.result.succes ? 'success' : 'error'}
              sx={{ mt: 2 }}
            >
              <Typography variant="body2" sx={{ fontWeight: 'bold', mb: 1 }}>
                {testDialog.result.succes ? `✅ Succès — ${testDialog.result.numero_facture}` : `❌ Échec — ${testDialog.result.numero_facture || ''}`}
              </Typography>
              {testDialog.result.last_response && (
                <Box sx={{ mt: 1 }}>
                  <Typography variant="caption" component="div" sx={{ fontWeight: 'bold' }}>Status HTTP : {testDialog.result.last_response.status_code} {testDialog.result.last_response.reason || ''}</Typography>
                  {testDialog.result.last_response.x_correlation_id && (
                    <Typography variant="caption" component="div">x-correlationid : <code>{testDialog.result.last_response.x_correlation_id}</code></Typography>
                  )}
                </Box>
              )}
              <Box component="pre" sx={{ mt: 1, fontSize: '0.75rem', whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 300, overflow: 'auto', backgroundColor: 'rgba(0,0,0,0.04)', p: 1, borderRadius: 1 }}>
                {JSON.stringify({
                  succes: testDialog.result.succes,
                  numero_flux: testDialog.result.numero_flux,
                  id_facture_chorus: testDialog.result.id_facture_chorus,
                  erreur: testDialog.result.erreur,
                  request: testDialog.result.last_request,
                  response: testDialog.result.last_response,
                }, null, 2)}
              </Box>
            </Alert>
          )}
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => setTestDialog({ open: false, siret: '', codeService: '', running: false, result: null })}
            disabled={testDialog.running}
          >
            Fermer
          </Button>
          <Button
            variant="contained"
            color="warning"
            onClick={lancerTestSoumission}
            disabled={testDialog.running || testDialog.siret.length !== 14}
            startIcon={testDialog.running ? <CircularProgress size={16} color="inherit" /> : <ScienceIcon />}
          >
            {testDialog.running ? 'Envoi...' : 'Lancer le test'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Snackbar */}
      <Snackbar
        open={snackbar.open}
        autoHideDuration={6000}
        onClose={() => setSnackbar({ ...snackbar, open: false })}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert
          severity={snackbar.severity}
          onClose={() => setSnackbar({ ...snackbar, open: false })}
          sx={{ width: '100%' }}
        >
          {snackbar.message}
        </Alert>
      </Snackbar>
    </Box>
  );
}
