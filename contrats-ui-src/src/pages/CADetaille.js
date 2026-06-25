import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Paper, Typography, Stack, Alert,
  Table, TableHead, TableBody, TableRow, TableCell, TableContainer,
  CircularProgress, Divider, Grid,
  Select, MenuItem, FormControl, InputLabel,
} from '@mui/material';
import { caAPI } from '../services/api';

const ANNEE_RECURRENT_MIN = 2026;          // pas de plan de facturation avant 2026
const anneeCourante = () => new Date().getFullYear();

const eur = (n) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR' }).format(Number(n) || 0);

// Nombre brut format FR sans devise (pour le tableau compact marge brute).
const num = (n) =>
  new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(n) || 0);

const pct = (n) => `${(Number(n) || 0).toFixed(1)} %`;
const pctSigne = (n) => `${n >= 0 ? '+' : ''}${Number(n).toFixed(1).replace('.', ',')} %`;

export default function CADetaille() {
  const [annee, setAnnee] = useState(null);
  const [annees, setAnnees] = useState([]);
  const [recurrent, setRecurrent] = useState(null);
  const [recap, setRecap] = useState(null);
  const [loading, setLoading] = useState(false);
  const [erreur, setErreur] = useState('');
  const [accesRefuse, setAccesRefuse] = useState(false);

  const handle403 = (e) => {
    if (e?.response?.status === 403) { setAccesRefuse(true); return true; }
    return false;
  };

  // Au montage : liste des annees disponibles (recap Excel), defaut = la plus recente.
  useEffect(() => {
    let actif = true;
    (async () => {
      try {
        const { data: res } = await caAPI.recapExcelAnnees();
        if (!actif) return;
        const liste = res?.annees || [];
        setAnnees(liste);
        setAccesRefuse(false);
        if (liste.length > 0) setAnnee(liste[0]); // deja triees desc cote API
      } catch (e) {
        if (!actif) return;
        if (!handle403(e)) setErreur(e?.response?.data?.detail || 'Erreur lors du chargement des années.');
      }
    })();
    return () => { actif = false; };
  }, []);

  // Au changement d'annee : charger les 2 blocs EN PARALLELE.
  const charger = useCallback(async (an) => {
    if (an == null) return;
    setErreur('');
    setLoading(true);
    try {
      const [rRec, rRecap] = await Promise.all([
        caAPI.recurrentParFamille(an),
        caAPI.recapExcel(an),
      ]);
      setRecurrent(rRec.data);
      setRecap(rRecap.data);
      setAccesRefuse(false);
    } catch (e) {
      if (!handle403(e)) {
        setErreur(e?.response?.data?.detail || 'Erreur lors du chargement du CA détaillé.');
      } else {
        setRecurrent(null);
        setRecap(null);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    charger(annee);
  }, [annee, charger]);

  // Defense en profondeur : le backend reste la garde (require_role).
  if (accesRefuse) {
    return (
      <Box sx={{ p: 3 }}>
        <Typography variant="h4" gutterBottom>CA détaillé</Typography>
        <Alert severity="warning" sx={{ mt: 2 }}>
          Accès réservé. Cet écran est réservé aux profils ADMIN, GESTIONNAIRE et DIRECTION.
        </Alert>
      </Box>
    );
  }

  const familles = recurrent?.familles || [];
  const moisLabels = recap?.mois_labels || [];
  const recapFamilles = recap?.familles || [];
  const totauxMois = recap?.totaux_mois || [];

  // RETOUCHE 1 : bloc recurrent indisponible avant 2026 (ou vide) -> message au lieu d'un vide.
  const recurrentMessage =
    (annee != null && annee < ANNEE_RECURRENT_MIN) || (recurrent != null && familles.length === 0);
  const recurrentTableau = recurrent != null && familles.length > 0 && !(annee != null && annee < ANNEE_RECURRENT_MIN);

  // Annee en cours -> recap partiel : prudence sur la variation.
  const anneeEnCours = annee === anneeCourante();

  // Styles compacts pour le tableau marge brute (doit tenir dans la page).
  const cellCompact = { fontSize: 12, py: 0.25, px: 0.75 };
  const cellCompactNum = { ...cellCompact, whiteSpace: 'nowrap' };

  // Cellule "Var. N/N-1" selon statut_var.
  const renderVariation = (f) => {
    if (f.statut_var === 'nouveau') {
      return <Typography component="span" variant="caption" sx={{ color: 'text.disabled' }}>nouveau</Typography>;
    }
    if (f.statut_var === 'n1_zero' || f.variation_pct == null) {
      return '—';
    }
    const v = f.variation_pct;
    return (
      <Typography component="span" sx={{ fontSize: 12, fontWeight: 600, color: v >= 0 ? 'success.main' : 'error.main' }}>
        {pctSigne(v)}
      </Typography>
    );
  };

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h4" gutterBottom>CA détaillé</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        CA récurrent contractuel (plan de facturation) et récapitulatif de marge brute
        (historiques Excel) pour une même année.
      </Typography>

      {/* Selecteur d'annee unique, commun aux deux blocs */}
      <Paper sx={{ p: 2, mb: 3 }}>
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} alignItems={{ sm: 'center' }}>
          <FormControl size="small" sx={{ minWidth: 160 }}>
            <InputLabel id="annee-label">Année</InputLabel>
            <Select
              labelId="annee-label"
              label="Année"
              value={annee ?? ''}
              onChange={(e) => setAnnee(Number(e.target.value))}
              disabled={annees.length === 0}
            >
              {annees.map((y) => (
                <MenuItem key={y} value={y}>{y}</MenuItem>
              ))}
            </Select>
          </FormControl>
          {loading && (
            <Stack direction="row" alignItems="center" spacing={1}>
              <CircularProgress size={18} />
              <Typography variant="body2" color="text.secondary">Chargement…</Typography>
            </Stack>
          )}
        </Stack>
        {erreur && <Alert severity="error" sx={{ mt: 2 }}>{erreur}</Alert>}
      </Paper>

      {/* ════════ BLOC 1 — CA recurrent par famille de contrat ════════ */}
      <Typography variant="h6" gutterBottom>CA récurrent par famille de contrat</Typography>

      {recurrentMessage && (
        <Alert severity="info" sx={{ mb: 4 }}>
          CA récurrent contractuel disponible à partir de 2026. Pour les exercices antérieurs,
          se reporter au récapitulatif des marges ci-dessous (données historiques).
        </Alert>
      )}

      {recurrentTableau && (
        <>
          <Grid container spacing={2} sx={{ mb: 2 }}>
            <Grid item xs={12} sm={6} md={3}>
              <Paper sx={{ p: 2 }}>
                <Typography variant="caption" color="text.secondary">CA récurrent HT</Typography>
                <Typography variant="h5" sx={{ mt: 0.5, color: 'primary.main' }}>{eur(recurrent.total_ca_ht)}</Typography>
              </Paper>
            </Grid>
            <Grid item xs={12} sm={6} md={3}>
              <Paper sx={{ p: 2 }}>
                <Typography variant="caption" color="text.secondary">Nb échéances</Typography>
                <Typography variant="h5" sx={{ mt: 0.5 }}>{(recurrent.nb_echeances ?? 0).toLocaleString('fr-FR')}</Typography>
              </Paper>
            </Grid>
          </Grid>

          <Paper sx={{ p: 2, mb: 4 }}>
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Famille</TableCell>
                    <TableCell align="right">Nb éch.</TableCell>
                    <TableCell align="right">CA HT</TableCell>
                    <TableCell>Part</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {familles.map((f) => (
                    <TableRow key={f.famille}>
                      <TableCell>{f.famille}</TableCell>
                      <TableCell align="right">{f.nb_echeances}</TableCell>
                      <TableCell align="right">{eur(f.ca_ht)}</TableCell>
                      <TableCell sx={{ minWidth: 160 }}>
                        <Stack direction="row" alignItems="center" spacing={1}>
                          <Box sx={{ flex: 1, height: 12, bgcolor: 'action.hover', borderRadius: 1, overflow: 'hidden' }}>
                            <Box sx={{ height: '100%', width: `${Math.max(2, f.part_pct || 0)}%`, bgcolor: 'primary.main' }} />
                          </Box>
                          <Typography variant="caption" color="text.secondary">{pct(f.part_pct)}</Typography>
                        </Stack>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>

            {recurrent.memo_karlia_vente_log != null && (
              <Typography variant="caption" sx={{ display: 'block', mt: 1.5, fontStyle: 'italic', color: 'text.disabled' }}>
                dont vente logiciels déjà facturée via Karlia : {eur(recurrent.memo_karlia_vente_log)}
                {' '}— sous-détail informatif, <strong>non additionné</strong> au total récurrent.
              </Typography>
            )}
          </Paper>
        </>
      )}

      <Divider sx={{ mb: 3 }} />

      {/* ════════ BLOC 2 — Recapitulatif marge brute (Excel + Karlia) ════════ */}
      <Typography variant="h6" gutterBottom>Récapitulatif marge brute (Excel)</Typography>

      {recap && (
        <Grid container spacing={2} sx={{ mb: 2 }}>
          <Grid item xs={12} sm={6} md={3}>
            <Paper sx={{ p: 2 }}>
              <Typography variant="caption" color="text.secondary">Marge brute {recap.annee}</Typography>
              <Typography variant="h5" sx={{ mt: 0.5, color: 'primary.main' }}>{eur(recap.total_annee)}</Typography>
            </Paper>
          </Grid>
        </Grid>
      )}

      {recap && recapFamilles.length > 0 && (
        <Paper sx={{ p: 2, mb: 2 }}>
          <TableContainer>
            <Table size="small" sx={{ '& td, & th': { ...cellCompact, whiteSpace: 'nowrap' } }}>
              <TableHead>
                <TableRow>
                  <TableCell sx={{ fontWeight: 700 }}>Famille / montants en €</TableCell>
                  {moisLabels.map((m) => (
                    <TableCell key={m} align="right">{m}</TableCell>
                  ))}
                  <TableCell align="right" sx={{ fontWeight: 700 }}>Total</TableCell>
                  <TableCell align="right" sx={{ fontWeight: 700 }}>Var. N/N-1</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {recapFamilles.map((f, i) => (
                  <TableRow key={`${f.code}-${i}`}>
                    <TableCell sx={cellCompact}>{f.famille}</TableCell>
                    {Array.from({ length: 12 }).map((_, k) => (
                      <TableCell key={k} align="right" sx={cellCompactNum}>
                        {f.mois[k] == null ? '' : num(f.mois[k])}
                      </TableCell>
                    ))}
                    <TableCell align="right" sx={{ ...cellCompactNum, fontWeight: 600 }}>{num(f.total)}</TableCell>
                    <TableCell align="right" sx={cellCompactNum}>{renderVariation(f)}</TableCell>
                  </TableRow>
                ))}
                <TableRow sx={{ '& td': { fontWeight: 700, borderTop: '2px solid', borderColor: 'divider' } }}>
                  <TableCell sx={cellCompact}>TOTAL</TableCell>
                  {Array.from({ length: 12 }).map((_, k) => (
                    <TableCell key={k} align="right" sx={cellCompactNum}>
                      {totauxMois[k] == null ? '' : num(totauxMois[k])}
                    </TableCell>
                  ))}
                  <TableCell align="right" sx={cellCompactNum}>{num(recap.total_annee)}</TableCell>
                  <TableCell align="right" sx={cellCompactNum}>—</TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </TableContainer>
        </Paper>
      )}

      {recap && recapFamilles.length === 0 && !loading && (
        <Alert severity="info">Aucun récapitulatif pour l’année {annee}.</Alert>
      )}

      {recap && recapFamilles.length > 0 && (
        <>
          <Divider sx={{ mb: 1 }} />
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
            Marge brute (CA − coût d’achat) issue des récapitulatifs annuels ; année en cours partielle.
            Bloc distinct du CA récurrent ci-dessus (grandeurs différentes, jamais additionnées).
          </Typography>
          {anneeEnCours && (
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5, fontStyle: 'italic' }}>
              Année en cours : variation vs N-1 à interpréter avec prudence (exercice incomplet).
            </Typography>
          )}
        </>
      )}
    </Box>
  );
}
