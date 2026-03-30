import React, { useState, useEffect } from 'react';
import {
  Box, Typography, Paper, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, Button, IconButton, Dialog, DialogTitle,
  DialogContent, DialogActions, TextField, Switch, FormControlLabel,
  Alert, Chip, Tooltip
} from '@mui/material';
import {
  Add as AddIcon,
  Edit as EditIcon,
  Delete as DeleteIcon,
  Person as PersonIcon
} from '@mui/icons-material';
import api from '../services/api';

export default function Formateurs() {
  const [formateurs, setFormateurs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [currentFormateur, setCurrentFormateur] = useState(null);
  const [formData, setFormData] = useState({
    nom: '',
    prenom: '',
    email: '',
    email_google: '',
    telephone: '',
    couleur: '#3788d8'
  });

  useEffect(() => {
    fetchFormateurs();
  }, []);

  const fetchFormateurs = async () => {
    try {
      setLoading(true);
      const res = await api.get('/api/formateurs?actif_only=false');
      setFormateurs(res.data.formateurs || []);
    } catch (err) {
      setError('Erreur lors du chargement des formateurs');
    } finally {
      setLoading(false);
    }
  };

  const handleOpenDialog = (formateur = null) => {
    if (formateur) {
      setEditMode(true);
      setCurrentFormateur(formateur);
      setFormData({
        nom: formateur.nom || '',
        prenom: formateur.prenom || '',
        email: formateur.email || '',
        email_google: formateur.email_google || '',
        telephone: formateur.telephone || '',
        couleur: formateur.couleur || '#3788d8'
      });
    } else {
      setEditMode(false);
      setCurrentFormateur(null);
      setFormData({
        nom: '',
        prenom: '',
        email: '',
        email_google: '',
        telephone: '',
        couleur: '#3788d8'
      });
    }
    setDialogOpen(true);
  };

  const handleCloseDialog = () => {
    setDialogOpen(false);
    setCurrentFormateur(null);
    setFormData({
      nom: '',
      prenom: '',
      email: '',
      email_google: '',
      telephone: '',
      couleur: '#3788d8'
    });
  };

  const handleSubmit = async () => {
    try {
      if (editMode && currentFormateur) {
        await api.put(`/api/formateurs/${currentFormateur.id}`, formData);
        setSuccess('Formateur mis à jour');
      } else {
        await api.post('/api/formateurs', formData);
        setSuccess('Formateur créé');
      }
      handleCloseDialog();
      fetchFormateurs();
    } catch (err) {
      setError(err.response?.data?.detail || 'Erreur lors de la sauvegarde');
    }
  };

  const handleToggleActif = async (formateur) => {
    try {
      await api.put(`/api/formateurs/${formateur.id}`, { actif: !formateur.actif });
      setSuccess(`Formateur ${formateur.actif ? 'désactivé' : 'activé'}`);
      fetchFormateurs();
    } catch (err) {
      setError('Erreur lors de la modification');
    }
  };

  const handleDelete = async (formateur) => {
    if (!window.confirm(`Désactiver le formateur ${formateur.prenom} ${formateur.nom} ?`)) return;
    try {
      await api.delete(`/api/formateurs/${formateur.id}`);
      setSuccess('Formateur désactivé');
      fetchFormateurs();
    } catch (err) {
      setError('Erreur lors de la désactivation');
    }
  };

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h5">
          <PersonIcon sx={{ mr: 1, verticalAlign: 'middle' }} />
          Gestion des Formateurs
        </Typography>
        <Button variant="contained" startIcon={<AddIcon />} onClick={() => handleOpenDialog()}>
          Nouveau formateur
        </Button>
      </Box>

      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>{error}</Alert>}
      {success && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setSuccess('')}>{success}</Alert>}

      <TableContainer component={Paper}>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell>Nom</TableCell>
              <TableCell>Email</TableCell>
              <TableCell>Téléphone</TableCell>
              <TableCell align="center">Commandes</TableCell>
              <TableCell align="center">Prestations à planifier</TableCell>
              <TableCell align="center">Actif</TableCell>
              <TableCell align="center">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {formateurs.map((formateur) => (
              <TableRow key={formateur.id} sx={{ opacity: formateur.actif ? 1 : 0.5 }}>
                <TableCell>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <Box sx={{ 
                      width: 12, 
                      height: 12, 
                      borderRadius: '50%', 
                      backgroundColor: formateur.couleur 
                    }} />
                    {formateur.prenom} {formateur.nom}
                  </Box>
                </TableCell>
                <TableCell>{formateur.email}</TableCell>
                <TableCell>{formateur.telephone || '-'}</TableCell>
                <TableCell align="center">
                  <Chip label={formateur.nb_commandes} size="small" />
                </TableCell>
                <TableCell align="center">
                  {formateur.nb_prestations_a_planifier > 0 ? (
                    <Chip label={formateur.nb_prestations_a_planifier} color="warning" size="small" />
                  ) : (
                    <Chip label="0" size="small" />
                  )}
                </TableCell>
                <TableCell align="center">
                  <Switch 
                    checked={formateur.actif} 
                    onChange={() => handleToggleActif(formateur)}
                    size="small"
                  />
                </TableCell>
                <TableCell align="center">
                  <Tooltip title="Modifier">
                    <IconButton size="small" onClick={() => handleOpenDialog(formateur)}>
                      <EditIcon />
                    </IconButton>
                  </Tooltip>
                  <Tooltip title="Désactiver">
                    <IconButton size="small" onClick={() => handleDelete(formateur)} color="error">
                      <DeleteIcon />
                    </IconButton>
                  </Tooltip>
                </TableCell>
              </TableRow>
            ))}
            {formateurs.length === 0 && !loading && (
              <TableRow>
                <TableCell colSpan={7} align="center">
                  Aucun formateur enregistré
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Dialog ajout/modification */}
      <Dialog open={dialogOpen} onClose={handleCloseDialog} maxWidth="sm" fullWidth>
        <DialogTitle>
          {editMode ? 'Modifier le formateur' : 'Nouveau formateur'}
        </DialogTitle>
        <DialogContent>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, mt: 1 }}>
            <Box sx={{ display: 'flex', gap: 2 }}>
              <TextField
                label="Prénom"
                value={formData.prenom}
                onChange={(e) => setFormData({ ...formData, prenom: e.target.value })}
                fullWidth
              />
              <TextField
                label="Nom *"
                value={formData.nom}
                onChange={(e) => setFormData({ ...formData, nom: e.target.value })}
                fullWidth
                required
              />
            </Box>
            <TextField
              label="Email *"
              type="email"
              value={formData.email}
              onChange={(e) => setFormData({ ...formData, email: e.target.value })}
              fullWidth
              required
            />
            <TextField
              label="Email Google Calendar"
              type="email"
              value={formData.email_google}
              onChange={(e) => setFormData({ ...formData, email_google: e.target.value })}
              fullWidth
              helperText="Laissez vide pour utiliser l'email principal"
            />
            <TextField
              label="Téléphone"
              value={formData.telephone}
              onChange={(e) => setFormData({ ...formData, telephone: e.target.value })}
              fullWidth
            />
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
              <Typography>Couleur agenda :</Typography>
              <input
                type="color"
                value={formData.couleur}
                onChange={(e) => setFormData({ ...formData, couleur: e.target.value })}
                style={{ width: 50, height: 35, cursor: 'pointer' }}
              />
            </Box>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseDialog}>Annuler</Button>
          <Button 
            variant="contained" 
            onClick={handleSubmit}
            disabled={!formData.nom || !formData.email}
          >
            {editMode ? 'Enregistrer' : 'Créer'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
