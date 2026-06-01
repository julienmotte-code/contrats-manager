import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Box, Paper, Typography, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, Button, Chip, CircularProgress, Alert, Card, CardContent,
  Grid, Select, MenuItem, FormControl, IconButton, Tooltip, Divider, InputLabel,
  TextField
} from '@mui/material';
import {
  ArrowBack as ArrowBackIcon, Check as CheckIcon, Close as CloseIcon,
  Group as GroupIcon, Warning as WarningIcon, DoneAll as DoneAllIcon
} from '@mui/icons-material';
import { DatePicker } from '@mui/x-date-pickers/DatePicker';
import { TimePicker } from '@mui/x-date-pickers/TimePicker';
import { LocalizationProvider } from '@mui/x-date-pickers/LocalizationProvider';
import { AdapterDateFns } from '@mui/x-date-pickers/AdapterDateFns';
import { format, parseISO } from 'date-fns';
import { fr } from 'date-fns/locale';
import api from '../services/api';

// Valeur sentinelle pour "non affecté" dans le Select MUI : un MenuItem ne peut
// pas porter `value={null}` proprement (MUI traite null comme "rien de
// sélectionné" et affiche un blanc). On utilise la chaîne vide en interne et
// on convertit en null à l'envoi du payload.
const UNASSIGNED = '';

const formatMontant = (montant) => {
  if (montant === null || montant === undefined) return '-';
  return new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR' }).format(montant);
};

// Libellés courts des statuts de prestation. Utilisés dans le chip de la ligne
// + l'avertissement visuel quand la prestation est déjà planifiée/réalisée.
const STATUT_CHIP = {
  a_planifier: { label: 'À planifier', color: 'default' },
  planifiee:   { label: 'Planifiée',   color: 'warning' },
  realisee:    { label: 'Réalisée',    color: 'success' },
};

const formateurLabel = (f) => `${f.prenom || ''} ${f.nom || ''}`.trim() || `Formateur #${f.id}`;

// Parse une heure "HH:mm:ss" (stockage backend) en Date (sur une date pivot
// arbitraire) pour alimenter le TimePicker. Même pattern que MesPrestations.js.
const parseHeure = (h) => (h ? parseISO(`2000-01-01T${h}`) : null);

export default function AffectationFormateurs() {
  const { id } = useParams();
  const navigate = useNavigate();

  const [commande, setCommande] = useState(null);
  const [prestations, setPrestations] = useState([]);
  const [formateurs, setFormateurs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  // Erreurs de planification par prestation (étape 2 du Valider), affichées
  // sans annuler l'affectation déjà committée.
  const [planifErrors, setPlanifErrors] = useState([]);

  // Map prestation_id -> formateur_id (string, '' = non affecté), initialisée
  // depuis les prestations courantes. Une prestation absente du payload final
  // ne serait pas modifiée côté backend, mais on envoie l'état COMPLET de
  // l'écran pour qu'il reflète l'intention de l'utilisateur (et qu'une
  // désaffectation manuelle soit possible).
  const [routage, setRoutage] = useState({});

  // Map prestation_id -> { date, debut, fin, lieu } (planification optionnelle,
  // saisie inline). date/debut/fin = objets Date (pickers) ou null ; lieu = str.
  const [planification, setPlanification] = useState({});

  // Sélecteur global "Appliquer à tous" — indépendant de la map des prestations.
  const [globalFormateur, setGlobalFormateur] = useState(UNASSIGNED);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [cmdRes, prestRes, formRes] = await Promise.all([
        api.get(`/api/commandes/${id}`),
        api.get('/api/prestations', { params: { commande_id: id } }),
        api.get('/api/formateurs', { params: { actif_only: true } }),
      ]);
      setCommande(cmdRes.data);
      // Construire l'ensemble des ligne_id qui sont des intitulés Karlia
      // (section_karlia=1) ou explicitement routés 'intitule'. Ces lignes ne
      // représentent pas une vraie prestation et ne doivent jamais apparaître
      // sur l'écran d'affectation — même si une prestation parasite y est
      // encore rattachée (résidu d'un éclatement antérieur au garde-fou
      // de v3.3.x). Cas couverts : les commandes resyncées depuis l'arrivée
      // de section_karlia (toutes les 'nouvelle' et celles du groupe A de la
      // bascule du chantier intitulés). Les commandes historiques restées
      // au statut a_planifier/planifiee n'ont PAS section_karlia peuplé →
      // le filtre n'a aucun effet sur elles (cf. Phase B, nettoyage DB).
      const lignesIntituleIds = new Set(
        (cmdRes.data.lignes || [])
          .filter((l) => l.section_karlia === 1 || l.destination === 'intitule')
          .map((l) => l.id),
      );
      const allPrests = prestRes.data.prestations || [];
      const prests = allPrests.filter(
        (p) => !lignesIntituleIds.has(p.commande_ligne_id),
      );
      setPrestations(prests);
      setFormateurs(formRes.data.formateurs || []);
      // Init des maps depuis les prestations AFFICHÉES (intitulés exclus).
      const initRoutage = {};
      const initPlanif = {};
      for (const p of prests) {
        initRoutage[p.id] = p.formateur_id !== null && p.formateur_id !== undefined
          ? String(p.formateur_id)
          : UNASSIGNED;
        initPlanif[p.id] = {
          date: p.date_planifiee ? parseISO(p.date_planifiee) : null,
          debut: parseHeure(p.heure_debut),
          fin: parseHeure(p.heure_fin),
          lieu: p.lieu || '',
        };
      }
      setRoutage(initRoutage);
      setPlanification(initPlanif);
      setError(null);
    } catch (err) {
      setError("Erreur lors du chargement de l'affectation");
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  // Tri stable par id (ordre de création = ordre d'éclatement). Cohérent avec
  // RoutageCommande.js qui trie par `ordre` Karlia ; ici les prestations n'ont
  // pas de notion d'ordre Karlia (issues de l'éclatement d'une ligne), donc
  // l'id est l'ordre naturel.
  const prestationsTriees = useMemo(() => {
    return [...prestations].sort((a, b) => a.id - b.id);
  }, [prestations]);

  // Index id → formateur pour le récap (couleur, libellé).
  const formateursById = useMemo(() => {
    const map = {};
    for (const f of formateurs) map[String(f.id)] = f;
    return map;
  }, [formateurs]);

  // Récap : compte par formateur + non affectées.
  const recap = useMemo(() => {
    const counts = {};
    let nonAffectees = 0;
    for (const p of prestationsTriees) {
      const fid = routage[p.id];
      if (fid && fid !== UNASSIGNED) {
        counts[fid] = (counts[fid] || 0) + 1;
      } else {
        nonAffectees += 1;
      }
    }
    return { counts, nonAffectees };
  }, [routage, prestationsTriees]);

  const handleChangeFormateur = (prestationId, value) => {
    setRoutage((prev) => ({ ...prev, [prestationId]: value }));
  };

  const handleChangePlanif = (prestationId, field, value) => {
    setPlanification((prev) => ({
      ...prev,
      [prestationId]: { ...(prev[prestationId] || {}), [field]: value },
    }));
  };

  const handleApplyToAll = () => {
    // Copie le formateur global sur TOUTES les prestations affichées (y compris
    // celles déjà 'planifiee' — le backend ajoutera ces ids dans 'avertissements').
    const next = {};
    for (const p of prestationsTriees) {
      next[p.id] = globalFormateur;
    }
    setRoutage(next);
  };

  // Une planification (heure/lieu) sans date ne partira pas → signalée à l'UI.
  const planifIncomplete = (p) => {
    const pl = planification[p.id] || {};
    const aHeureOuLieu = !!pl.debut || !!pl.fin || !!(pl.lieu && pl.lieu.trim());
    return aHeureOuLieu && !pl.date;
  };

  const handleValider = async () => {
    if (!commande) return;
    setSubmitting(true);
    setError(null);
    setPlanifErrors([]);
    try {
      // ── Étape 1 : affectation des formateurs (payload inchangé) ──────────
      const affectations = prestationsTriees.map((p) => ({
        prestation_id: p.id,
        formateur_id: routage[p.id] && routage[p.id] !== UNASSIGNED
          ? Number(routage[p.id])
          : null,
      }));
      const res = await api.post(
        `/api/commandes/${id}/affecter-formateurs`,
        { affectations },
      );
      const avert = res.data?.avertissements || [];

      // ── Étape 2 : planification — UNIQUEMENT les prestations avec une date.
      // Heure début/fin/lieu envoyés seulement s'ils sont remplis. Les erreurs
      // sont collectées par prestation, sans annuler l'affectation committée.
      const erreurs = [];
      for (const p of prestationsTriees) {
        const pl = planification[p.id] || {};
        if (!pl.date) continue; // pas de date → on n'appelle PAS /planifier
        const payload = { date_planifiee: format(pl.date, 'yyyy-MM-dd') };
        if (pl.debut) payload.heure_debut = format(pl.debut, 'HH:mm:ss');
        if (pl.fin) payload.heure_fin = format(pl.fin, 'HH:mm:ss');
        if (pl.lieu && pl.lieu.trim()) payload.lieu = pl.lieu.trim();
        try {
          await api.post(`/api/prestations/${p.id}/planifier`, payload);
        } catch (e) {
          erreurs.push({
            id: p.id,
            designation: p.designation || `Prestation #${p.id}`,
            detail: e.response?.data?.detail || 'Erreur de planification',
          });
        }
      }

      // ── Étape 3 : succès total → redirection ; sinon → on reste + Alert.
      if (erreurs.length === 0) {
        let successMessage = `Affectation enregistrée pour ${commande.reference_devis || `commande ${id}`}`;
        if (avert.length > 0) {
          successMessage += ` — attention : ${avert.length} prestation(s) déjà planifiée(s) ont été réaffectée(s) (id ${avert.join(', ')}). Vérifiez l'agenda associé.`;
        }
        navigate('/commandes/a-planifier', { state: { successMessage } });
      } else {
        setPlanifErrors(erreurs);
        // Recharge l'état réel (affectation + planifications réussies).
        await fetchAll();
      }
    } catch (err) {
      const detail = err.response?.data?.detail;
      setError(detail ? `Erreur d'affectation : ${detail}` : "Erreur lors de l'affectation");
      console.error(err);
    } finally {
      setSubmitting(false);
    }
  };

  const handleAnnuler = () => navigate('/commandes/a-planifier');

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
          Retour aux commandes à planifier
        </Button>
      </Box>
    );
  }

  return (
    <LocalizationProvider dateAdapter={AdapterDateFns} adapterLocale={fr}>
    <Box sx={{ p: 3 }}>
      {/* En-tête */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
        <Tooltip title="Retour">
          <IconButton onClick={handleAnnuler}><ArrowBackIcon /></IconButton>
        </Tooltip>
        <Typography variant="h4" sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <GroupIcon color="primary" /> Affecter et planifier
        </Typography>
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

      {planifErrors.length > 0 && (
        <Alert severity="warning" sx={{ mb: 2 }} onClose={() => setPlanifErrors([])}>
          L'affectation a été enregistrée, mais la planification a échoué pour&nbsp;:
          <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
            {planifErrors.map((e) => (
              <li key={e.id}>{e.designation} — {e.detail}</li>
            ))}
          </ul>
        </Alert>
      )}

      {prestationsTriees.length === 0 ? (
        <Alert severity="info">
          Aucune prestation à affecter pour cette commande. Si la commande a été
          validée avec uniquement des lignes contrat ou facturation directe,
          c'est normal — il n'y a pas d'intervention SGI à attribuer.
        </Alert>
      ) : (
        <>
          {/* Raccourci "Appliquer à tous" */}
          <Paper variant="outlined" sx={{ p: 2, mb: 2, bgcolor: 'grey.50' }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
              <Typography variant="subtitle2" sx={{ minWidth: 130 }}>
                Appliquer à tous :
              </Typography>
              <FormControl size="small" sx={{ minWidth: 240 }}>
                <InputLabel id="global-formateur-label">Formateur</InputLabel>
                <Select
                  labelId="global-formateur-label"
                  label="Formateur"
                  value={globalFormateur}
                  onChange={(e) => setGlobalFormateur(e.target.value)}
                >
                  <MenuItem value={UNASSIGNED}><em>— non affecté —</em></MenuItem>
                  {formateurs.map((f) => (
                    <MenuItem key={f.id} value={String(f.id)}>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        <Box sx={{
                          width: 12, height: 12, borderRadius: '50%',
                          backgroundColor: f.couleur || '#999',
                        }} />
                        <span>{formateurLabel(f)}</span>
                      </Box>
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              <Button
                variant="outlined"
                size="small"
                startIcon={<DoneAllIcon />}
                onClick={handleApplyToAll}
                disabled={submitting}
              >
                Appliquer aux {prestationsTriees.length} prestation(s)
              </Button>
            </Box>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
              Date, heures et lieu sont optionnels et se saisissent par prestation.
              La planification n'est enregistrée que si une date est renseignée.
            </Typography>
          </Paper>

          {/* Tableau prestations */}
          <TableContainer component={Paper}>
            <Table size="small">
              <TableHead>
                <TableRow sx={{ backgroundColor: 'grey.100' }}>
                  <TableCell sx={{ width: 50 }} align="center">#</TableCell>
                  <TableCell>Désignation</TableCell>
                  <TableCell sx={{ width: 130 }} align="center">Statut</TableCell>
                  <TableCell sx={{ width: 70 }} align="center">Durée (j)</TableCell>
                  <TableCell sx={{ width: 220 }}>Formateur</TableCell>
                  <TableCell sx={{ width: 150 }}>Date</TableCell>
                  <TableCell sx={{ width: 105 }} align="center">Début</TableCell>
                  <TableCell sx={{ width: 105 }} align="center">Fin</TableCell>
                  <TableCell sx={{ width: 240 }}>Lieu</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {prestationsTriees.map((p, idx) => {
                  const dejaPlanifiee = p.statut === 'planifiee' || p.date_planifiee;
                  const statutConf = STATUT_CHIP[p.statut] || { label: p.statut, color: 'default' };
                  const pl = planification[p.id] || {};
                  const dateManquante = planifIncomplete(p);
                  return (
                    <TableRow key={p.id} hover>
                      <TableCell align="center">
                        <Typography variant="caption" color="text.secondary">
                          #{idx + 1}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        {/* description NON affichée : c'est du HTML Karlia brut
                            (balises échappées + <p> vides) qui polluait l'écran.
                            designation suffit à identifier la prestation. */}
                        <Typography variant="body2">
                          {p.designation || `Prestation #${p.id}`}
                        </Typography>
                      </TableCell>
                      <TableCell align="center">
                        <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 0.5 }}>
                          <Chip size="small" label={statutConf.label} color={statutConf.color} />
                          {dejaPlanifiee && (
                            <Tooltip title="Réaffectation possible, mais cette prestation est déjà engagée — pensez à recaler l'agenda associé.">
                              <Chip
                                size="small"
                                icon={<WarningIcon sx={{ fontSize: 14 }} />}
                                label="déjà planifiée"
                                color="warning"
                                variant="outlined"
                              />
                            </Tooltip>
                          )}
                        </Box>
                      </TableCell>
                      <TableCell align="center">
                        {p.duree_jours ?? '-'}
                      </TableCell>
                      <TableCell>
                        <FormControl size="small" sx={{ minWidth: 220 }}>
                          <Select
                            value={routage[p.id] ?? UNASSIGNED}
                            onChange={(e) => handleChangeFormateur(p.id, e.target.value)}
                          >
                            <MenuItem value={UNASSIGNED}><em>— non affecté —</em></MenuItem>
                            {formateurs.map((f) => (
                              <MenuItem key={f.id} value={String(f.id)}>
                                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                  <Box sx={{
                                    width: 12, height: 12, borderRadius: '50%',
                                    backgroundColor: f.couleur || '#999',
                                  }} />
                                  <span>{formateurLabel(f)}</span>
                                </Box>
                              </MenuItem>
                            ))}
                          </Select>
                        </FormControl>
                      </TableCell>
                      <TableCell>
                        <DatePicker
                          value={pl.date ?? null}
                          onChange={(v) => handleChangePlanif(p.id, 'date', v)}
                          format="dd/MM/yyyy"
                          slotProps={{
                            textField: {
                              size: 'small',
                              fullWidth: true,
                              error: dateManquante,
                              helperText: dateManquante
                                ? 'Renseignez une date pour enregistrer ces informations'
                                : undefined,
                            },
                            field: { clearable: true },
                          }}
                        />
                      </TableCell>
                      <TableCell align="center">
                        <TimePicker
                          value={pl.debut ?? null}
                          onChange={(v) => handleChangePlanif(p.id, 'debut', v)}
                          ampm={false}
                          slotProps={{ textField: { size: 'small', sx: { width: 95 } }, field: { clearable: true } }}
                        />
                      </TableCell>
                      <TableCell align="center">
                        <TimePicker
                          value={pl.fin ?? null}
                          onChange={(v) => handleChangePlanif(p.id, 'fin', v)}
                          ampm={false}
                          slotProps={{ textField: { size: 'small', sx: { width: 95 } }, field: { clearable: true } }}
                        />
                      </TableCell>
                      <TableCell>
                        <TextField
                          size="small"
                          fullWidth
                          placeholder="Lieu"
                          value={pl.lieu ?? ''}
                          onChange={(e) => handleChangePlanif(p.id, 'lieu', e.target.value)}
                        />
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </TableContainer>

          {/* Récap */}
          <Paper sx={{ mt: 2, p: 2 }}>
            <Typography variant="subtitle1" gutterBottom>Récapitulatif</Typography>
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, alignItems: 'center' }}>
              {Object.keys(recap.counts).length === 0 && recap.nonAffectees === prestationsTriees.length && (
                <Typography variant="body2" color="text.secondary">
                  Aucune prestation affectée pour l'instant.
                </Typography>
              )}
              {Object.entries(recap.counts).map(([fid, n]) => {
                const f = formateursById[fid];
                const label = f ? formateurLabel(f) : `Formateur #${fid}`;
                return (
                  <Chip
                    key={fid}
                    label={`${label} : ${n} prestation(s)`}
                    sx={{
                      bgcolor: f?.couleur || undefined,
                      color: f?.couleur ? '#fff' : undefined,
                    }}
                  />
                );
              })}
              {recap.nonAffectees > 0 && (
                <Chip
                  variant="outlined"
                  label={`${recap.nonAffectees} non affectée(s)`}
                  color="default"
                />
              )}
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
              disabled={submitting}
            >
              Valider l'affectation
            </Button>
          </Box>
        </>
      )}
    </Box>
    </LocalizationProvider>
  );
}
