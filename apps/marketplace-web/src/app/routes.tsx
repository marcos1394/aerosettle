import { useI18n } from './i18n';
import { Component, lazy, Suspense, type ReactNode } from 'react';
import { BrowserRouter, Link, Route, Routes, useLocation } from 'react-router';
import AppShell from '../components/layout/AppShell';
const Journal = lazy(() => import('../features/discover/Journal'));
const Article = lazy(() =>
  import('../features/discover/Journal').then((m) => ({ default: m.Article }))
);
const Ecosystem = lazy(() => import('../features/discover/Ecosystem'));
const Roadmap = lazy(() => import('../features/discover/Roadmap'));
const Planner = lazy(() => import('../features/planner/MissionPlanner'));
const Landing = lazy(() => import('./Landing'));
const Overview = lazy(() => import('./Overview'));
const Agents = lazy(() => import('../features/agents/AgentsPage'));
const AgentDetail = lazy(() => import('../features/agents/AgentDetail'));
const Missions = lazy(() => import('../features/missions/MissionsPage'));
const MissionDetail = lazy(() => import('../features/missions/MissionDetail'));
const CreateMission = lazy(() => import('../features/missions/CreateMission'));
const Wallet = lazy(() => import('../features/wallet/WalletPage'));
const Settings = lazy(() => import('../features/wallet/SettingsPage'));
const Activity = lazy(() => import('../features/activity/ActivityPage'));
const Economy = lazy(() => import('../features/economy/EconomyPage'));
const Fleet = lazy(() => import('../features/fleet/FleetPage'));
const RegisterAgent = lazy(() => import('../features/agents/RegisterAgent'));
const Organizations = lazy(() => import('../features/organizations/OrganizationsPage'));
class Boundary extends Component<
  { children: ReactNode; path: string },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidUpdate(previous: { path: string }) {
    if (previous.path !== this.props.path && this.state.failed)
      this.setState({ failed: false });
  }
  render() {
    return this.state.failed ? <RouteError /> : this.props.children;
  }
}
function RouteError() {
  const { t } = useI18n();
  return (
    <div className="error-state" role="alert">
      <h1>{t('No se pudo cargar esta vista')}</h1>
      <p>
        {t(
          'Recarga para volver a intentarlo. No se enviará ninguna transacción.'
        )}
      </p>
      <button onClick={() => window.location.reload()}>
        {t('Recargar aplicación')}
      </button>
      <Link to="/app">{t('Mission Control')}</Link>
    </div>
  );
}
function NotFound() {
  const { t, locale } = useI18n();

  return (
    <div className="empty-state">
      <h1>{t('Página no encontrada')}</h1>
      <Link className="button primary" to="/app">
        {t('Abrir Mission Control')}
      </Link>
    </div>
  );
}
function RouteTree() {
  const { t, locale } = useI18n();

  const location = useLocation();
  return (
    <Boundary path={location.pathname}>
      <Suspense
        fallback={
          <div className="loading-state" role="status">
            {locale === 'es' ? 'Cargando Conatus…' : 'Loading Conatus…'}
          </div>
        }
      >
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/journal" element={<Journal />} />
          <Route path="/journal/:slug" element={<Article />} />
          <Route path="/ecosystem" element={<Ecosystem />} />
          <Route path="/roadmap" element={<Roadmap />} />
          <Route path="/app" element={<AppShell />}>
            <Route path="planner" element={<Planner />} />
            <Route index element={<Overview />} />
            <Route path="economy" element={<Economy />} />
            <Route path="agents" element={<Agents />} />
            <Route path="agents/register" element={<RegisterAgent />} />
            <Route path="agents/:agentId" element={<AgentDetail />} />
            <Route path="organizations" element={<Organizations />} />
            <Route path="missions" element={<Missions />} />
            <Route path="missions/new" element={<CreateMission />} />
            <Route path="missions/:workOrderPda" element={<MissionDetail />} />
            <Route path="fleet" element={<Fleet />} />
            <Route path="wallet" element={<Wallet />} />
            <Route path="activity" element={<Activity />} />
            <Route path="settings" element={<Settings />} />
            <Route path="*" element={<NotFound />} />
          </Route>
          <Route path="*" element={<NotFound />} />
        </Routes>
      </Suspense>
    </Boundary>
  );
}
export function AppRoutes() {
  const { t, locale } = useI18n();

  return (
    <BrowserRouter>
      <RouteTree />
    </BrowserRouter>
  );
}
