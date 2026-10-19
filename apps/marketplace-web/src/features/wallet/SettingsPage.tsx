import {
  LOCALNET_GENESIS,
  MINT,
  PROGRAM_ID,
  RPC,
  time,
} from '../../app/config';
import {
  SETTLEMENT_SYMBOL,
  snapshotLocked,
  useSnapshot,
} from '../../app/atlas';
import { LanguageSelect, useCopy, useI18n } from '../../app/i18n';
import { useNetwork } from '../../app/NetworkProvider';
import {
  CopyAddress,
  DataGrid,
  Icon,
  PageHeader,
  ResourceState,
} from '../../components/ui';
import { Pulse } from '../../components/ui/viz';
import '../../styles/treasury.css';

export default function SettingsPage() {
  const { t, locale } = useI18n();
  const c = useCopy();
  const network = useNetwork();
  const [snapshot, setSnapshot] = useSnapshot();

  const reducedMotion =
    typeof window !== 'undefined' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  return (
    <>
      <PageHeader
        eyebrow={c('OPERATE / SETTINGS', 'OPERAR / CONFIGURACIÓN')}
        title={c('Settings & network', 'Configuración y red')}
        description={c(
          'Manage data display preferences, interface language, and Solana protocol service endpoints.',
          'Administra las preferencias de visualización de datos, el idioma de la interfaz y los endpoints de servicios del protocolo Solana.'
        )}
        action={
          <button
            type="button"
            className="button primary"
            disabled={network.loading}
            onClick={network.reload}
          >
            <Icon name="activity" />
            {network.loading
              ? c('Verifying…', 'Verificando…')
              : t('Verificar red')}
          </button>
        }
      />

      {!snapshot && <ResourceState {...network} />}

      <div className="settings-stack">
        {/* Data & display section */}
        <section className="panel">
          <div className="panel-title">
            <div>
              <h2>{c('Data & display', 'Datos y visualización')}</h2>
              <p>
                {c(
                  'Configure how network records, language, and interface motion are rendered across your workspace.',
                  'Configura cómo se presentan los registros de red, el idioma y las animaciones en tu espacio de trabajo.'
                )}
              </p>
            </div>
          </div>

          <div className="settings-controls-grid">
            {/* Network snapshot switch */}
            <div className="switch-row">
              <div className="switch-row-copy">
                <strong>
                  <Icon name="globe" />
                  {c('Network snapshot', 'Instantánea de red')}
                </strong>
                <p>
                  {c(
                    'Include the curated network snapshot alongside live on-chain records in analytics, marketplace and fleet views.',
                    'Incluye la instantánea curada de la red junto con los registros on-chain en vivo en las vistas de analítica, mercado y flota.'
                  )}
                </p>
                {snapshotLocked && (
                  <p className="micro" style={{ marginTop: 6 }}>
                    {c(
                      'Locked by environment configuration (VITE_CONATUS_SNAPSHOT=off).',
                      'Bloqueado por configuración de entorno (VITE_CONATUS_SNAPSHOT=off).'
                    )}
                  </p>
                )}
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={snapshot}
                aria-label={c('Network snapshot', 'Instantánea de red')}
                disabled={snapshotLocked}
                className="toggle-switch"
                onClick={() => setSnapshot(!snapshot)}
              >
                <span className="toggle-switch-thumb" />
              </button>
            </div>

            {/* Language preference */}
            <div className="switch-row">
              <div className="switch-row-copy">
                <strong>
                  <Icon name="spark" />
                  {c('Interface language', 'Idioma de la interfaz')}
                </strong>
                <p>
                  {c(
                    'Switch between English and Spanish for navigation, financial formatting, and protocol labels.',
                    'Alterna entre inglés y español para la navegación, el formato financiero y las etiquetas del protocolo.'
                  )}
                </p>
              </div>
              <LanguageSelect />
            </div>

            {/* Motion preference note */}
            <div className="switch-row">
              <div className="switch-row-copy">
                <strong>
                  <Icon name="eye" />
                  {c('Motion & transitions', 'Movimiento y transiciones')}
                </strong>
                <p>
                  {c(
                    'Animated counters, chart drawing, and live pulse indicators automatically follow your system prefers-reduced-motion preference.',
                    'Los contadores animados, el trazado de gráficos y los indicadores de pulso siguen automáticamente la preferencia prefers-reduced-motion de tu sistema.'
                  )}
                </p>
              </div>
              <span className="badge status-confirmed">
                {reducedMotion
                  ? c('Reduced motion active', 'Movimiento reducido activo')
                  : c('Standard motion', 'Movimiento estándar')}
              </span>
            </div>
          </div>
        </section>

        {/* Network & services section */}
        <section className="panel">
          <div className="panel-title">
            <div>
              <h2>{c('Network & services', 'Red y servicios')}</h2>
              <p>
                {c(
                  'Active Solana cluster parameters, settlement smart contract addresses, and protocol gateway services.',
                  'Parámetros activos del clúster de Solana, direcciones del contrato inteligente de liquidación y servicios de pasarela del protocolo.'
                )}
              </p>
            </div>
            <span className="fleet-state-pill">
              <Pulse
                tone={
                  network.data
                    ? 'success'
                    : network.loading
                      ? 'warning'
                      : 'accent'
                }
              />
              {network.data
                ? c('Cluster verified', 'Clúster verificado')
                : network.loading
                  ? c('Verifying cluster…', 'Verificando clúster…')
                  : c('Snapshot active', 'Instantánea activa')}
            </span>
          </div>

          <DataGrid
            items={[
              [c('Configured RPC endpoint', 'Endpoint RPC configurado'), RPC],
              [
                t('Genesis esperado'),
                <CopyAddress
                  value={LOCALNET_GENESIS}
                  label={t('genesis esperado')}
                />,
              ],
              [
                t('Genesis verificado'),
                network.data ? (
                  <CopyAddress
                    value={network.data.genesis}
                    label={t('genesis verificado')}
                  />
                ) : (
                  c('Awaiting live RPC handshake', 'En espera de conexión RPC en vivo')
                ),
              ],
              [
                c('Conatus settlement program', 'Programa de liquidación Conatus'),
                <CopyAddress value={PROGRAM_ID.toBase58()} />,
              ],
              [
                c(
                  `Settlement asset mint (${SETTLEMENT_SYMBOL})`,
                  `Mint del activo de liquidación (${SETTLEMENT_SYMBOL})`
                ),
                <CopyAddress value={MINT.toBase58()} />,
              ],
              [
                t('Verificación de conectividad'),
                network.data
                  ? t('Program and API verified · {time}', {
                      time: time(network.data.observedAt, locale),
                    })
                  : c(
                      'Operating with verified network snapshot',
                      'Operando con instantánea de red verificada'
                    ),
              ],
            ]}
          />

          <h3 style={{ marginTop: 24, marginBottom: 8 }}>
            {c('Protocol gateway services', 'Servicios de pasarela del protocolo')}
          </h3>
          <div className="service-cards-grid">
            <div className="service-card">
              <div className="service-card-top">
                <strong>{c('Marketplace API', 'API del Marketplace')}</strong>
                <span className="badge status-active">REST / v1</span>
              </div>
              <code>/v1, /health → 127.0.0.1:8787</code>
            </div>

            <div className="service-card">
              <div className="service-card-top">
                <strong>{c('Solana RPC gateway', 'Pasarela RPC de Solana')}</strong>
                <span className="badge status-active">JSON-RPC</span>
              </div>
              <code>/solana-rpc → 127.0.0.1:8899</code>
            </div>

            <div className="service-card">
              <div className="service-card-top">
                <strong>
                  {c('Escrow funding gateway', 'Pasarela de financiamiento en escrow')}
                </strong>
                <span className="badge status-active">Preflight</span>
              </div>
              <code>/funding-api → 127.0.0.1:8788</code>
            </div>

            <div className="service-card">
              <div className="service-card-top">
                <strong>
                  {c('Device signer service', 'Servicio firmante de dispositivo')}
                </strong>
                <span className="badge status-active">Ed25519</span>
              </div>
              <code>/dev-signer → 127.0.0.1:8799</code>
            </div>
          </div>

          <p className="hint" style={{ marginBottom: 0 }}>
            {c(
              'Connection verification checks the RPC cluster, settlement program, and Marketplace API; the escrow funding gateway and device signer service are verified on demand when signing transactions.',
              'La verificación de conexión comprueba el clúster RPC, el programa de liquidación y la API del Marketplace; la pasarela de escrow y el servicio firmante de dispositivo se comprueban al firmar transacciones.'
            )}
          </p>

          {network.error && snapshot && (
            <details className="diagnostics">
              <summary>
                {c('RPC connection diagnostics', 'Diagnóstico de conexión RPC')}
              </summary>
              <pre>{network.error}</pre>
            </details>
          )}
        </section>
      </div>
    </>
  );
}
