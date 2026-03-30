import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Paper, Typography, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, Button, IconButton, Chip, TextField, InputAdornment,
  Dialog, DialogTitle, DialogContent, DialogActions, CircularProgress,
  Alert, Card, CardContent, Grid, Radio, RadioGroup, FormControlLabel,
  FormControl, FormLabel, Checkbox, Tooltip, TablePagination
} from '@mui/material';
import {
  Sync as SyncIcon, Search as SearchIcon, Visibility as ViewIcon,
  Check as CheckIcon, PictureAsPdf as PdfIcon, NewReleases as NewIcon
} from '@mui/icons-material';
import { format } from 'date-fns';
import { fr } from 'date-fns/locale';
import api from '../services/api';

export default function NouvellesCommandes() {
  const [commandes, setCommandes] = useState([]);
  const [stats, setStats] = useState({});
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(20);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  // Dialog validation
  const [validationOpen, setValidationOpen] = useState(false);
  const [selectedCommande, setSelectedCommande] = useState(null);
  const [typeTraitement, setTypeTraitement] = useState('a_planifier');
  const [necessiteContrat, setNecessiteContrat] = useState(false);
  const [validating, setValidating] = useState(false);

  // Dialog détail
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailCommande, setDetailCommande] = useState(null);

  const fetchStats = useCallback(async () => {
    try {
      const res = await api.get('/api/commandes/stats');
      setStats(res.data);
    } catch (err) {
      console.error('Erreur stats:', err);
    }
  }, []);

  const fetchCommandes = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/api/commandes/nouvelles', {
        params: { page: page + 1, page_size: rowsPerPage, search: search || undefined }
      });
      setCommandes(res.data.items);
      setTotal(res.data.total);
      setError(null);
    } catch (err) {
      setError('Erreur lors du chargement des commandes');
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [page, rowsPerPage, search]);

  useEffect(() => {
    fetchStats();
    fetchCommandes();
  }, [fetchStats, fetchCommandes]);

  const handleSync = async (forceFull = false) => {
    setSyncing(true);
    setError(null);
    try {
      const res = await api.post(`/api/commandes/sync?force_full=${forceFull}`);
      setSuccess(`Synchronisation terminée : ${res.data.nouveaux_devis} nouveaux, ${res.data.devis_mis_a_jour} mis à jour`);
      fetchCommandes();
      fetchStats();
    } catch (err) {
      setError('Erreur lors de la synchronisation');
      console.error(err);
    } finally {
      setSyncing(false);
    }
  };

  const openValidation = (commande) => {
    setSelectedCommande(commande);
    setTypeTraitement('a_planifier');
    setNecessiteContrat(false);
    setValidationOpen(true);
  };

  const handleValidation = async () => {
    if (!selectedCommande) return;
    setValidating(true);
    try {
      await api.post(`/api/commandes/${selectedCommande.id}/valider`, {
        type_traitement: typeTraitement,
        necessite_contrat: necessiteContrat
      });
      setSuccess('Commande validée avec succès');
      setValidationOpen(false);
      fetchCommandes();
      fetchStats();
    } catch (err) {
      setError('Erreur lors de la validation');
      console.error(err);
    } finally {
      setValidating(false);
    }
  };

  const openDetail = async (commande) => {
    try {
      const res = await api.get(`/api/commandes/${commande.id}`);
      setDetailCommande(res.data);
      setDetailOpen(true);
    } catch (err) {
      setError('Erreur lors du chargement du détail');
    }
  };

  const handleDownloadPdf = (commande) => {
    window.open(`/api/commandes/${commande.id}/pdf`, '_blank');
  };

  const formatDate = (dateStr) => {
    if (!dateStr) return '-';
    try {
      return format(new Date(dateStr + 'T12:00:00'), 'd MMM yyyy', { locale: fr });
    } catch {
      return dateStr;
    }
  };

  const formatMontant = (montant) => {
    if (montant === null || montant === undefined) return '-';
    return new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR' }).format(montant);
  };

  return (
    <Box sx={{ p: 3 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h4" sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <NewIcon color="primary" /> Nouvelles Commandes
        </Typography>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Button
            variant="outlined"
            startIcon={syncing ? <CircularProgress size={20} /> : <SyncIcon />}
            onClick={() => handleSync(false)}
            disabled={syncing}
          >
            Synchroniser
          </Button>
          <Button
            variant="contained"
            startIcon={syncing ? <CircularProgress size={20} /> : <SyncIcon />}
            onClick={() => handleSync(true)}
            disabled={syncing}
          >
            Sync complète
          </Button>
        </Box>
      </Box>

      {/* Stats */}
      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid item xs={12} sm={6} md={2.4}>
          <Card>
            <CardContent sx={{ textAlign: 'center', py: 1 }}>
              <Typography variant="h4" color="warning.main">{stats.nouvelles || 0}</Typography>
              <Typography variant="body2" color="text.secondary">Nouvelles</Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} sm={6} md={2.4}>
          <Card>
            <CardContent sx={{ textAlign: 'center', py: 1 }}>
              <Typography variant="h4" color="info.main">{stats.a_planifier || 0}</Typography>
              <Typography variant="body2" color="text.secondary">À planifier</Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} sm={6} md={2.4}>
          <Card>
            <CardContent sx={{ textAlign: 'center', py: 1 }}>
              <Typography variant="h4" color="primary.main">{stats.planifiees || 0}</Typography>
              <Typography variant="body2" color="text.secondary">Planifiées</Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} sm={6} md={2.4}>
          <Card>
            <CardContent sx={{ textAlign: 'center', py: 1 }}>
              <Typography variant="h4" color="secondary.main">{stats.a_commander || 0}</Typography>
              <Typography variant="body2" color="text.secondary">À traiter</Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} sm={6} md={2.4}>
          <Card>
            <CardContent sx={{ textAlign: 'center', py: 1 }}>
              <Typography variant="h4" color="error.main">{stats.contrats_a_creer || 0}</Typography>
              <Typography variant="body2" color="text.secondary">Contrats à créer</Typography>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>{error}</Alert>}
      {success && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setSuccess(null)}>{success}</Alert>}

      {/* Recherche */}
      <Box sx={{ mb: 2 }}>
        <TextField
          size="small"
          placeholder="Rechercher par client ou référence..."
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(0); }}
          InputProps={{
            startAdornment: <InputAdornment position="start"><SearchIcon /></InputAdornment>
          }}
          sx={{ width: 350 }}
        />
      </Box>

      {/* Table */}
      <TableContainer component={Paper}>
        <Table size="small">
          <TableHead>
            <TableRow sx={{ backgroundColor: 'grey.100' }}>
              <TableCell>Référence</TableCell>
              <TableCell>Client</TableCell>
              <TableCell>Date devis</TableCell>
              <TableCell>Date acceptation</TableCell>
              <TableCell align="right">Montant TTC</TableCell>
              <TableCell align="center">PDF</TableCell>
              <TableCell align="center">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={7} align="center" sx={{ py: 4 }}>
                  <CircularProgress />
                </TableCell>
              </TableRow>
            ) : commandes.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} align="center" sx={{ py: 4 }}>
                  Aucune nouvelle commande
                </TableCell>
              </TableRow>
            ) : (
              commandes.map((cmd) => (
                <TableRow key={cmd.id} hover>
                  <TableCell>
                    <Typography variant="body2" fontWeight="medium">
                      {cmd.reference_devis || '-'}
                    </Typography>
                  </TableCell>
                  <TableCell>{cmd.client_nom || '-'}</TableCell>
                  <TableCell>{formatDate(cmd.date_devis)}</TableCell>
                  <TableCell>{formatDate(cmd.date_acceptation)}</TableCell>
                  <TableCell align="right">
                    <Typography fontWeight="medium">{formatMontant(cmd.montant_ttc)}</Typography>
                  </TableCell>
                  <TableCell align="center">
                    {cmd.pdf_disponible ? (
                      <IconButton size="small" color="error" onClick={() => handleDownloadPdf(cmd)}>
                        <PdfIcon />
                      </IconButton>
                    ) : '-'}
                  </TableCell>
                  <TableCell align="center">
                    <Tooltip title="Voir détail">
                      <IconButton size="small" onClick={() => openDetail(cmd)}>
                        <ViewIcon />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="Valider">
                      <IconButton size="small" color="primary" onClick={() => openValidation(cmd)}>
                        <CheckIcon />
                      </IconButton>
                    </Tooltip>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
        <TablePagination
          component="div"
          count={total}
          page={page}
          onPageChange={(e, newPage) => setPage(newPage)}
          rowsPerPage={rowsPerPage}
          onRowsPerPageChange={(e) => { setRowsPerPage(parseInt(e.target.value, 10)); setPage(0); }}
          rowsPerPageOptions={[10, 20, 50]}
          labelRowsPerPage="Par page"
        />
      </TableContainer>

      {/* Dialog Validation */}
      <Dialog open={validationOpen} onClose={() => setValidationOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Valider la commande</DialogTitle>
        <DialogContent>
          {selectedCommande && (
            <Box sx={{ mt: 1 }}>
              <Typography variant="subtitle1" gutterBottom>
                {selectedCommande.reference_devis} — {selectedCommande.client_nom}
              </Typography>
              <Typography variant="body2" color="text.secondary" gutterBottom>
                Montant : {formatMontant(selectedCommande.montant_ttc)}
              </Typography>

              <FormControl sx={{ mt: 3 }}>
                <FormLabel>Type de traitement</FormLabel>
                <RadioGroup
                  value={typeTraitement}
                  onChange={(e) => setTypeTraitement(e.target.value)}
                >
                  <FormControlLabel
                    value="a_planifier"
                    control={<Radio />}
                    label="À planifier (intervention requise)"
                  />
                  <FormControlLabel
                    value="sans_planification"
                    control={<Radio />}
                    label="Sans planification (commande directe)"
                  />
                </RadioGroup>
              </FormControl>

              <Box sx={{ mt: 2 }}>
                <FormControlLabel
                  control={
                    <Checkbox
                      checked={necessiteContrat}
                      onChange={(e) => setNecessiteContrat(e.target.checked)}
                    />
                  }
                  label="Cette commande nécessite la création d'un contrat/avenant"
                />
              </Box>
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setValidationOpen(false)}>Annuler</Button>
          <Button
            variant="contained"
            onClick={handleValidation}
            disabled={validating}
            startIcon={validating ? <CircularProgress size={20} /> : <CheckIcon />}
          >
            Valider
          </Button>
        </DialogActions>
      </Dialog>

      {/* Dialog Détail */}
      <Dialog open={detailOpen} onClose={() => setDetailOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>Détail de la commande</DialogTitle>
        <DialogContent>
          {detailCommande && (
            <Box sx={{ mt: 1 }}>
              <Grid container spacing={2}>
                <Grid item xs={6}>
                  <Typography variant="subtitle2" color="text.secondary">Référence</Typography>
                  <Typography>{detailCommande.reference_devis || '-'}</Typography>
                </Grid>
                <Grid item xs={6}>
                  <Typography variant="subtitle2" color="text.secondary">Client</Typography>
                  <Typography>{detailCommande.client_nom || '-'}</Typography>
                </Grid>
                <Grid item xs={6}>
                  <Typography variant="subtitle2" color="text.secondary">Email</Typography>
                  <Typography>{detailCommande.client_email || '-'}</Typography>
                </Grid>
                <Grid item xs={6}>
                  <Typography variant="subtitle2" color="text.secondary">Téléphone</Typography>
                  <Typography>{detailCommande.client_telephone || '-'}</Typography>
                </Grid>
                <Grid item xs={12}>
                  <Typography variant="subtitle2" color="text.secondary">Adresse</Typography>
                  <Typography sx={{ whiteSpace: 'pre-line' }}>{detailCommande.client_adresse || '-'}</Typography>
                </Grid>
              </Grid>

              <Typography variant="h6" sx={{ mt: 3, mb: 2 }}>Lignes du devis</Typography>
              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Désignation</TableCell>
                      <TableCell align="right">Qté</TableCell>
                      <TableCell align="right">P.U. HT</TableCell>
                      <TableCell align="right">TVA</TableCell>
                      <TableCell align="right">Total HT</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {detailCommande.lignes?.map((ligne, idx) => (
                      <TableRow key={idx}>
                        <TableCell>{ligne.designation}</TableCell>
                        <TableCell align="right">{ligne.quantite}</TableCell>
                        <TableCell align="right">{formatMontant(ligne.prix_unitaire_ht)}</TableCell>
                        <TableCell align="right">{ligne.taux_tva}%</TableCell>
                        <TableCell align="right">{formatMontant(ligne.montant_ht)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>

              <Box sx={{ mt: 2, textAlign: 'right' }}>
                <Typography>Total HT : {formatMontant(detailCommande.montant_ht)}</Typography>
                <Typography>TVA : {formatMontant(detailCommande.montant_tva)}</Typography>
                <Typography variant="h6">Total TTC : {formatMontant(detailCommande.montant_ttc)}</Typography>
              </Box>
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDetailOpen(false)}>Fermer</Button>
          {detailCommande?.pdf_disponible && (
            <Button
              variant="outlined"
              color="error"
              startIcon={<PdfIcon />}
              onClick={() => handleDownloadPdf(detailCommande)}
            >
              Télécharger PDF
            </Button>
          )}
        </DialogActions>
      </Dialog>
    </Box>
  );
}
