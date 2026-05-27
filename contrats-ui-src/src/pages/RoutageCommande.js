import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Box, Paper, Typography, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, Button, Chip, CircularProgress, Alert, Card, CardContent,
  Grid, Select, MenuItem, FormControl, IconButton, Tooltip, Divider
} from '@mui/material';
import {
  ArrowBack as ArrowBackIcon, Check as CheckIcon, Close as CloseIcon,
  PictureAsPdf as PdfIcon, Route as RouteIcon
} from '@mui/icons-material';
import api from '../services/api';
import { openPdfWithAuth } from '../services/pdfFetch';

// Destinations métier (alignées sur routage_service.py côté backend).
// 'intitule' n'apparaît PAS dans le sélecteur : il est forcé pour les lignes
// d'intitulé Karlia (section_karlia === 1) et inséré automatiquement dans le
// payload final. L'utilisateur ne peut pas le choisir manuellement.
const DEST = {
  A_PLANIFIER: 'a_planifier',
  CONTRAT: 'contrat',
  FACTURATION_DIRECTE: 'facturation_directe',
  INTITULE: 'intitule',
};

const DEST_LABELS = {
  [DEST.A_PLANIFIER]: 'À planifier',
  [DEST.CONTRAT]: 'Contrat / avenant',
  [DEST.FACTURATION_DIRECTE]: 'Facturation directe',
  [DEST.INTITULE]: 'Intitulé',
};

const DEST_CHOICES_VRAIES_LIGNES = [
  DEST.A_PLANIFIER,
  DEST.CONTRAT,
  DEST.FACTURATION_DIRECTE,
];

// Couleurs des chips de récap, cohérentes avec NouvellesCommandes.js.
const DEST_COLORS = {
  [DEST.A_PLANIFIER]: 'info',
  [DEST.CONTRAT]: 'error',
  [DEST.FACTURATION_DIRECTE]: 'success',
  [DEST.INTITULE]: 'default',
};

const formatMontant = (montant) => {
  if (montant === null || montant === undefined) return '-';
  return new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR' }).format(montant);
};

// Math.ceil reflète la règle du backend (eclater_ligne_en_prestations) :
// partie entière + 1 si reste fractionnaire > 0, sinon partie entière.
// Aligné sur Math.ceil(quantite) pour les quantités positives.
const nbPrestationsPrevisionnelles = (quantite) => {
  if (quantite === null || quantite === undefined) return 1;
  const q = Number(quantite);
  if (!isFinite(q) || q <= 0) return 0;
  return Math.ceil(q);
};

export default function RoutageCommande() {
  const { id } = useParams();
  const navigate = useNavigate();

  const [commande, setCommande] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  // Map ligne_id -> destination courante (incluant les intitulés forcés).
  const [routage, setRoutage] = useState({});

  const fetchCommande = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get(`/api/commandes/${id}`);
      setCommande(res.data);
      // Initialisation : pour CHAQUE ligne, on prend la destination par défaut
      // calculée par le backend (qui force déjà 'intitule' quand
      // section_karlia === 1). Cela garantit la couverture totale exigée par
      // le backend (POST /valider).
      const init = {};
      for (const ligne of (res.data.lignes || [])) {
        init[ligne.id] = ligne.destination_defaut || DEST.FACTURATION_DIRECTE;
      }
      setRoutage(init);
      setError(null);
    } catch (err) {
      setError("Erreur lors du chargement de la commande");
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { fetchCommande(); }, [fetchCommande]);

  // Lignes triées par ordre Karlia (ordre du BC). Stable et déterministe.
  const lignesTriees = useMemo(() => {
    if (!commande?.lignes) return [];
    return [...commande.lignes].sort((a, b) => (a.ordre ?? 0) - (b.ordre ?? 0));
  }, [commande]);

  // Récap : compte par destination + total prestations prévisionnelles.
  const recap = useMemo(() => {
    const counts = {
      [DEST.A_PLANIFIER]: 0,
      [DEST.CONTRAT]: 0,
      [DEST.FACTURATION_DIRECTE]: 0,
      [DEST.INTITULE]: 0,
    };
    let nbPrestations = 0;
    for (const ligne of lignesTriees) {
      const dest = routage[ligne.id] || ligne.destination_defaut;
      if (counts[dest] !== undefined) counts[dest] += 1;
      if (dest === DEST.A_PLANIFIER) {
        nbPrestations += nbPrestationsPrevisionnelles(ligne.quantite);
      }
    }
    return { counts, nbPrestations };
  }, [routage, lignesTriees]);

  const handleChangeDest = (ligneId, value) => {
    setRoutage((prev) => ({ ...prev, [ligneId]: value }));
  };

  const handleValider = async () => {
    if (!commande) return;
    setSubmitting(true);
    setError(null);
    try {
      // Payload par-ligne : TOUTES les lignes de la commande, intitulés
      // inclus. Le backend exige une couverture totale (cf. /valider :
      // "Lignes non routées" si une ligne manque).
      const payload = {
        lignes: lignesTriees.map((l) => ({
          ligne_id: l.id,
          destination: routage[l.id] || l.destination_defaut,
        })),
      };
      await api.post(`/api/commandes/${id}/valider`, payload);
      navigate('/commandes/nouvelles', {
        state: { successMessage: `Commande ${commande.reference_devis || ''} validée avec succès` },
      });
    } catch (err) {
      const detail = err.response?.data?.detail;
      setError(detail ? `Erreur de validation : ${detail}` : 'Erreur lors de la validation');
      console.error(err);
    } finally {
      setSubmitting(false);
    }
  };

  const handleAnnuler = () => navigate('/commandes/nouvelles');

  const handleDownloadPdf = () => {
    if (commande) openPdfWithAuth(`/api/commandes/${commande.id}/pdf`);
  };

  if (loading) {
    return (
      <Box sx={{ p: 3, display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: 400 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (!commande) {
    return (
      <Box sx={{ p: 3 }}>
        <Alert severity="error">{error || 'Commande introuvable'}</Alert>
        <Button sx={{ mt: 2 }} startIcon={<ArrowBackIcon />} onClick={handleAnnuler}>
          Retour aux nouvelles commandes
        </Button>
      </Box>
    );
  }

  return (
    <Box sx={{ p: 3 }}>
      {/* En-tête */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Tooltip title="Retour">
            <IconButton onClick={handleAnnuler}><ArrowBackIcon /></IconButton>
          </Tooltip>
          <Typography variant="h4" sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <RouteIcon color="primary" /> Routage de la commande
          </Typography>
        </Box>
        {commande.pdf_disponible && (
          <Button variant="outlined" color="error" startIcon={<PdfIcon />} onClick={handleDownloadPdf}>
            PDF du BC
          </Button>
        )}
      </Box>

      {/* Bloc info commande */}
      <Card sx={{ mb: 2 }}>
        <CardContent>
          <Grid container spacing={2}>
            <Grid item xs={12} sm={4}>
              <Typography variant="subtitle2" color="text.secondary">Référence</Typography>
              <Typography variant="h6">{commande.reference_devis || '-'}</Typography>
            </Grid>
            <Grid item xs={12} sm={5}>
              <Typography variant="subtitle2" color="text.secondary">Client</Typography>
              <Typography variant="h6">{commande.client_nom || '-'}</Typography>
            </Grid>
            <Grid item xs={12} sm={3}>
              <Typography variant="subtitle2" color="text.secondary">Montant TTC</Typography>
              <Typography variant="h6">{formatMontant(commande.montant_ttc)}</Typography>
            </Grid>
          </Grid>
        </CardContent>
      </Card>

      {error && <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>{error}</Alert>}

      {/* Tableau des lignes */}
      <TableContainer component={Paper}>
        <Table size="small">
          <TableHead>
            <TableRow sx={{ backgroundColor: 'grey.100' }}>
              <TableCell sx={{ width: 60 }} align="center">#</TableCell>
              <TableCell>Désignation</TableCell>
              <TableCell sx={{ width: 220 }}>Catégorie Karlia</TableCell>
              <TableCell align="right" sx={{ width: 80 }}>Qté</TableCell>
              <TableCell align="right" sx={{ width: 130 }}>Montant HT</TableCell>
              <TableCell sx={{ width: 280 }}>Destination</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {lignesTriees.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} align="center" sx={{ py: 4 }}>
                  Aucune ligne sur cette commande.
                </TableCell>
              </TableRow>
            ) : lignesTriees.map((ligne) => {
              const estIntitule = ligne.section_karlia === 1;
              const destCourante = routage[ligne.id] || ligne.destination_defaut;
              const cellSx = estIntitule
                ? { backgroundColor: 'grey.100', color: 'text.disabled' }
                : undefined;

              return (
                <TableRow
                  key={ligne.id}
                  sx={estIntitule ? { backgroundColor: 'grey.50' } : undefined}
                >
                  <TableCell align="center" sx={cellSx}>
                    {ligne.ordre !== null && ligne.ordre !== undefined ? ligne.ordre + 1 : '-'}
                  </TableCell>
                  <TableCell sx={cellSx}>
                    <Typography
                      variant="body2"
                      sx={{
                        fontStyle: estIntitule ? 'italic' : 'normal',
                        fontWeight: estIntitule ? 500 : 400,
                        color: estIntitule ? 'text.disabled' : 'text.primary',
                      }}
                    >
                      {ligne.designation || '-'}
                    </Typography>
                    {ligne.description && ligne.description !== ligne.designation && (
                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                        {ligne.description}
                      </Typography>
                    )}
                  </TableCell>
                  <TableCell sx={cellSx}>
                    {estIntitule ? (
                      <Typography variant="caption" color="text.disabled">—</Typography>
                    ) : ligne.product_category ? (
                      <Chip
                        size="small"
                        label={ligne.product_category}
                        variant="outlined"
                        sx={{ maxWidth: 220 }}
                      />
                    ) : (
                      <Typography variant="caption" color="text.secondary">non catégorisée</Typography>
                    )}
                  </TableCell>
                  <TableCell align="right" sx={cellSx}>
                    {estIntitule ? '-' : (ligne.quantite ?? '-')}
                  </TableCell>
                  <TableCell align="right" sx={cellSx}>
                    {estIntitule ? '-' : formatMontant(ligne.montant_ht)}
                  </TableCell>
                  <TableCell sx={cellSx}>
                    {estIntitule ? (
                      <Chip
                        size="small"
                        label="Intitulé (ignoré)"
                        variant="outlined"
                        sx={{ color: 'text.disabled', borderColor: 'grey.300' }}
                      />
                    ) : (
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        <FormControl size="small" sx={{ minWidth: 180 }}>
                          <Select
                            value={destCourante}
                            onChange={(e) => handleChangeDest(ligne.id, e.target.value)}
                          >
                            {DEST_CHOICES_VRAIES_LIGNES.map((d) => (
                              <MenuItem key={d} value={d}>{DEST_LABELS[d]}</MenuItem>
                            ))}
                          </Select>
                        </FormControl>
                        {destCourante === DEST.A_PLANIFIER && (
                          <Typography variant="caption" color="text.secondary">
                            → {nbPrestationsPrevisionnelles(ligne.quantite)} prestation(s)
                          </Typography>
                        )}
                      </Box>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Récap visuel */}
      <Paper sx={{ mt: 2, p: 2 }}>
        <Typography variant="subtitle1" gutterBottom>Récapitulatif</Typography>
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, alignItems: 'center' }}>
          <Chip
            color={DEST_COLORS[DEST.A_PLANIFIER]}
            label={`${recap.counts[DEST.A_PLANIFIER]} à planifier → ${recap.nbPrestations} prestation(s)`}
          />
          <Chip
            color={DEST_COLORS[DEST.CONTRAT]}
            label={`${recap.counts[DEST.CONTRAT]} en contrat`}
          />
          <Chip
            color={DEST_COLORS[DEST.FACTURATION_DIRECTE]}
            label={`${recap.counts[DEST.FACTURATION_DIRECTE]} en facturation directe`}
          />
          <Chip
            variant="outlined"
            label={`${recap.counts[DEST.INTITULE]} intitulé(s) ignoré(s)`}
          />
        </Box>
      </Paper>

      <Divider sx={{ my: 2 }} />

      {/* Actions */}
      <Box sx={{ display: 'flex', justifyContent: 'flex-end', gap: 1 }}>
        <Button
          variant="outlined"
          startIcon={<CloseIcon />}
          onClick={handleAnnuler}
          disabled={submitting}
        >
          Annuler
        </Button>
        <Button
          variant="contained"
          startIcon={submitting ? <CircularProgress size={20} /> : <CheckIcon />}
          onClick={handleValider}
          disabled={submitting || lignesTriees.length === 0}
        >
          Valider le routage
        </Button>
      </Box>
    </Box>
  );
}
