import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box, Grid, Card, CardContent, Typography, CircularProgress, Alert
} from '@mui/material';
import {
  Event as EventIcon, Schedule as ScheduleIcon, CheckCircle as DoneIcon
} from '@mui/icons-material';
import { format } from 'date-fns';
import { fr } from 'date-fns/locale';
import api from '../services/api';
import { useAuth } from '../context/AuthContext';

export default function DashboardFormateur() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [stats, setStats] = useState({ a_planifier: 0, planifiees: 0, realisees: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchStats = useCallback(async () => {
    if (!user?.formateur_id) {
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const res = await api.get(`/api/prestations/formateur/${user.formateur_id}`);
      setStats({
        a_planifier: res.data.a_planifier || 0,
        planifiees: res.data.planifiees || 0,
        realisees: res.data.realisees || 0,
      });
      setError(null);
    } catch (err) {
      console.error('Erreur chargement prestations:', err);
      setError('Erreur lors du chargement des prestations');
    } finally {
      setLoading(false);
    }
  }, [user?.formateur_id]);

  useEffect(() => {
    fetchStats();
  }, [fetchStats]);

  if ((user?.role === 'FORMATEUR' || user?.role === 'TECHNICIEN') && !user?.formateur_id) {
    return (
      <Box sx={{ p: 3 }}>
        <Alert severity="warning">
          Votre compte n'est pas associé à un profil formateur. Contactez un administrateur.
        </Alert>
      </Box>
    );
  }

  const tuiles = [
    {
      label: 'À planifier',
      count: stats.a_planifier,
      icon: <EventIcon sx={{ fontSize: 56 }} />,
      color: 'warning.main',
      target: '/mes-prestations?tab=a_planifier',
    },
    {
      label: 'Planifiées',
      count: stats.planifiees,
      icon: <ScheduleIcon sx={{ fontSize: 56 }} />,
      color: 'info.main',
      target: '/mes-prestations?tab=planifiee',
    },
    {
      label: 'Réalisées',
      count: stats.realisees,
      icon: <DoneIcon sx={{ fontSize: 56 }} />,
      color: 'success.main',
      target: '/mes-prestations?tab=realisee',
    },
  ];

  return (
    <Box sx={{ p: 3 }}>
      <Box sx={{ mb: 4 }}>
        <Typography variant="h4">Tableau de bord</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          {format(new Date(), "EEEE d MMMM yyyy", { locale: fr })}
        </Typography>
      </Box>

      {error && <Alert severity="error" sx={{ mb: 3 }} onClose={() => setError(null)}>{error}</Alert>}

      {loading ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
          <CircularProgress />
        </Box>
      ) : (
        <Grid container spacing={3}>
          {tuiles.map((t) => (
            <Grid item xs={12} sm={4} key={t.label}>
              <Card
                onClick={() => navigate(t.target)}
                sx={{
                  cursor: 'pointer',
                  transition: 'transform 0.15s ease, box-shadow 0.15s ease',
                  '&:hover': { transform: 'translateY(-2px)', boxShadow: 6 },
                }}
              >
                <CardContent sx={{ textAlign: 'center', py: 4 }}>
                  <Box sx={{ color: t.color, mb: 1 }}>{t.icon}</Box>
                  <Typography variant="h2" sx={{ color: t.color, fontWeight: 700, lineHeight: 1 }}>
                    {t.count}
                  </Typography>
                  <Typography variant="body1" color="text.secondary" sx={{ mt: 1.5 }}>
                    {t.label}
                  </Typography>
                </CardContent>
              </Card>
            </Grid>
          ))}
        </Grid>
      )}
    </Box>
  );
}
