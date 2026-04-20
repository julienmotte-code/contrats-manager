import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Paper, Typography, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, Button, IconButton, Chip, TextField, InputAdornment,
  Dialog, DialogTitle, DialogContent, DialogActions, CircularProgress,
  Alert, Tooltip, TablePagination, Autocomplete, Divider, Card, CardContent
} from '@mui/material';
import {
  Search as SearchIcon, Visibility as ViewIcon, Schedule as ScheduleIcon,
  PictureAsPdf as PdfIcon, PersonAdd as AssignIcon, School as PrestationIcon
} from '@mui/icons-material';
import { format } from 'date-fns';
import { fr } from 'date-fns/locale';
import api from '../services/api';

export default function CommandesAPlanifier() {
  const [commandes, setCommandes] = useState([]);
  const [formateurs, setFormateurs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(20);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  // Dialog attribution
  const [attribOpen, setAttribOpen] = useState(false);
  const [selectedCommande, setSelectedCommande] = useState(null);
  const [selectedFormateur, setSelectedFormateur] = useState(null);
  const [attribLoading, setAttribLoading] = useState(false);

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

  const fetchFormateurs = async () => {
    try {
      const res = await api.get('/api/formateurs?actif_only=true');
      setFormateurs(res.data.formateurs || []);
    } catch (err) {
      console.error('Erreur chargement formateurs:', err);
    }
  };

  useEffect(() => {
    fetchCommandes();
    fetchFormateurs();
  }, [fetchCommandes]);

  const openAttribution = async (commande) => {
    // Charger le détail complet avec les lignes
    try {
      const res = await api.get(`/api/commandes/${commande.id}`);
      setSelectedCommande(res.data);
      setSelectedFormateur(null);
      setAttribOpen(true);
    } catch (err) {
      setError('Erreur lors du chargement de la commande');
    }
  };

  const handleAttribuer = async () => {
    if (!selectedCommande || !selectedFormateur) return;
    setAttribLoading(true);
    try {
      // Vérifier si des prestations existent déjà (réattribution)
      const prestRes = await api.get(`/api/prestations?commande_id=${selectedCommande.id}`);
      const hasExistingPrestations = prestRes.data.prestations?.length > 0;

      if (hasExistingPrestations) {
        // Réattribuer les prestations existantes
        await api.post(`/api/prestations/reattribuer-commande/${selectedCommande.id}?formateur_id=${selectedFormateur.id}`);
        setSuccess(`Prestations réattribuées à ${selectedFormateur.prenom || ''} ${selectedFormateur.nom}`);
      } else {
        // Créer les prestations depuis les lignes de commande
        await api.post(`/api/prestations/from-commande/${selectedCommande.id}?formateur_id=${selectedFormateur.id}`);
        // Mettre à jour le statut de la commande
        await api.put(`/api/commandes/${selectedCommande.id}`, {
          statut: 'a_planifier',
          formateur_id: selectedFormateur.id
        });
        setSuccess(`Commande attribuée à ${selectedFormateur.prenom || ''} ${selectedFormateur.nom}`);
      }
      
      setAttribOpen(false);
      fetchCommandes();
    } catch (err) {
      setError(err.response?.data?.detail || 'Erreur lors de l\'attribution');
      console.error(err);
    } finally {
      setAttribLoading(false);
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

  // Calcule le nombre total de prestations à créer (somme des quantités)
  const getNbPrestations = (lignes) => {
    if (!lignes || lignes.length === 0) return 0;
    return lignes.reduce((sum, l) => sum + (parseInt(l.quantite) || 1), 0);
  };

  return (
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
              <TableCell align="center">Prestations</TableCell>
              <TableCell align="right">Montant TTC</TableCell>
              <TableCell align="center">PDF</TableCell>
              <TableCell align="center">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={8} align="center" sx={{ py: 4 }}>
                  <CircularProgress />
                </TableCell>
              </TableRow>
            ) : commandes.length === 0 ? (
              <TableRow>
                <TableCell colSpan={8} align="center" sx={{ py: 4 }}>
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
                  <TableCell align="center">
                    <Chip 
                      icon={<PrestationIcon sx={{ fontSize: 16 }} />}
                      label={`${cmd.nb_prestations || 0} prestation(s)`}
                      color={cmd.nb_prestations_attribuees === cmd.nb_prestations && cmd.nb_prestations > 0 ? "success" : cmd.nb_prestations_attribuees > 0 ? "warning" : "default"} 
                      size="small" 
                      color="primary"
                      variant="outlined"
                    />
                  </TableCell>
                  <TableCell>
                    {cmd.formateur_nom ? (
                      <Chip label={cmd.formateur_nom} size="small" color="success" variant="outlined" />
                    ) : (
                      <Chip label="Non attribué" size="small" color="default" variant="outlined" />
                    )}
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
                    <Tooltip title="Attribuer à un formateur">
                      <IconButton size="small" color="primary" onClick={() => openAttribution(cmd)}>
                        <AssignIcon />
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

      {/* Dialog Attribution Formateur */}
      <Dialog open={attribOpen} onClose={() => setAttribOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>
          {selectedCommande?.formateur_nom ? 'Réattribuer la commande' : 'Attribuer la commande à un formateur'}
        </DialogTitle>
        <DialogContent>
          {selectedCommande && (
            <Box sx={{ mt: 1 }}>
              <Card variant="outlined" sx={{ mb: 3, bgcolor: 'grey.50' }}>
                <CardContent>
                  <Typography variant="h6" gutterBottom>
                    {selectedCommande.reference_devis} — {selectedCommande.client_nom}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    Montant : {formatMontant(selectedCommande.montant_ttc)} • 
                    Date acceptation : {formatDate(selectedCommande.date_acceptation)}
                  </Typography>
                </CardContent>
              </Card>

              <Typography variant="subtitle1" gutterBottom sx={{ fontWeight: 'bold' }}>
                Prestations à planifier ({getNbPrestations(selectedCommande.lignes)})
              </Typography>
              
              <TableContainer component={Paper} variant="outlined" sx={{ mb: 3 }}>
                <Table size="small">
                  <TableHead>
                    <TableRow sx={{ bgcolor: 'grey.100' }}>
                      <TableCell>Désignation</TableCell>
                      <TableCell align="center">Quantité</TableCell>
                      <TableCell align="right">Montant HT</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {selectedCommande.lignes?.map((ligne, idx) => (
                      <TableRow key={idx}>
                        <TableCell>
                          <Typography variant="body2">{ligne.designation}</Typography>
                          {ligne.description && (
                            <Typography variant="caption" color="text.secondary">
                              {ligne.description}
                            </Typography>
                          )}
                        </TableCell>
                        <TableCell align="center">
                          <Chip label={ligne.quantite || 1} size="small" color="info" />
                        </TableCell>
                        <TableCell align="right">{formatMontant(ligne.montant_ht)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>

              <Divider sx={{ my: 2 }} />

              <Typography variant="subtitle1" gutterBottom sx={{ fontWeight: 'bold' }}>
                Assigner à un formateur
              </Typography>
              
              <Autocomplete
                options={formateurs}
                getOptionLabel={(opt) => `${opt.prenom || ''} ${opt.nom}`.trim()}
                value={selectedFormateur}
                onChange={(e, newVal) => setSelectedFormateur(newVal)}
                renderOption={(props, option) => (
                  <li {...props}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Box sx={{ 
                        width: 12, 
                        height: 12, 
                        borderRadius: '50%', 
                        backgroundColor: option.couleur 
                      }} />
                      <span>{option.prenom || ''} {option.nom}</span>
                      {option.nb_prestations_a_planifier > 0 && (
                        <Chip 
                          label={`${option.nb_prestations_a_planifier} en cours`} 
                          size="small" 
                          color="warning"
                          sx={{ ml: 1 }}
                        />
                      )}
                    </Box>
                  </li>
                )}
                renderInput={(params) => (
                  <TextField {...params} label="Sélectionner un formateur" required />
                )}
              />

              <Alert severity="info" sx={{ mt: 2 }}>
                {selectedCommande.formateur_nom ? (
                  <>
                    <strong>Formateur actuel :</strong> {selectedCommande.formateur_nom}<br/>
                    Les prestations existantes seront réattribuées au nouveau formateur.
                  </>
                ) : (
                  <>
                    <strong>{selectedCommande.nb_prestations || getNbPrestations(selectedCommande.lignes)} prestation(s)</strong> seront attribuées au formateur sélectionné.
                    Le formateur pourra ensuite planifier chaque prestation dans son agenda.
                  </>
                )}
              </Alert>
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAttribOpen(false)}>Annuler</Button>
          <Button 
            variant="contained" 
            onClick={handleAttribuer}
            disabled={!selectedFormateur || attribLoading}
            startIcon={attribLoading ? <CircularProgress size={16} /> : <AssignIcon />}
          >
            {selectedCommande?.formateur_nom ? 'Réattribuer' : 'Attribuer et créer les prestations'}
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
  );
}
