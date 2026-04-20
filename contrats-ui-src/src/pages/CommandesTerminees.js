import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Paper, Typography, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, IconButton, Chip, TextField, InputAdornment,
  Dialog, DialogTitle, DialogContent, DialogActions, CircularProgress,
  Alert, Tooltip, TablePagination, Button
} from '@mui/material';
import {
  Search as SearchIcon, Visibility as ViewIcon, Receipt as FactureIcon,
  PictureAsPdf as PdfIcon, CheckCircle as DoneIcon
} from '@mui/icons-material';
import { format } from 'date-fns';
import { fr } from 'date-fns/locale';
import api from '../services/api';

export default function CommandesTerminees() {
  const [commandes, setCommandes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(20);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  // Dialog détail
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailCommande, setDetailCommande] = useState(null);

  const fetchCommandes = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/api/commandes/terminees', {
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

  const [facturant, setFacturant] = useState(null);

  const handleFacturer = async (commande) => {
    if (!commande.karlia_customer_id) {
      setError('Client Karlia non renseigné - impossible de facturer');
      return;
    }
    setFacturant(commande.id);
    try {
      const res = await api.post(`/api/commandes/${commande.id}/facturer`);
      setSuccess(res.data.message || 'Facture émise avec succès');
      fetchCommandes();
    } catch (err) {
      setError(err.response?.data?.detail || 'Erreur lors de la facturation');
    } finally {
      setFacturant(null);
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
    <Box sx={{ p: 3 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h4" sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <DoneIcon color="success" /> Commandes terminées
        </Typography>
        <Chip label={`${total} commande(s)`} color="success" />
      </Box>

      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>{error}</Alert>}
      {success && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setSuccess(null)}>{success}</Alert>}

      <Paper sx={{ mb: 2, p: 2 }}>
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
      </Paper>

      <TableContainer component={Paper}>
        <Table size="small">
          <TableHead>
            <TableRow sx={{ backgroundColor: 'grey.100' }}>
              <TableCell>Référence</TableCell>
              <TableCell>Client</TableCell>
              <TableCell>Formateur</TableCell>
              <TableCell align="center">Prestations</TableCell>
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
                  Aucune commande terminée
                </TableCell>
              </TableRow>
            ) : (
              commandes.map((cmd) => (
                <TableRow key={cmd.id} hover>
                  <TableCell>
                    <Typography variant="body2" fontWeight="medium">{cmd.reference_devis}</Typography>
                  </TableCell>
                  <TableCell>{cmd.client_nom || '-'}</TableCell>
                  <TableCell>
                    {cmd.formateur_nom ? (
                      <Chip label={cmd.formateur_nom} size="small" color="primary" variant="outlined" />
                    ) : '-'}
                  </TableCell>
                  <TableCell align="center">
                    <Chip
                      label={`${cmd.nb_prestations_planifiees}/${cmd.nb_prestations} réalisée(s)`}
                      color="success"
                      size="small"
                      variant="outlined"
                    />
                  </TableCell>
                  <TableCell align="right">
                    <Typography fontWeight="medium">{formatMontant(cmd.montant_ttc)}</Typography>
                  </TableCell>
                  <TableCell align="center">
                    {cmd.pdf_disponible && (
                      <IconButton size="small" color="error" onClick={() => handleDownloadPdf(cmd)}>
                        <PdfIcon />
                      </IconButton>
                    )}
                  </TableCell>
                  <TableCell align="center">
                    <Tooltip title="Voir détail">
                      <IconButton size="small" onClick={() => openDetail(cmd)}>
                        <ViewIcon />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="Émettre facture Karlia">
                      <IconButton size="small" color="success" onClick={() => handleFacturer(cmd)} disabled={facturant === cmd.id}>
                        <FactureIcon />
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
          onPageChange={(e, p) => setPage(p)}
          rowsPerPage={rowsPerPage}
          onRowsPerPageChange={(e) => { setRowsPerPage(parseInt(e.target.value)); setPage(0); }}
          rowsPerPageOptions={[10, 20, 50]}
          labelRowsPerPage="Par page"
          labelDisplayedRows={({ from, to, count }) => `${from}-${to} of ${count}`}
        />
      </TableContainer>

      {/* Dialog Détail */}
      <Dialog open={detailOpen} onClose={() => setDetailOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>Détail de la commande</DialogTitle>
        <DialogContent>
          {detailCommande && (
            <Box sx={{ mt: 2 }}>
              <Typography variant="h6" gutterBottom>{detailCommande.reference_devis}</Typography>
              <Typography>Client : {detailCommande.client_nom || '-'}</Typography>
              <Typography>Montant TTC : {formatMontant(detailCommande.montant_ttc)}</Typography>
              <Typography>Formateur : {detailCommande.formateur_nom || '-'}</Typography>
              <Typography sx={{ mt: 2, fontWeight: 'bold' }}>Lignes :</Typography>
              {detailCommande.lignes?.map((l, i) => (
                <Typography key={i} variant="body2" sx={{ ml: 2 }}>
                  • {l.designation || 'Article'} - {formatMontant(l.montant_ht)} HT x {l.quantite}
                </Typography>
              ))}
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDetailOpen(false)}>Fermer</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
