import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Paper, Typography, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, Button, IconButton, Chip, TextField, InputAdornment,
  Dialog, DialogTitle, DialogContent, DialogActions, CircularProgress,
  Alert, Tooltip, TablePagination, Autocomplete
} from '@mui/material';
import {
  Search as SearchIcon, Visibility as ViewIcon, Schedule as ScheduleIcon,
  PictureAsPdf as PdfIcon, Event as EventIcon
} from '@mui/icons-material';
import { DatePicker } from '@mui/x-date-pickers/DatePicker';
import { LocalizationProvider } from '@mui/x-date-pickers/LocalizationProvider';
import { AdapterDateFns } from '@mui/x-date-pickers/AdapterDateFns';
import { format } from 'date-fns';
import { fr } from 'date-fns/locale';
import api from '../services/api';

const INTERVENANTS = [
  { id: 1, nom: 'Jean Dupont' },
  { id: 2, nom: 'Marie Martin' },
  { id: 3, nom: 'Pierre Durand' },
  { id: 4, nom: 'Sophie Bernard' }
];

export default function CommandesAPlanifier() {
  const [commandes, setCommandes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(20);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  // Dialog planification
  const [planifOpen, setPlanifOpen] = useState(false);
  const [selectedCommande, setSelectedCommande] = useState(null);
  const [datePlanifiee, setDatePlanifiee] = useState(null);
  const [intervenant, setIntervenant] = useState(null);
  const [notesPlanification, setNotesPlanification] = useState('');
  const [planifLoading, setPlanifLoading] = useState(false);

  // Dialog détail
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailCommande, setDetailCommande] = useState(null);

  const fetchCommandes = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/api/commandes/a-planifier', {
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
    fetchCommandes();
  }, [fetchCommandes]);

  const openPlanif = (commande) => {
    setSelectedCommande(commande);
    setDatePlanifiee(null);
    setIntervenant(null);
    setNotesPlanification('');
    setPlanifOpen(true);
  };

  const handlePlanifier = async () => {
    if (!selectedCommande || !datePlanifiee) return;
    setPlanifLoading(true);
    try {
      await api.post(`/api/commandes/${selectedCommande.id}/planifier`, {
        date_planifiee: format(datePlanifiee, 'yyyy-MM-dd'),
        intervenant_id: intervenant?.id || null,
        intervenant_nom: intervenant?.nom || null,
        notes_planification: notesPlanification || null
      });
      setSuccess('Commande planifiée avec succès');
      setPlanifOpen(false);
      fetchCommandes();
    } catch (err) {
      setError('Erreur lors de la planification');
      console.error(err);
    } finally {
      setPlanifLoading(false);
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

  const handleDownloadPdf = async (commande) => {
    try {
      const res = await api.get(`/api/commandes/${commande.id}/pdf`, { responseType: 'blob' });
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const link = document.createElement('a');
      link.href = url;
      link.download = commande.pdf_devis_nom || `devis_${commande.reference_devis}.pdf`;
      link.click();
    } catch (err) {
      setError('PDF non disponible');
    }
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
    <LocalizationProvider dateAdapter={AdapterDateFns} adapterLocale={fr}>
      <Box sx={{ p: 3 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
          <Typography variant="h4" sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <ScheduleIcon color="primary" /> Commandes à planifier
          </Typography>
          <Chip label={`${total} commande(s)`} color="info" />
        </Box>

        {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>{error}</Alert>}
        {success && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setSuccess(null)}>{success}</Alert>}

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

        <TableContainer component={Paper}>
          <Table size="small">
            <TableHead>
              <TableRow sx={{ backgroundColor: 'grey.100' }}>
                <TableCell>Référence</TableCell>
                <TableCell>Client</TableCell>
                <TableCell>Date acceptation</TableCell>
                <TableCell align="right">Montant TTC</TableCell>
                <TableCell align="center">Contrat</TableCell>
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
                    Aucune commande à planifier
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
                    <TableCell>{formatDate(cmd.date_acceptation)}</TableCell>
                    <TableCell align="right">
                      <Typography fontWeight="medium">{formatMontant(cmd.montant_ttc)}</Typography>
                    </TableCell>
                    <TableCell align="center">
                      {cmd.necessite_contrat && (
                        <Chip label="Contrat à créer" size="small" color="warning" />
                      )}
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
                      <Tooltip title="Planifier">
                        <IconButton size="small" color="primary" onClick={() => openPlanif(cmd)}>
                          <EventIcon />
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

        {/* Dialog Planification */}
        <Dialog open={planifOpen} onClose={() => setPlanifOpen(false)} maxWidth="sm" fullWidth>
          <DialogTitle>Planifier la commande</DialogTitle>
          <DialogContent>
            {selectedCommande && (
              <Box sx={{ mt: 1 }}>
                <Typography variant="subtitle1" gutterBottom>
                  {selectedCommande.reference_devis} — {selectedCommande.client_nom}
                </Typography>
                <Typography variant="body2" color="text.secondary" gutterBottom>
                  Montant : {formatMontant(selectedCommande.montant_ttc)}
                </Typography>

                <Box sx={{ mt: 3 }}>
                  <DatePicker
                    label="Date d'intervention"
                    value={datePlanifiee}
                    onChange={setDatePlanifiee}
                    slotProps={{ textField: { fullWidth: true, required: true } }}
                    minDate={new Date()}
                  />
                </Box>

                <Box sx={{ mt: 2 }}>
                  <Autocomplete
                    options={INTERVENANTS}
                    getOptionLabel={(opt) => opt.nom}
                    value={intervenant}
                    onChange={(e, newVal) => setIntervenant(newVal)}
                    renderInput={(params) => (
                      <TextField {...params} label="Intervenant" />
                    )}
                  />
                </Box>

                <Box sx={{ mt: 2 }}>
                  <TextField
                    label="Notes"
                    multiline
                    rows={3}
                    fullWidth
                    value={notesPlanification}
                    onChange={(e) => setNotesPlanification(e.target.value)}
                  />
                </Box>
              </Box>
            )}
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setPlanifOpen(false)}>Annuler</Button>
            <Button
              variant="contained"
              onClick={handlePlanifier}
              disabled={planifLoading || !datePlanifiee}
              startIcon={planifLoading ? <CircularProgress size={20} /> : <EventIcon />}
            >
              Planifier
            </Button>
          </DialogActions>
        </Dialog>

        {/* Dialog Détail */}
        <Dialog open={detailOpen} onClose={() => setDetailOpen(false)} maxWidth="md" fullWidth>
          <DialogTitle>Détail de la commande</DialogTitle>
          <DialogContent>
            {detailCommande && (
              <Box sx={{ mt: 1 }}>
                <Typography variant="subtitle2" color="text.secondary">Client</Typography>
                <Typography gutterBottom>{detailCommande.client_nom}</Typography>
                
                <Typography variant="subtitle2" color="text.secondary">Adresse</Typography>
                <Typography sx={{ whiteSpace: 'pre-line', mb: 2 }}>{detailCommande.client_adresse || '-'}</Typography>

                <Typography variant="h6" sx={{ mt: 2, mb: 1 }}>Lignes du devis</Typography>
                <TableContainer>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>Désignation</TableCell>
                        <TableCell align="right">Qté</TableCell>
                        <TableCell align="right">Total HT</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {detailCommande.lignes?.map((ligne, idx) => (
                        <TableRow key={idx}>
                          <TableCell>{ligne.designation}</TableCell>
                          <TableCell align="right">{ligne.quantite}</TableCell>
                          <TableCell align="right">{formatMontant(ligne.montant_ht)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>

                <Box sx={{ mt: 2, textAlign: 'right' }}>
                  <Typography variant="h6">Total TTC : {formatMontant(detailCommande.montant_ttc)}</Typography>
                </Box>
              </Box>
            )}
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setDetailOpen(false)}>Fermer</Button>
          </DialogActions>
        </Dialog>
      </Box>
    </LocalizationProvider>
  );
}
