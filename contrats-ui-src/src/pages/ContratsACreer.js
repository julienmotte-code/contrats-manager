import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box, Paper, Typography, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, Button, IconButton, Chip, TextField, InputAdornment,
  Dialog, DialogTitle, DialogContent, DialogActions, CircularProgress,
  Alert, Tooltip, TablePagination, Grid
} from '@mui/material';
import {
  Search as SearchIcon, Visibility as ViewIcon, Add as AddIcon,
  PictureAsPdf as PdfIcon, PlaylistAdd as PlaylistAddIcon
} from '@mui/icons-material';
import { format } from 'date-fns';
import { fr } from 'date-fns/locale';
import api from '../services/api';

export default function ContratsACreer() {
  const navigate = useNavigate();
  const [commandes, setCommandes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(20);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState(null);

  // Dialog détail
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailCommande, setDetailCommande] = useState(null);

  const fetchCommandes = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/api/commandes/contrats-a-creer', {
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

  const handleCreerContrat = (commande) => {
    // Naviguer vers le tunnel de création avec les données pré-remplies
    navigate('/contrats/nouveau', {
      state: {
        fromCommande: commande.id,
        client: {
          karlia_id: commande.karlia_customer_id,
          nom: commande.client_nom,
          email: commande.client_email,
          telephone: commande.client_telephone,
          adresse: commande.client_adresse,
          siret: commande.client_siret
        },
        devis: {
          reference: commande.reference_devis,
          montant_ht: commande.montant_ht,
          montant_ttc: commande.montant_ttc,
          lignes: commande.lignes
        }
      }
    });
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
          <PlaylistAddIcon color="primary" /> Contrats à créer
        </Typography>
        <Chip label={`${total} commande(s)`} color="warning" />
      </Box>

      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>{error}</Alert>}

      <Alert severity="info" sx={{ mb: 2 }}>
        Ces commandes ont été marquées comme nécessitant la création d'un contrat ou avenant.
        Cliquez sur "Créer contrat" pour pré-remplir le formulaire avec les données du devis.
      </Alert>

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
              <TableCell>Référence devis</TableCell>
              <TableCell>Client</TableCell>
              <TableCell>Date acceptation</TableCell>
              <TableCell>Statut commande</TableCell>
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
                  Aucun contrat à créer
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
                  <TableCell>
                    <Chip 
                      label={
                        cmd.statut === 'a_planifier' ? 'À planifier' :
                        cmd.statut === 'planifiee' ? 'Planifiée' :
                        cmd.statut === 'a_commander' ? 'À traiter' :
                        cmd.statut === 'terminee' ? 'Terminée' :
                        cmd.statut
                      }
                      size="small"
                      color={
                        cmd.statut === 'terminee' ? 'success' :
                        cmd.statut === 'planifiee' ? 'primary' :
                        'default'
                      }
                    />
                  </TableCell>
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
                    <Tooltip title="Créer le contrat">
                      <Button
                        size="small"
                        variant="contained"
                        color="primary"
                        startIcon={<AddIcon />}
                        onClick={() => handleCreerContrat(cmd)}
                        sx={{ ml: 1 }}
                      >
                        Créer contrat
                      </Button>
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

      {/* Dialog Détail */}
      <Dialog open={detailOpen} onClose={() => setDetailOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>Détail de la commande</DialogTitle>
        <DialogContent>
          {detailCommande && (
            <Box sx={{ mt: 1 }}>
              <Grid container spacing={2}>
                <Grid item xs={6}>
                  <Typography variant="subtitle2" color="text.secondary">Référence devis</Typography>
                  <Typography gutterBottom>{detailCommande.reference_devis || '-'}</Typography>
                </Grid>
                <Grid item xs={6}>
                  <Typography variant="subtitle2" color="text.secondary">Client</Typography>
                  <Typography gutterBottom>{detailCommande.client_nom || '-'}</Typography>
                </Grid>
                <Grid item xs={6}>
                  <Typography variant="subtitle2" color="text.secondary">Email</Typography>
                  <Typography gutterBottom>{detailCommande.client_email || '-'}</Typography>
                </Grid>
                <Grid item xs={6}>
                  <Typography variant="subtitle2" color="text.secondary">Téléphone</Typography>
                  <Typography gutterBottom>{detailCommande.client_telephone || '-'}</Typography>
                </Grid>
                <Grid item xs={6}>
                  <Typography variant="subtitle2" color="text.secondary">SIRET</Typography>
                  <Typography gutterBottom>{detailCommande.client_siret || '-'}</Typography>
                </Grid>
                <Grid item xs={6}>
                  <Typography variant="subtitle2" color="text.secondary">Date acceptation</Typography>
                  <Typography gutterBottom>{formatDate(detailCommande.date_acceptation)}</Typography>
                </Grid>
                <Grid item xs={12}>
                  <Typography variant="subtitle2" color="text.secondary">Adresse</Typography>
                  <Typography sx={{ whiteSpace: 'pre-line' }}>{detailCommande.client_adresse || '-'}</Typography>
                </Grid>
              </Grid>

              <Typography variant="h6" sx={{ mt: 3, mb: 1 }}>Lignes du devis</Typography>
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
          {detailCommande && (
            <Button
              variant="contained"
              color="primary"
              startIcon={<AddIcon />}
              onClick={() => {
                setDetailOpen(false);
                handleCreerContrat(detailCommande);
              }}
            >
              Créer le contrat
            </Button>
          )}
        </DialogActions>
      </Dialog>
    </Box>
  );
}
