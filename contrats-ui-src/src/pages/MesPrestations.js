import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Paper, Typography, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, Button, IconButton, Chip, TextField,
  Dialog, DialogTitle, DialogContent, DialogActions, CircularProgress,
  Alert, Tooltip, Card, CardContent, Tabs, Tab, Divider
} from '@mui/material';
import {
  Event as EventIcon, CheckCircle as DoneIcon, Schedule as ScheduleIcon,
  PictureAsPdf as PdfIcon, Place as PlaceIcon, AccessTime as TimeIcon
} from '@mui/icons-material';
import { DatePicker } from '@mui/x-date-pickers/DatePicker';
import { TimePicker } from '@mui/x-date-pickers/TimePicker';
import { LocalizationProvider } from '@mui/x-date-pickers/LocalizationProvider';
import { AdapterDateFns } from '@mui/x-date-pickers/AdapterDateFns';
import { format, parseISO } from 'date-fns';
import { fr } from 'date-fns/locale';
import api from '../services/api';
import { useAuth } from '../context/AuthContext';

export default function MesPrestations() {
  const { user } = useAuth();
  const [prestations, setPrestations] = useState([]);
  const [stats, setStats] = useState({ a_planifier: 0, planifiees: 0, realisees: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [tabValue, setTabValue] = useState(0);
  const [formateurs, setFormateurs] = useState([]);
  const [selectedFormateur, setSelectedFormateur] = useState(null);

  // Dialog planification
  const [planifOpen, setPlanifOpen] = useState(false);
  const [selectedPrestation, setSelectedPrestation] = useState(null);
  const [datePlanifiee, setDatePlanifiee] = useState(null);
  const [heureDebut, setHeureDebut] = useState(null);
  const [heureFin, setHeureFin] = useState(null);
  const [lieu, setLieu] = useState('');
  const [notes, setNotes] = useState('');
  const [planifLoading, setPlanifLoading] = useState(false);

  // Charger les formateurs pour le sélecteur (admin)
  useEffect(() => {
    const fetchFormateurs = async () => {
      try {
        const res = await api.get('/api/formateurs?actif_only=true');
        setFormateurs(res.data.formateurs || []);
        // Par défaut, sélectionner le premier formateur ou celui lié à l'utilisateur
        if (res.data.formateurs?.length > 0) {
          setSelectedFormateur(res.data.formateurs[0]);
        }
      } catch (err) {
        console.error('Erreur chargement formateurs:', err);
      }
    };
    fetchFormateurs();
  }, []);

  const fetchPrestations = useCallback(async () => {
    if (!selectedFormateur) return;
    setLoading(true);
    try {
      const res = await api.get(`/api/prestations/formateur/${selectedFormateur.id}`);
      setPrestations(res.data.prestations || []);
      setStats({
        a_planifier: res.data.a_planifier || 0,
        planifiees: res.data.planifiees || 0,
        realisees: res.data.realisees || 0
      });
      setError(null);
    } catch (err) {
      setError('Erreur lors du chargement des prestations');
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [selectedFormateur]);

  useEffect(() => {
    fetchPrestations();
  }, [fetchPrestations]);

  const openPlanification = (prestation) => {
    setSelectedPrestation(prestation);
    setDatePlanifiee(prestation.date_planifiee ? parseISO(prestation.date_planifiee) : null);
    setHeureDebut(prestation.heure_debut ? parseISO(`2000-01-01T${prestation.heure_debut}`) : null);
    setHeureFin(prestation.heure_fin ? parseISO(`2000-01-01T${prestation.heure_fin}`) : null);
    setLieu(prestation.lieu || '');
    setNotes(prestation.notes || '');
    setPlanifOpen(true);
  };

  const handlePlanifier = async () => {
    if (!selectedPrestation || !datePlanifiee) return;
    setPlanifLoading(true);
    try {
      await api.post(`/api/prestations/${selectedPrestation.id}/planifier`, {
        date_planifiee: format(datePlanifiee, 'yyyy-MM-dd'),
        heure_debut: heureDebut ? format(heureDebut, 'HH:mm:ss') : null,
        heure_fin: heureFin ? format(heureFin, 'HH:mm:ss') : null,
        lieu: lieu || null,
        notes: notes || null
      });
      setSuccess('Prestation planifiée avec succès');
      setPlanifOpen(false);
      fetchPrestations();
    } catch (err) {
      setError(err.response?.data?.detail || 'Erreur lors de la planification');
    } finally {
      setPlanifLoading(false);
    }
  };

  const handleMarquerRealisee = async (prestation) => {
    try {
      await api.post(`/api/prestations/${prestation.id}/realiser`);
      setSuccess('Prestation marquée comme réalisée');
      fetchPrestations();
    } catch (err) {
      setError('Erreur lors de la mise à jour');
    }
  };

  const formatDate = (dateStr) => {
    if (!dateStr) return '-';
    try {
      return format(parseISO(dateStr), 'd MMM yyyy', { locale: fr });
    } catch {
      return dateStr;
    }
  };

  const formatTime = (timeStr) => {
    if (!timeStr) return '';
    return timeStr.substring(0, 5);
  };

  const getFilteredPrestations = () => {
    switch (tabValue) {
      case 0: return prestations.filter(p => p.statut === 'a_planifier');
      case 1: return prestations.filter(p => p.statut === 'planifiee');
      case 2: return prestations.filter(p => p.statut === 'realisee');
      default: return prestations;
    }
  };

  const getStatutChip = (statut) => {
    switch (statut) {
      case 'a_planifier':
        return <Chip label="À planifier" color="warning" size="small" />;
      case 'planifiee':
        return <Chip label="Planifiée" color="info" size="small" />;
      case 'realisee':
        return <Chip label="Réalisée" color="success" size="small" />;
      default:
        return <Chip label={statut} size="small" />;
    }
  };

  return (
    <LocalizationProvider dateAdapter={AdapterDateFns} adapterLocale={fr}>
      <Box sx={{ p: 3 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
          <Typography variant="h4" sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <ScheduleIcon color="primary" /> Mes Prestations
          </Typography>
          
          {/* Sélecteur de formateur (pour admin/manager) */}
          {formateurs.length > 1 && (
            <TextField
              select
              size="small"
              label="Formateur"
              value={selectedFormateur?.id || ''}
              onChange={(e) => {
                const f = formateurs.find(f => f.id === parseInt(e.target.value));
                setSelectedFormateur(f);
              }}
              sx={{ minWidth: 200 }}
              SelectProps={{ native: true }}
            >
              {formateurs.map(f => (
                <option key={f.id} value={f.id}>
                  {f.prenom} {f.nom}
                </option>
              ))}
            </TextField>
          )}
        </Box>

        {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>{error}</Alert>}
        {success && <Alert severity="success" sx={{ mb: 2 }} onClose={() => setSuccess(null)}>{success}</Alert>}

        {/* Stats */}
        <Box sx={{ display: 'flex', gap: 2, mb: 3 }}>
          <Card sx={{ flex: 1, bgcolor: 'warning.light' }}>
            <CardContent sx={{ textAlign: 'center', py: 2 }}>
              <Typography variant="h3">{stats.a_planifier}</Typography>
              <Typography variant="body2">À planifier</Typography>
            </CardContent>
          </Card>
          <Card sx={{ flex: 1, bgcolor: 'info.light' }}>
            <CardContent sx={{ textAlign: 'center', py: 2 }}>
              <Typography variant="h3">{stats.planifiees}</Typography>
              <Typography variant="body2">Planifiées</Typography>
            </CardContent>
          </Card>
          <Card sx={{ flex: 1, bgcolor: 'success.light' }}>
            <CardContent sx={{ textAlign: 'center', py: 2 }}>
              <Typography variant="h3">{stats.realisees}</Typography>
              <Typography variant="body2">Réalisées</Typography>
            </CardContent>
          </Card>
        </Box>

        {/* Tabs */}
        <Paper sx={{ mb: 2 }}>
          <Tabs value={tabValue} onChange={(e, v) => setTabValue(v)}>
            <Tab label={`À planifier (${stats.a_planifier})`} />
            <Tab label={`Planifiées (${stats.planifiees})`} />
            <Tab label={`Réalisées (${stats.realisees})`} />
          </Tabs>
        </Paper>

        {/* Table */}
        <TableContainer component={Paper}>
          <Table size="small">
            <TableHead>
              <TableRow sx={{ backgroundColor: 'grey.100' }}>
                <TableCell>Commande</TableCell>
                <TableCell>Client</TableCell>
                <TableCell>Désignation</TableCell>
                <TableCell align="center">Date planifiée</TableCell>
                <TableCell align="center">Horaires</TableCell>
                <TableCell>Lieu</TableCell>
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
              ) : getFilteredPrestations().length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} align="center" sx={{ py: 4 }}>
                    Aucune prestation
                  </TableCell>
                </TableRow>
              ) : (
                getFilteredPrestations().map((prest) => (
                  <TableRow key={prest.id} hover>
                    <TableCell>
                      <Typography variant="body2" fontWeight="medium">
                        {prest.reference_devis || '-'}
                      </Typography>
                    </TableCell>
                    <TableCell>{prest.client_nom || '-'}</TableCell>
                    <TableCell>
                      <Typography variant="body2">{prest.designation}</Typography>
                      {prest.description && (
                        <Typography variant="caption" color="text.secondary">
                          {prest.description}
                        </Typography>
                      )}
                    </TableCell>
                    <TableCell align="center">
                      {prest.date_planifiee ? (
                        <Chip 
                          icon={<EventIcon sx={{ fontSize: 16 }} />}
                          label={formatDate(prest.date_planifiee)} 
                          size="small" 
                          color="primary"
                          variant="outlined"
                        />
                      ) : '-'}
                    </TableCell>
                    <TableCell align="center">
                      {prest.heure_debut && (
                        <Typography variant="body2">
                          {formatTime(prest.heure_debut)}
                          {prest.heure_fin && ` - ${formatTime(prest.heure_fin)}`}
                        </Typography>
                      )}
                    </TableCell>
                    <TableCell>
                      {prest.lieu && (
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                          <PlaceIcon sx={{ fontSize: 16 }} color="action" />
                          <Typography variant="body2">{prest.lieu}</Typography>
                        </Box>
                      )}
                    </TableCell>
                    <TableCell align="center">
                      {prest.statut === 'a_planifier' && (
                        <Tooltip title="Planifier">
                          <IconButton size="small" color="primary" onClick={() => openPlanification(prest)}>
                            <EventIcon />
                          </IconButton>
                        </Tooltip>
                      )}
                      {prest.statut === 'planifiee' && (
                        <>
                          <Tooltip title="Modifier">
                            <IconButton size="small" color="primary" onClick={() => openPlanification(prest)}>
                              <EventIcon />
                            </IconButton>
                          </Tooltip>
                          <Tooltip title="Marquer réalisée">
                            <IconButton size="small" color="success" onClick={() => handleMarquerRealisee(prest)}>
                              <DoneIcon />
                            </IconButton>
                          </Tooltip>
                        </>
                      )}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </TableContainer>

        {/* Dialog Planification */}
        <Dialog open={planifOpen} onClose={() => setPlanifOpen(false)} maxWidth="sm" fullWidth>
          <DialogTitle>
            Planifier la prestation
          </DialogTitle>
          <DialogContent>
            {selectedPrestation && (
              <Box sx={{ mt: 1 }}>
                <Card variant="outlined" sx={{ mb: 3, bgcolor: 'grey.50' }}>
                  <CardContent>
                    <Typography variant="subtitle1" gutterBottom>
                      {selectedPrestation.reference_devis} — {selectedPrestation.client_nom}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      {selectedPrestation.designation}
                    </Typography>
                  </CardContent>
                </Card>

                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  <DatePicker
                    label="Date de la prestation *"
                    value={datePlanifiee}
                    onChange={setDatePlanifiee}
                    slotProps={{ textField: { fullWidth: true, required: true } }}
                  />

                  <Box sx={{ display: 'flex', gap: 2 }}>
                    <TimePicker
                      label="Heure début"
                      value={heureDebut}
                      onChange={setHeureDebut}
                      slotProps={{ textField: { fullWidth: true } }}
                    />
                    <TimePicker
                      label="Heure fin"
                      value={heureFin}
                      onChange={setHeureFin}
                      slotProps={{ textField: { fullWidth: true } }}
                    />
                  </Box>

                  <TextField
                    label="Lieu"
                    value={lieu}
                    onChange={(e) => setLieu(e.target.value)}
                    fullWidth
                    placeholder="Adresse ou nom du lieu"
                  />

                  <TextField
                    label="Notes"
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    fullWidth
                    multiline
                    rows={2}
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
              disabled={!datePlanifiee || planifLoading}
              startIcon={planifLoading ? <CircularProgress size={16} /> : <EventIcon />}
            >
              Planifier
            </Button>
          </DialogActions>
        </Dialog>
      </Box>
    </LocalizationProvider>
  );
}
