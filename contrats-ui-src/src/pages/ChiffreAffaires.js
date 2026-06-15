import React, { useState, useEffect, useCallback } from 'react';
import {
  Box, Paper, Typography, TextField, Button, Stack, Alert,
  Table, TableHead, TableBody, TableRow, TableCell, TableContainer,
  CircularProgress, Chip, Divider, Tooltip,
} from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import { caAPI } from '../services/api';

const eur = (n) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR' }).format(Number(n) || 0);

const frDate = (iso) => {
  if (!iso) return '';
  const [y, m, d] = String(iso).slice(0, 10).split('-');
  return `${d}/${m}/${y}`;
};

const todayISO = () => {
  const d = new Date();
  const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
};
const defaultDebut = () => `${new Date().getFullYear()}-01-01`;

export default function ChiffreAffaires() {
  const [dateDebut, setDateDebut] = useState(defaultDebut());
  const [dateFin, setDateFin] = useState(todayISO());
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [refreshInfo, setRefreshInfo] = useState('');

  const charger = useCallback(async () => {
    if (dateFin < dateDebut) {
      setError('La date de fin est antérieure à la date de début.');
      return;
    }
    setError('');
    setLoading(true);
    try {
      const { data } = await caAPI.comparatif({ date_debut: dateDebut, date_fin: dateFin, n: 5 });
      setData(data);
    } catch (e) {
      setError(e?.response?.data?.detail || 'Erreur lors du calcul du chiffre d’affaires.');
    } finally {
      setLoading(false);
    }
  }, [dateDebut, dateFin]);

  useEffect(() => {
    charger();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const rafraichirKarlia = async () => {
    setRefreshing(true);
    setRefreshInfo('');
    setError('');
    try {
      const { data } = await caAPI.rafraichirKarlia();
      setRefreshInfo(
        `Miroir Karlia rafraîchi : ${data.nb_retenues} factures retenues ` +
        `(${data.nb_annulees} annulée(s) exclue(s)).`
      );
      await charger();
    } catch (e) {
      setError(e?.response?.data?.detail || 'Échec du rafraîchissement Karlia.');
    } finally {
      setRefreshing(false);
    }
  };

  const lignes = data?.comparatif || [];
  const maxTotal = lignes.reduce((m, l) => Math.max(m, l.ca_total || 0), 0) || 1;

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h4" gutterBottom>Chiffre d’affaires</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Comparatif sur une fenêtre de dates et les 5 exercices précédents (même période calendaire).
        Sources : factures historiques (n° ≤ 8900) et ventes Karlia (n° 8901+, hors annulées).
      </Typography>

      <Paper sx={{ p: 2, mb: 3 }}>
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} alignItems={{ sm: 'center' }}>
          <TextField label="Date de début" type="date" size="small" value={dateDebut}
            onChange={(e) => setDateDebut(e.target.value)} InputLabelProps={{ shrink: true }} />
          <TextField label="Date de fin" type="date" size="small" value={dateFin}
            onChange={(e) => setDateFin(e.target.value)} InputLabelProps={{ shrink: true }} />
          <Button variant="contained" onClick={charger} disabled={loading}>
            {loading ? <CircularProgress size={22} /> : 'Calculer'}
          </Button>
          <Box sx={{ flexGrow: 1 }} />
          <Tooltip title="Interroge Karlia et met à jour le miroir local des ventes">
            <span>
              <Button variant="outlined"
                startIcon={refreshing ? <CircularProgress size={18} /> : <RefreshIcon />}
                onClick={rafraichirKarlia} disabled={refreshing}>
                Rafraîchir le CA Karlia
              </Button>
            </span>
          </Tooltip>
        </Stack>
        {data?.karlia_last_refresh && (
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
            Dernier rafraîchissement Karlia : {new Date(data.karlia_last_refresh).toLocaleString('fr-FR')}
          </Typography>
        )}
        {refreshInfo && <Alert severity="success" sx={{ mt: 2 }}>{refreshInfo}</Alert>}
        {error && <Alert severity="error" sx={{ mt: 2 }}>{error}</Alert>}
      </Paper>

      {data && (
        <Paper sx={{ p: 2, mb: 3 }}>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Exercice</TableCell>
                  <TableCell>Période</TableCell>
                  <TableCell align="right">CA historique</TableCell>
                  <TableCell align="right">CA Karlia</TableCell>
                  <TableCell align="right">CA total</TableCell>
                  <TableCell align="right">Évolution N/N-1</TableCell>
                  <TableCell align="right">Factures</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {lignes.map((l, i) => {
                  const prev = lignes[i + 1];
                  const delta = prev && prev.ca_total ? ((l.ca_total - prev.ca_total) / prev.ca_total) * 100 : null;
                  const nbFact = (l.nb_factures_historique || 0) + (l.nb_factures_karlia || 0);
                  return (
                    <TableRow key={l.exercice} sx={i === 0 ? { '& td': { fontWeight: 600 } } : undefined}>
                      <TableCell>
                        {l.exercice}
                        {i === 0 && <Chip label="référence" size="small" color="primary" sx={{ ml: 1 }} />}
                      </TableCell>
                      <TableCell>{frDate(l.date_debut)} → {frDate(l.date_fin)}</TableCell>
                      <TableCell align="right">{eur(l.ca_historique)}</TableCell>
                      <TableCell align="right">{l.ca_karlia ? eur(l.ca_karlia) : '—'}</TableCell>
                      <TableCell align="right">{eur(l.ca_total)}</TableCell>
                      <TableCell align="right">
                        {delta === null ? '—' : (
                          <Typography component="span" variant="body2"
                            color={delta >= 0 ? 'success.main' : 'error.main'}>
                            {delta >= 0 ? '+' : ''}{delta.toFixed(1)} %
                          </Typography>
                        )}
                      </TableCell>
                      <TableCell align="right">{nbFact}</TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </TableContainer>
        </Paper>
      )}

      {data && lignes.length > 0 && (
        <Paper sx={{ p: 2 }}>
          <Typography variant="subtitle1" gutterBottom>CA total par exercice</Typography>
          <Divider sx={{ mb: 2 }} />
          <Stack spacing={1.5}>
            {lignes.map((l) => (
              <Box key={l.exercice}>
                <Stack direction="row" justifyContent="space-between">
                  <Typography variant="body2">{l.exercice}</Typography>
                  <Typography variant="body2">{eur(l.ca_total)}</Typography>
                </Stack>
                <Box sx={{ height: 14, bgcolor: 'action.hover', borderRadius: 1, overflow: 'hidden' }}>
                  <Box sx={{ height: '100%', width: `${Math.max(2, (l.ca_total / maxTotal) * 100)}%`, bgcolor: 'primary.main' }} />
                </Box>
              </Box>
            ))}
          </Stack>
        </Paper>
      )}
    </Box>
  );
}
