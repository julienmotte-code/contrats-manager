import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Paper, Typography, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, Button, IconButton, Chip, TextField, InputAdornment,
  Dialog, DialogTitle, DialogContent, DialogActions, CircularProgress,
  Alert, Tooltip, TablePagination
} from '@mui/material';
import {
  Search as SearchIcon, Visibility as ViewIcon, CheckCircle as DoneIcon,
  PictureAsPdf as PdfIcon, ShoppingCart as CartIcon
} from '@mui/icons-material';
import { format } from 'date-fns';
import { fr } from 'date-fns/locale';
import api from '../services/api';

export default function CommandesATraiter() {
  const [commandes, setCommandes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(20);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  // Dialog confirmation
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [selectedCommande, setSelectedCommande] = useState(null);
  const [terminerLoading, setTerminerLoading] = useState(false);

  // Dialog détail
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailCommande, setDetailCommande] = useState(null);

  const fetchCommandes = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/api/commandes/a-commander', {
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

  const openConfirm = (commande) => {
    setSelectedCommande(commande);
    setConfirmOpen(true);
  };

  const handleTerminer = async () => {
    if (!selectedCommande) return;
    setTerminerLoading(true);
    try {
      await api.post(`/api/commandes/${selectedCommande.id}/terminer`);
      setSuccess('Commande marquée comme terminée');
      setConfirmOpen(false);
      fetchCommandes();
    } catch (err) {
      setError('Erreur lors de la mise à jour');
      console.error(err);
    } finally {
      setTerminerLoading(false);
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
          <CartIcon color="primary" /> Commandes à traiter
        </Typography>
        <Chip label={`${total} commande(s)`} color="secondary" />
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
                  Aucune commande à traiter
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
                    <Tooltip title="Marquer terminée">
                      <IconButton size="small" color="success" onClick={() => openConfirm(cmd)}>
                        <DoneIcon />
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

      {/* Dialog Confirmation */}
      <Dialog open={confirmOpen} onClose={() => setConfirmOpen(false)}>
        <DialogTitle>Confirmer</DialogTitle>
        <DialogContent>
          <Typography>
            Marquer la commande <strong>{selectedCommande?.reference_devis}</strong> comme terminée ?
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmOpen(false)}>Annuler</Button>
          <Button
            variant="contained"
            color="success"
            onClick={handleTerminer}
            disabled={terminerLoading}
            startIcon={terminerLoading ? <CircularProgress size={20} /> : <DoneIcon />}
          >
            Terminer
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
              
              <Typography variant="subtitle2" color="text.secondary">Email</Typography>
              <Typography gutterBottom>{detailCommande.client_email || '-'}</Typography>
              
              <Typography variant="subtitle2" color="text.secondary">Téléphone</Typography>
              <Typography gutterBottom>{detailCommande.client_telephone || '-'}</Typography>

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
  );
}
