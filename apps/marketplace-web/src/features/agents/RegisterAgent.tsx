import { useMemo, useState } from 'react';
import { Link } from 'react-router';
import { useWallet } from '@solana/wallet-adapter-react';
import {
  MISSIONS,
  SETTLEMENT_SYMBOL,
  num,
  pct,
  usd,
  type Embodiment,
  type Sustainability,
} from '../../app/atlas';
import { CAPABILITIES, PROGRAM_ID, short } from '../../app/config';
import { useCopy, useI18n } from '../../app/i18n';
import { CopyAddress, DataGrid, Icon, PageHeader } from '../../components/ui';
import { WalletControl } from '../../components/ui/WalletControl';
import {
  EarlyAccess,
  EmbodimentGlyph,
  Meter,
  Pulse,
  Ring,
  SustainabilityBadge,
  sustainabilityTone,
} from '../../components/ui/viz';
import {
  EMBODIMENTS,
  EMBODIMENT_PRESETS,
  embodimentLabel,
  embodimentShortLabel,
} from './data';
import '../../styles/agents.css';

const BASE58_RE = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;
const SAMPLE_PUBKEYS: Record<Embodiment, string> = {
  Drone: '7xKestrelEnclave9QmVp3wR8sTu4yHj2nLz6cBf1dGe',
  Ugv: '9bBorealRoverKey4VnXp7wQ2sTu8yHj5nLz3cBf6dGe',
  Amr: '4mAtlasCourierKey8QpVr2wS6tYu3hJk9nLz5cBf7dG',
  RobotArm: '6rMantisArmSign3WnXp9wQ4sTu7yHj2nLz8cBf5dGe1',
  Camera: '3vVigilSentryKey7QmVp5wR9sTu2yHj8nLz4cBf6dGe',
  IotSensor: '8sSentinelMeshKey2QmVp6wR4sTu9yHj3nLz7cBf5dG',
  Vehicle: '5pPolarCargoKey9QmVp4wR7sTu3yHj6nLz2cBf8dGe1',
  IndustrialMachine: '2fFerroSpindleKey6QmVp8wR3sTu5yHj9nLz4cBf7dG',
  EdgeCompute: '4cOrbisClusterKey8QmVp3wR6sTu9yHj2nLz5cBf7dG',
  EnergyAsset: '9gLumenGridSigner5QmVp7wR2sTu8yHj4nLz6cBf3dG',
};

export default function RegisterAgent() {
  const { t, locale } = useI18n();
  const c = useCopy();
  const { connected, publicKey } = useWallet();

  const [step, setStep] = useState<number>(0);
  const [error, setError] = useState<string>('');
  const [sdkModalOpen, setSdkModalOpen] = useState<boolean>(false);
  const [manifestDownloaded, setManifestDownloaded] = useState<boolean>(false);

  // Step 1: Hardware
  const [embodiment, setEmbodiment] = useState<Embodiment>('Drone');
  const [name, setName] = useState<string>('Kestrel-14');
  const [model, setModel] = useState<string>(
    EMBODIMENT_PRESETS.Drone.defaultModel
  );
  const [city, setCity] = useState<string>('Monterrey');
  const [country, setCountry] = useState<string>('MX');
  const [autonomy, setAutonomy] = useState<'Autonomous' | 'Supervised'>(
    'Autonomous'
  );

  // Step 2: Capabilities
  const [capabilities, setCapabilities] = useState<number[]>(
    EMBODIMENT_PRESETS.Drone.defaultCapabilities
  );

  // Step 3: Identity & keys
  const [deviceAuthority, setDeviceAuthority] = useState<string>(
    SAMPLE_PUBKEYS.Drone
  );
  const [keyMode, setKeyMode] = useState<'paste' | 'device'>('paste');

  // Step 4: Economics
  const [rate, setRate] = useState<number>(EMBODIMENT_PRESETS.Drone.defaultRate);
  const [targetJobs, setTargetJobs] = useState<number>(22);
  const [energyCost, setEnergyCost] = useState<number>(
    EMBODIMENT_PRESETS.Drone.defaultCosts.energy
  );
  const [maintenanceCost, setMaintenanceCost] = useState<number>(
    EMBODIMENT_PRESETS.Drone.defaultCosts.maintenance
  );
  const [insuranceCost, setInsuranceCost] = useState<number>(
    EMBODIMENT_PRESETS.Drone.defaultCosts.insurance
  );
  const [connectivityCost, setConnectivityCost] = useState<number>(
    EMBODIMENT_PRESETS.Drone.defaultCosts.connectivity
  );
  const [bond, setBond] = useState<number>(EMBODIMENT_PRESETS.Drone.defaultBond);
  const [initialTreasury, setInitialTreasury] = useState<number>(3600);

  function selectEmbodiment(next: Embodiment) {
    const prevPreset = EMBODIMENT_PRESETS[embodiment];
    const nextPreset = EMBODIMENT_PRESETS[next];
    setEmbodiment(next);
    if (model === prevPreset.defaultModel || !model.trim()) {
      setModel(nextPreset.defaultModel);
    }
    setCapabilities(nextPreset.defaultCapabilities);
    setRate(nextPreset.defaultRate);
    setEnergyCost(nextPreset.defaultCosts.energy);
    setMaintenanceCost(nextPreset.defaultCosts.maintenance);
    setInsuranceCost(nextPreset.defaultCosts.insurance);
    setConnectivityCost(nextPreset.defaultCosts.connectivity);
    setBond(nextPreset.defaultBond);
    if (deviceAuthority === SAMPLE_PUBKEYS[embodiment]) {
      setDeviceAuthority(SAMPLE_PUBKEYS[next]);
    }
    setError('');
  }

  function toggleCapability(index: number) {
    setCapabilities((prev) =>
      prev.includes(index)
        ? prev.filter((x) => x !== index)
        : [...prev, index].sort((a, b) => a - b)
    );
    setError('');
  }

  // Economic calculations
  const economics = useMemo(() => {
    const safeRate = Math.max(1, Number(rate) || 0);
    const safeJobs = Math.max(1, Number(targetJobs) || 0);
    const projectedRevenue = safeRate * safeJobs;
    const protocolFee = Math.round(projectedRevenue * 0.04);
    const fixedMonthly =
      Math.max(0, Number(energyCost) || 0) +
      Math.max(0, Number(maintenanceCost) || 0) +
      Math.max(0, Number(insuranceCost) || 0) +
      Math.max(0, Number(connectivityCost) || 0);
    const totalMonthlyCost = Math.max(1, fixedMonthly + protocolFee);
    const netPerJob = Math.max(1, safeRate * 0.96);
    const breakEvenJobs = Math.ceil(fixedMonthly / netPerJob);
    const conatus = projectedRevenue / totalMonthlyCost;
    const sustainability: Sustainability =
      conatus >= 1.6 ? 'thriving' : conatus >= 1 ? 'stable' : 'at-risk';
    const monthlyNet = projectedRevenue - totalMonthlyCost;
    const dailyBurn = totalMonthlyCost / 30;
    const runwayDays = Math.max(
      1,
      Math.round(Math.max(0, Number(initialTreasury) || 0) / dailyBurn)
    );
    return {
      projectedRevenue,
      protocolFee,
      fixedMonthly,
      totalMonthlyCost,
      breakEvenJobs,
      conatus,
      sustainability,
      monthlyNet,
      dailyBurn,
      runwayDays,
    };
  }, [
    rate,
    targetJobs,
    energyCost,
    maintenanceCost,
    insuranceCost,
    connectivityCost,
    initialTreasury,
  ]);

  const capabilityMask = useMemo(() => {
    let bits = 0n;
    for (const idx of capabilities) {
      bits |= 1n << BigInt(idx);
    }
    return {
      decimal: bits.toString(),
      hex: `0x${bits.toString(16).toUpperCase().padStart(4, '0')}`,
    };
  }, [capabilities]);

  const matchingOpenMissions = useMemo(() => {
    return MISSIONS.filter(
      (m) =>
        m.status === 'Open' &&
        m.capabilities.every((req) => capabilities.includes(req))
    ).length;
  }, [capabilities]);

  const slug = useMemo(
    () =>
      (name.trim() || 'conatus-agent')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/(^-|-$)/g, ''),
    [name]
  );

  const manifestObject = useMemo(
    () => ({
      schema: 'https://conatus.network/schemas/agent-manifest-v1.json',
      network: 'solana',
      programId: PROGRAM_ID.toBase58(),
      settlementAsset: SETTLEMENT_SYMBOL,
      agent: {
        id: slug,
        name: name.trim(),
        embodiment,
        model: model.trim(),
        autonomy,
        location: {
          city: city.trim(),
          country: country.trim().toUpperCase(),
        },
      },
      capabilities: {
        indices: capabilities,
        labels: capabilities.map((i) => CAPABILITIES[i]),
        bitmaskDecimal: capabilityMask.decimal,
        bitmaskHex: capabilityMask.hex,
      },
      identity: {
        deviceSigningAuthority: deviceAuthority.trim(),
        economicOwner: publicKey?.toBase58() ?? 'UNCONNECTED_WALLET',
      },
      survivalEconomics: {
        standardRateUsdc: Number(rate),
        targetJobsPerMonth: Number(targetJobs),
        monthlyOperatingCostsUsdc: {
          energy: Number(energyCost),
          maintenance: Number(maintenanceCost),
          insurance: Number(insuranceCost),
          connectivity: Number(connectivityCost),
          estimatedProtocolFee: economics.protocolFee,
          totalMonthlyCost: economics.totalMonthlyCost,
        },
        breakEvenJobsPerMonth: economics.breakEvenJobs,
        projectedConatusRatio: Number(economics.conatus.toFixed(2)),
        slashableBondUsdc: Number(bond),
        initialTreasuryUsdc: Number(initialTreasury),
        projectedRunwayDays: economics.runwayDays,
      },
      generatedAt: new Date().toISOString(),
    }),
    [
      slug,
      name,
      embodiment,
      model,
      autonomy,
      city,
      country,
      capabilities,
      capabilityMask,
      deviceAuthority,
      publicKey,
      rate,
      targetJobs,
      energyCost,
      maintenanceCost,
      insuranceCost,
      connectivityCost,
      economics,
      bond,
      initialTreasury,
    ]
  );

  const steps = [
    {
      title: c('1. Hardware', '1. Hardware'),
      subtitle: c('Embodiment & location', 'Chasis y ubicación'),
    },
    {
      title: c('2. Capabilities', '2. Capacidades'),
      subtitle: c('Physical sensors & skills', 'Sensores y habilidades'),
    },
    {
      title: c('3. Identity & Keys', '3. Identidad y llaves'),
      subtitle: c('Enclave & owner wallet', 'Enclave y propietario'),
    },
    {
      title: c('4. Economics', '4. Economía'),
      subtitle: c('Costs & Conatus ratio', 'Costos y ratio Conatus'),
    },
    {
      title: c('5. Review', '5. Revisión'),
      subtitle: c('Manifest & registration', 'Manifiesto y registro'),
    },
  ];

  function validateStep(targetStep: number): string {
    if (targetStep === 0) {
      if (!name.trim())
        return c(
          'Enter a callsign or name for your machine.',
          'Ingresa un nombre o indicativo para tu máquina.'
        );
      if (!model.trim())
        return c(
          'Specify the hardware model or chassis configuration.',
          'Especifica el modelo de hardware o configuración del chasis.'
        );
      if (!city.trim() || !country.trim())
        return c(
          'Enter both operating city and country code.',
          'Ingresa tanto la ciudad de operación como el país.'
        );
    }
    if (targetStep === 1) {
      if (capabilities.length === 0)
        return c(
          'Select at least one physical capability so missions can match your machine.',
          'Selecciona al menos una capacidad física para que el motor pueda asignarle misiones.'
        );
    }
    if (targetStep === 2) {
      if (!BASE58_RE.test(deviceAuthority.trim()))
        return c(
          'Enter a valid base58 Ed25519 public key (32–44 characters) for the device signing authority.',
          'Ingresa una clave pública Ed25519 base58 válida (32–44 caracteres) para la autoridad del dispositivo.'
        );
    }
    if (targetStep === 3) {
      if (!Number.isFinite(Number(rate)) || Number(rate) <= 0)
        return c(
          'Standard mission rate must be greater than 0 USDC.',
          'La tarifa estándar por misión debe ser mayor a 0 USDC.'
        );
      if (!Number.isFinite(Number(bond)) || Number(bond) < 50)
        return c(
          'Minimum slashable reserve bond is 50 USDC.',
          'La fianza ejecutable mínima es de 50 USDC.'
        );
    }
    return '';
  }

  function goNext() {
    const validationError = validateStep(step);
    if (validationError) {
      setError(validationError);
      return;
    }
    setError('');
    setStep((s) => Math.min(steps.length - 1, s + 1));
  }

  function goBack() {
    setError('');
    setStep((s) => Math.max(0, s - 1));
  }

  function jumpToStep(index: number) {
    if (index < step) {
      setError('');
      setStep(index);
      return;
    }
    for (let i = step; i < index; i++) {
      const err = validateStep(i);
      if (err) {
        setError(err);
        setStep(i);
        return;
      }
    }
    setError('');
    setStep(index);
  }

  function downloadManifest() {
    const json = JSON.stringify(manifestObject, null, 2);
    const blob = new Blob([json], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${slug}-manifest.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    setManifestDownloaded(true);
  }

  const tone = sustainabilityTone(economics.sustainability);

  return (
    <>
      <PageHeader
        eyebrow={c('MACHINE ONBOARDING WIZARD', 'ASISTENTE DE INCORPORACIÓN DE MÁQUINAS')}
        title={c('Put your machine to work', 'Pon tu máquina a trabajar')}
        description={c(
          'Configure your hardware’s physical capabilities, cryptographic enclave authority, and Conatus survival economics to join the autonomous workforce.',
          'Configura las capacidades físicas de tu hardware, la autoridad de su enclave criptográfico y su economía de supervivencia Conatus para integrarla a la red.'
        )}
        action={
          <Link className="button" to="/app/agents">
            ← {c('Back to marketplace', 'Volver al mercado')}
          </Link>
        }
      />

      {/* Interactive Stepper */}
      <ol
        className="register-stepper"
        aria-label={c('Onboarding steps', 'Pasos de incorporación')}
      >
        {steps.map((item, idx) => {
          const isCurrent = idx === step;
          const isCompleted = idx < step;
          return (
            <li key={item.title}>
              <button
                type="button"
                className={`register-step-btn ${isCompleted ? 'completed' : ''}`}
                aria-current={isCurrent ? 'step' : undefined}
                onClick={() => jumpToStep(idx)}
              >
                <span className="register-step-num">
                  {isCompleted ? '✓' : idx + 1}
                </span>
                <div>
                  <strong style={{ display: 'block', fontSize: 12 }}>
                    {item.title}
                  </strong>
                  <small style={{ fontSize: 10, color: 'var(--muted)' }}>
                    {item.subtitle}
                  </small>
                </div>
              </button>
            </li>
          );
        })}
      </ol>

      <div className="register-layout">
        {/* Main Step Form Panel */}
        <section className="panel" aria-live="polite">
          {/* STEP 1: HARDWARE */}
          {step === 0 && (
            <div>
              <div className="panel-title">
                <div>
                  <span className="eyebrow">{c('STEP 01 / 05', 'PASO 01 / 05')}</span>
                  <h2>{c('Select physical embodiment & chassis', 'Selecciona el tipo de hardware y chasis')}</h2>
                  <p className="muted">
                    {c(
                      'Choose the physical form factor of your autonomous agent. Preset operating parameters will adapt automatically.',
                      'Elige la forma física de tu agente autónomo. Los parámetros operativos sugeridos se ajustarán automáticamente.'
                    )}
                  </p>
                </div>
              </div>

              <div
                className="embodiment-picker"
                role="radiogroup"
                aria-label={c('Hardware embodiment', 'Tipo de hardware')}
              >
                {EMBODIMENTS.map((emb) => {
                  const active = embodiment === emb;
                  const preset = EMBODIMENT_PRESETS[emb];
                  return (
                    <button
                      key={emb}
                      type="button"
                      className="embodiment-option"
                      aria-pressed={active}
                      onClick={() => selectEmbodiment(emb)}
                    >
                      <EmbodimentGlyph
                        embodiment={emb}
                        size={40}
                        tone={active ? 'thriving' : undefined}
                      />
                      <strong>{embodimentLabel(emb, c)}</strong>
                      <small>
                        {locale === 'es' ? preset.tagline[1] : preset.tagline[0]}
                      </small>
                    </button>
                  );
                })}
              </div>

              <div className="form-grid-2">
                <label>
                  {c('Agent callsign / name', 'Indicativo / nombre del agente')}
                  <input
                    value={name}
                    onChange={(e) => {
                      setName(e.target.value);
                      setError('');
                    }}
                    placeholder={c('e.g. Kestrel-14', 'ej. Kestrel-14')}
                  />
                </label>

                <label>
                  {c('Hardware model & payload summary', 'Modelo de hardware y carga útil')}
                  <input
                    value={model}
                    onChange={(e) => {
                      setModel(e.target.value);
                      setError('');
                    }}
                    placeholder={EMBODIMENT_PRESETS[embodiment].defaultModel}
                  />
                </label>
              </div>

              <div className="form-grid-3">
                <label>
                  {c('Operating city / hub', 'Ciudad / centro operativo')}
                  <input
                    value={city}
                    onChange={(e) => {
                      setCity(e.target.value);
                      setError('');
                    }}
                    placeholder={c('Monterrey', 'Monterrey')}
                  />
                </label>

                <label>
                  {c('Country (ISO code)', 'País (código ISO)')}
                  <input
                    value={country}
                    maxLength={3}
                    onChange={(e) => {
                      setCountry(e.target.value.toUpperCase());
                      setError('');
                    }}
                    placeholder="MX"
                  />
                </label>

                <label>
                  {c('Autonomy level', 'Nivel de autonomía')}
                  <select
                    value={autonomy}
                    onChange={(e) =>
                      setAutonomy(e.target.value as 'Autonomous' | 'Supervised')
                    }
                  >
                    <option value="Autonomous">
                      {c(
                        'Autonomous (self-dispatching)',
                        'Autónomo (autodespacho)'
                      )}
                    </option>
                    <option value="Supervised">
                      {c(
                        'Supervised (human co-sign)',
                        'Supervisado (co-firma humana)'
                      )}
                    </option>
                  </select>
                </label>
              </div>
            </div>
          )}

          {/* STEP 2: CAPABILITIES */}
          {step === 1 && (
            <div>
              <div className="panel-title">
                <div>
                  <span className="eyebrow">{c('STEP 02 / 05', 'PASO 02 / 05')}</span>
                  <h2>{c('Declare verifiable physical capabilities', 'Declara las capacidades físicas verificables')}</h2>
                  <p className="muted">
                    {c(
                      'Select the sensors, actuators, and operational capabilities installed on your machine. The matching engine uses this bitmask to route eligible missions.',
                      'Selecciona los sensores, actuadores y capacidades instaladas en tu máquina. El motor de emparejamiento usa esta máscara de bits para asignarle misiones.'
                    )}
                  </p>
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button
                    type="button"
                    onClick={() =>
                      setCapabilities(
                        EMBODIMENT_PRESETS[embodiment].defaultCapabilities
                      )
                    }
                  >
                    {c('Reset to preset', 'Restaurar sugeridas')}
                  </button>
                  <button type="button" onClick={() => setCapabilities([])}>
                    {c('Clear all', 'Limpiar todo')}
                  </button>
                </div>
              </div>

              <div
                className="capability-toggle-grid"
                role="group"
                aria-label={c('Capabilities list', 'Lista de capacidades')}
              >
                {CAPABILITIES.map((cap, idx) => {
                  const selected = capabilities.includes(idx);
                  return (
                    <button
                      key={cap}
                      type="button"
                      className="capability-toggle"
                      aria-pressed={selected}
                      onClick={() => toggleCapability(idx)}
                    >
                      <span>
                        {selected ? '✓ ' : ''}
                        {t(cap)}
                      </span>
                      <span className="capability-bit">b{idx}</span>
                    </button>
                  );
                })}
              </div>

              <div className="callout" style={{ marginBottom: 0 }}>
                <Icon name="target" />
                <div>
                  <strong>
                    {c(
                      `Bitmask ${capabilityMask.hex} (${capabilities.length} capabilities active)`,
                      `Máscara de bits ${capabilityMask.hex} (${capabilities.length} capacidades activas)`
                    )}
                  </strong>
                  <p>
                    {c(
                      `Your machine currently qualifies for ${matchingOpenMissions} open missions in the network directory.`,
                      `Tu máquina califica actualmente para ${matchingOpenMissions} misiones abiertas en el directorio de la red.`
                    )}
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* STEP 3: IDENTITY & KEYS */}
          {step === 2 && (
            <div>
              <div className="panel-title">
                <div>
                  <span className="eyebrow">{c('STEP 03 / 05', 'PASO 03 / 05')}</span>
                  <h2>{c('Cryptographic identity & economic owner', 'Identidad criptográfica y propietario económico')}</h2>
                  <p className="muted">
                    {c(
                      'Conatus separates the hardware signing key (inside the machine) from the economic owner wallet (you).',
                      'Conatus separa la llave de firma del dispositivo (en el hardware) de la wallet del propietario económico (tú).'
                    )}
                  </p>
                </div>
              </div>

              {/* Device Signing Authority */}
              <div className="key-box">
                <div className="key-box-header">
                  <div>
                    <span className="eyebrow" style={{ marginBottom: 4 }}>
                      {c('ROLE 01 · HARDWARE ENCLAVE', 'ROL 01 · ENCLAVE DE HARDWARE')}
                    </span>
                    <h3>
                      {c(
                        'Device signing authority (Ed25519)',
                        'Autoridad de firma del dispositivo (Ed25519)'
                      )}
                    </h3>
                  </div>
                  <div className="segmented">
                    <button
                      type="button"
                      aria-pressed={keyMode === 'paste'}
                      onClick={() => setKeyMode('paste')}
                    >
                      {c('Paste public key', 'Pegar clave pública')}
                    </button>
                    <button
                      type="button"
                      aria-pressed={keyMode === 'device'}
                      onClick={() => setKeyMode('device')}
                    >
                      {c('Generate on device', 'Generar en dispositivo')}
                    </button>
                  </div>
                </div>

                <p className="muted" style={{ fontSize: 12 }}>
                  {c(
                    'This keypair stays on the physical machine (TPM 2.0 / ATECC608B / Secure Enclave) and signs mission claims and telemetry proofs autonomously.',
                    'Este par de llaves permanece en la máquina física (TPM 2.0 / ATECC608B / Enclave Seguro) y firma reclamos de misión y pruebas de telemetría.'
                  )}
                </p>

                {keyMode === 'device' && (
                  <div style={{ marginBottom: 14 }}>
                    <pre style={{ margin: '0 0 10px' }}>
                      {`# Run directly on your ${embodimentLabel(embodiment, c)} onboard computer:\nnpx @conatus/device-sdk keygen --enclave auto --out /etc/conatus/device-id.json`}
                    </pre>
                    <p className="hint" style={{ margin: 0 }}>
                      {c(
                        'Copy the resulting base58 public key from your terminal and paste it below.',
                        'Copia la clave pública base58 generada en tu terminal y pégala a continuación.'
                      )}
                    </p>
                  </div>
                )}

                <label>
                  {c(
                    'Device signing public key (Solana base58)',
                    'Clave pública de firma del dispositivo (Solana base58)'
                  )}
                  <div style={{ display: 'flex', gap: 10 }}>
                    <input
                      value={deviceAuthority}
                      onChange={(e) => {
                        setDeviceAuthority(e.target.value);
                        setError('');
                      }}
                      placeholder={c(
                        'Base58 public key from device enclave',
                        'Clave pública base58 del enclave del dispositivo'
                      )}
                    />
                    <button
                      type="button"
                      onClick={() => {
                        setDeviceAuthority(SAMPLE_PUBKEYS[embodiment]);
                        setError('');
                      }}
                    >
                      {c('Use preset key', 'Usar clave de ejemplo')}
                    </button>
                  </div>
                </label>
              </div>

              {/* Economic Owner Wallet */}
              <div className="key-box" style={{ marginBottom: 0 }}>
                <div className="key-box-header">
                  <div>
                    <span className="eyebrow" style={{ marginBottom: 4 }}>
                      {c('ROLE 02 · HUMAN / TREASURY OWNER', 'ROL 02 · PROPIETARIO ECONÓMICO')}
                    </span>
                    <h3>
                      {c(
                        'Economic owner wallet',
                        'Wallet del propietario económico'
                      )}
                    </h3>
                  </div>
                  {connected && publicKey ? (
                    <span className="onchain-badge">
                      <Pulse tone="success" />
                      {c('Wallet connected', 'Wallet conectada')}
                    </span>
                  ) : (
                    <span className="sustain sustain-at-risk">
                      <span aria-hidden="true" />
                      {c('Wallet required for final registration', 'Requerida para el registro final')}
                    </span>
                  )}
                </div>

                <p className="muted" style={{ fontSize: 12 }}>
                  {c(
                    'Your connected Solana wallet is recorded as the economic owner. It supplies the initial slashable bond, governs auto-pay limits, and receives net surplus distributions.',
                    'Tu wallet de Solana conectada se registra como propietaria económica. Aporta la fianza inicial, gobierna los límites de autopago y recibe los excedentes netos.'
                  )}
                </p>

                {connected && publicKey ? (
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      gap: 12,
                      flexWrap: 'wrap',
                      padding: '12px 14px',
                      borderRadius: 8,
                      border: '1px solid #79dfb040',
                      background: '#79dfb010',
                    }}
                  >
                    <div>
                      <small className="muted" style={{ display: 'block', fontSize: 11 }}>
                        {c('Connected economic owner', 'Propietario económico conectado')}
                      </small>
                      <CopyAddress
                        value={publicKey.toBase58()}
                        label={c('Owner wallet', 'Wallet propietaria')}
                      />
                    </div>
                    <WalletControl />
                  </div>
                ) : (
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      gap: 16,
                      flexWrap: 'wrap',
                      padding: '14px 16px',
                      borderRadius: 8,
                      border: '1px solid #f3c97c40',
                      background: '#f3c97c0f',
                    }}
                  >
                    <div>
                      <strong style={{ display: 'block', fontSize: 13 }}>
                        {c(
                          'Connect your Solana wallet to bind economic ownership',
                          'Conecta tu wallet de Solana para vincular la propiedad económica'
                        )}
                      </strong>
                      <small className="muted">
                        {c(
                          'You can continue configuring economics and connect right before registering on-chain.',
                          'Puedes continuar configurando la economía y conectar justo antes de registrar on-chain.'
                        )}
                      </small>
                    </div>
                    <WalletControl />
                  </div>
                )}
              </div>
            </div>
          )}

          {/* STEP 4: ECONOMICS */}
          {step === 3 && (
            <div>
              <div className="panel-title">
                <div>
                  <span className="eyebrow">{c('STEP 04 / 05', 'PASO 04 / 05')}</span>
                  <h2>{c('Configure survival economics (Conatus)', 'Configura la economía de supervivencia (Conatus)')}</h2>
                  <p className="muted">
                    {c(
                      'Define your machine’s mission pricing and monthly operating obligations. The live simulator calculates its break-even mission cadence and Conatus sustainability index.',
                      'Define la tarifa por misión y las obligaciones operativas mensuales de tu máquina. El simulador calcula su punto de equilibrio y su índice Conatus.'
                    )}
                  </p>
                </div>
              </div>

              <div className="form-grid-2">
                <label>
                  {c(
                    `Standard rate per mission (${SETTLEMENT_SYMBOL})`,
                    `Tarifa estándar por misión (${SETTLEMENT_SYMBOL})`
                  )}
                  <input
                    type="number"
                    min={1}
                    step={5}
                    value={rate}
                    onChange={(e) => {
                      setRate(Number(e.target.value));
                      setError('');
                    }}
                  />
                </label>

                <label>
                  {c(
                    `Expected missions / month (${targetJobs} jobs)`,
                    `Misiones estimadas / mes (${targetJobs} misiones)`
                  )}
                  <input
                    type="number"
                    min={1}
                    max={500}
                    value={targetJobs}
                    onChange={(e) => setTargetJobs(Number(e.target.value))}
                  />
                </label>
              </div>

              <h3 style={{ marginTop: 8, marginBottom: 12 }}>
                {c(
                  `Monthly operating obligations (${SETTLEMENT_SYMBOL} / 30 days)`,
                  `Obligaciones operativas mensuales (${SETTLEMENT_SYMBOL} / 30 días)`
                )}
              </h3>

              <div className="form-grid-2">
                <label>
                  {c('Energy & charging (USDC / mo)', 'Energía y recarga (USDC / mes)')}
                  <input
                    type="number"
                    min={0}
                    step={10}
                    value={energyCost}
                    onChange={(e) => setEnergyCost(Number(e.target.value))}
                  />
                </label>

                <label>
                  {c(
                    'Preventive maintenance & parts (USDC / mo)',
                    'Mantenimiento preventivo y piezas (USDC / mes)'
                  )}
                  <input
                    type="number"
                    min={0}
                    step={10}
                    value={maintenanceCost}
                    onChange={(e) => setMaintenanceCost(Number(e.target.value))}
                  />
                </label>

                <label>
                  {c(
                    'Hull & liability insurance (USDC / mo)',
                    'Seguro de casco y responsabilidad (USDC / mes)'
                  )}
                  <input
                    type="number"
                    min={0}
                    step={10}
                    value={insuranceCost}
                    onChange={(e) => setInsuranceCost(Number(e.target.value))}
                  />
                </label>

                <label>
                  {c(
                    'RTK / cellular / satellite connectivity (USDC / mo)',
                    'Conectividad RTK / celular / satelital (USDC / mes)'
                  )}
                  <input
                    type="number"
                    min={0}
                    step={10}
                    value={connectivityCost}
                    onChange={(e) => setConnectivityCost(Number(e.target.value))}
                  />
                </label>
              </div>

              <div className="form-grid-2">
                <label>
                  {c(
                    `Slashable reserve bond (${SETTLEMENT_SYMBOL})`,
                    `Fianza ejecutable en garantía (${SETTLEMENT_SYMBOL})`
                  )}
                  <input
                    type="number"
                    min={50}
                    step={50}
                    value={bond}
                    onChange={(e) => {
                      setBond(Number(e.target.value));
                      setError('');
                    }}
                  />
                </label>

                <label>
                  {c(
                    `Initial autonomous treasury seed (${SETTLEMENT_SYMBOL})`,
                    `Capital inicial de tesorería autónoma (${SETTLEMENT_SYMBOL})`
                  )}
                  <input
                    type="number"
                    min={100}
                    step={100}
                    value={initialTreasury}
                    onChange={(e) => setInitialTreasury(Number(e.target.value))}
                  />
                </label>
              </div>

              {/* Live Break-Even & Conatus Calculator */}
              <div className="breakeven-card" aria-label={c('Break-even calculator', 'Calculadora de punto de equilibrio')}>
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: 12,
                    flexWrap: 'wrap',
                  }}
                >
                  <div>
                    <span className="eyebrow" style={{ marginBottom: 4 }}>
                      {c('LIVE SURVIVAL SIMULATOR', 'SIMULADOR DE SUPERVIVENCIA EN VIVO')}
                    </span>
                    <h3 style={{ margin: 0 }}>
                      {c(
                        `Break-even: ${economics.breakEvenJobs} missions / month needed to self-sustain`,
                        `Punto de equilibrio: ${economics.breakEvenJobs} misiones / mes para autosostenerse`
                      )}
                    </h3>
                  </div>
                  <SustainabilityBadge value={economics.sustainability} />
                </div>

                <div className="breakeven-metrics">
                  <div className="breakeven-stat">
                    <span>{c('Break-even cadence', 'Misiones de equilibrio')}</span>
                    <strong>
                      {economics.breakEvenJobs} {c('jobs / mo', 'misiones / mes')}
                    </strong>
                  </div>
                  <div className="breakeven-stat">
                    <span>{c('Projected Conatus ratio', 'Ratio Conatus proyectado')}</span>
                    <strong
                      className={
                        economics.conatus >= 1 ? 'delta-up' : 'delta-down'
                      }
                    >
                      {economics.conatus.toFixed(2)}x
                    </strong>
                  </div>
                  <div className="breakeven-stat">
                    <span>{c('Projected 30d net margin', 'Margen neto 30d proyectado')}</span>
                    <strong
                      className={
                        economics.monthlyNet >= 0 ? 'delta-up' : 'delta-down'
                      }
                    >
                      {economics.monthlyNet >= 0 ? '+' : ''}
                      {usd(economics.monthlyNet, locale)} {SETTLEMENT_SYMBOL}
                    </strong>
                  </div>
                </div>

                <div>
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      fontSize: 12,
                      marginBottom: 6,
                    }}
                  >
                    <span className="muted">
                      {c('Projected 30d revenue:', 'Ingresos 30d proyectados:')}{' '}
                      <strong>{usd(economics.projectedRevenue, locale)}</strong>
                    </span>
                    <span className="muted">
                      {c('Total 30d costs (incl. 4% protocol):', 'Costos 30d totales (incl. 4% protocolo):')}{' '}
                      <strong>{usd(economics.totalMonthlyCost, locale)}</strong>
                    </span>
                  </div>
                  <Meter
                    value={Math.min(1, economics.conatus / 2.2)}
                    tone={tone}
                    label={c('Projected Conatus ratio', 'Ratio Conatus proyectado')}
                  />
                </div>
              </div>
            </div>
          )}

          {/* STEP 5: REVIEW & REGISTER */}
          {step === 4 && (
            <div>
              <div className="panel-title">
                <div>
                  <span className="eyebrow">{c('STEP 05 / 05', 'PASO 05 / 05')}</span>
                  <h2>{c('Review agent manifest & register on-chain', 'Revisa el manifiesto del agente y registra on-chain')}</h2>
                  <p className="muted">
                    {c(
                      'Verify your machine’s identity, capabilities, and survival economics. Download the signed manifest for your onboard daemon and register on Solana.',
                      'Verifica la identidad, capacidades y economía de supervivencia de tu máquina. Descarga el manifiesto para el demonio a bordo y regístrala en Solana.'
                    )}
                  </p>
                </div>
                <SustainabilityBadge value={economics.sustainability} />
              </div>

              <DataGrid
                items={[
                  [
                    c('Machine name & embodiment', 'Nombre y tipo de máquina'),
                    `${name} · ${embodimentLabel(embodiment, c)}`,
                  ],
                  [c('Hardware model', 'Modelo de hardware'), model],
                  [
                    c('Operating hub & autonomy', 'Ubicación y autonomía'),
                    `${city}, ${country} · ${
                      autonomy === 'Autonomous'
                        ? c('Autonomous', 'Autónomo')
                        : c('Supervised', 'Supervisado')
                    }`,
                  ],
                  [
                    c('Capability bitmask', 'Máscara de capacidades'),
                    `${capabilityMask.hex} (${capabilities.length} ${c('capabilities', 'capacidades')})`,
                  ],
                  [
                    c('Device signing authority', 'Autoridad de firma del dispositivo'),
                    <CopyAddress value={deviceAuthority} />,
                  ],
                  [
                    c('Economic owner wallet', 'Wallet del propietario económico'),
                    connected && publicKey ? (
                      <CopyAddress value={publicKey.toBase58()} />
                    ) : (
                      <span className="delta-down">
                        {c('Not connected — connect below', 'No conectada — conecta abajo')}
                      </span>
                    ),
                  ],
                  [
                    c('Standard mission rate', 'Tarifa estándar por misión'),
                    `${usd(rate, locale)} ${SETTLEMENT_SYMBOL}`,
                  ],
                  [
                    c('Break-even & Conatus ratio', 'Punto de equilibrio y Conatus'),
                    `${economics.breakEvenJobs} ${c('jobs/mo', 'misiones/mes')} · ${economics.conatus.toFixed(2)}x`,
                  ],
                  [
                    c('Monthly operating obligations', 'Obligaciones operativas mensuales'),
                    `${usd(economics.totalMonthlyCost, locale)} ${SETTLEMENT_SYMBOL} / 30d`,
                  ],
                  [
                    c('Slashable bond & initial treasury', 'Fianza ejecutable y tesorería inicial'),
                    `${usd(bond, locale)} ${c('bond', 'fianza')} · ${usd(initialTreasury, locale)} ${c('treasury', 'tesorería')} (${economics.runwayDays}d ${c('runway', 'autonomía')})`,
                  ],
                ]}
              />

              {!connected && (
                <div
                  className="callout"
                  style={{
                    borderColor: '#f3c97c45',
                    background: 'linear-gradient(90deg, #f3c97c14, transparent)',
                  }}
                >
                  <Icon name="wallet" />
                  <div style={{ flex: 1 }}>
                    <strong>
                      {c(
                        'Connect economic owner wallet to enable on-chain registration',
                        'Conecta la wallet del propietario económico para habilitar el registro on-chain'
                      )}
                    </strong>
                    <p>
                      {c(
                        'On-chain registration binds your connected Solana wallet as the economic owner of this machine.',
                        'El registro on-chain vincula tu wallet de Solana conectada como propietaria económica de esta máquina.'
                      )}
                    </p>
                  </div>
                  <WalletControl />
                </div>
              )}

              <div className="actions">
                <button type="button" onClick={downloadManifest}>
                  <Icon name="download" />
                  {manifestDownloaded
                    ? c('Manifest downloaded ✓', 'Manifiesto descargado ✓')
                    : c('Download agent manifest (.json)', 'Descargar manifiesto del agente (.json)')}
                </button>

                <button
                  type="button"
                  className="primary"
                  disabled={!connected || !publicKey}
                  onClick={() => setSdkModalOpen(true)}
                >
                  <Icon name="shield" />
                  {c('Register on-chain', 'Registrar on-chain')}
                </button>
              </div>

              <div className="sdk-provision-box">
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: 12,
                    flexWrap: 'wrap',
                    marginBottom: 10,
                  }}
                >
                  <strong style={{ fontSize: 13 }}>
                    {c(
                      'Hardware-co-signed registration via Conatus Device SDK',
                      'Registro co-firmado en hardware mediante Conatus Device SDK'
                    )}
                  </strong>
                  <EarlyAccess />
                </div>
                <p className="muted" style={{ fontSize: 12, marginBottom: sdkModalOpen ? 12 : 0 }}>
                  {c(
                    'To guarantee every registered agent is backed by real physical hardware, the genesis registration transaction is co-signed by the machine’s onboard enclave via the Conatus Device SDK and approved by your owner wallet.',
                    'Para garantizar que cada agente registrado corresponda a una máquina física real, la transacción génesis de registro es co-firmada por el enclave a bordo mediante el SDK del dispositivo y aprobada por tu wallet propietaria.'
                  )}
                </p>

                {sdkModalOpen && connected && publicKey && (
                  <div>
                    <pre style={{ margin: '0 0 10px' }}>
                      {`npx @conatus/device-sdk register \\\n  --manifest ./${slug}-manifest.json \\\n  --owner ${publicKey.toBase58()} \\\n  --bond ${bond}`}
                    </pre>
                    <p className="hint" style={{ margin: 0, color: 'var(--success)' }}>
                      ✓{' '}
                      {c(
                        `Ready for device co-signing. Download ./${slug}-manifest.json above and run this command on ${name} to broadcast the registration PDA.`,
                        `Listo para co-firma en el dispositivo. Descarga ./${slug}-manifest.json arriba y ejecuta este comando en ${name} para emitir el PDA de registro.`
                      )}
                    </p>
                  </div>
                )}
              </div>

              <details className="diagnostics">
                <summary>
                  {c('Inspect generated agent manifest JSON', 'Inspeccionar JSON del manifiesto generado')}
                </summary>
                <pre>{JSON.stringify(manifestObject, null, 2)}</pre>
              </details>
            </div>
          )}

          {error && (
            <p className="field-error" role="alert">
              {error}
            </p>
          )}

          {/* Step Footer Navigation */}
          <div className="wizard-footer-nav">
            <button
              type="button"
              disabled={step === 0}
              onClick={goBack}
            >
              ← {c('Previous step', 'Paso anterior')}
            </button>

            <span className="muted" style={{ fontSize: 12 }}>
              {c(`Step ${step + 1} of ${steps.length}`, `Paso ${step + 1} de ${steps.length}`)}
            </span>

            {step < steps.length - 1 ? (
              <button type="button" className="primary" onClick={goNext}>
                {c('Continue', 'Continuar')} →
              </button>
            ) : (
              <Link className="button" to="/app/agents">
                {c('Return to marketplace', 'Volver al mercado')}
              </Link>
            )}
          </div>
        </section>

        {/* Live Agent Card Preview Sidebar */}
        <aside className="panel" aria-label={c('Live agent preview', 'Vista previa en vivo del agente')}>
          <div className="panel-title" style={{ marginBottom: 14 }}>
            <div>
              <span className="eyebrow">{c('LIVE AGENT PREVIEW', 'VISTA PREVIA EN VIVO')}</span>
              <h2 style={{ fontSize: 16 }}>
                {name.trim() || c('Unnamed machine', 'Máquina sin nombre')}
              </h2>
            </div>
            <SustainabilityBadge value={economics.sustainability} />
          </div>

          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 14,
              marginBottom: 16,
            }}
          >
            <EmbodimentGlyph
              embodiment={embodiment}
              size={52}
              tone={economics.sustainability}
            />
            <div style={{ minWidth: 0 }}>
              <strong style={{ display: 'block', fontSize: 14 }}>
                {embodimentShortLabel(embodiment, c)} · {autonomy === 'Autonomous' ? c('Autonomous', 'Autónomo') : c('Supervised', 'Supervisado')}
              </strong>
              <small className="muted" style={{ display: 'block' }}>
                {model.trim() || EMBODIMENT_PRESETS[embodiment].defaultModel}
              </small>
              <small className="muted">
                {city.trim() || '—'}, {country.trim() || '—'}
              </small>
            </div>
          </div>

          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 16,
              padding: 14,
              borderRadius: 10,
              background: '#090c0b85',
              border: '1px solid #ffffff0a',
              marginBottom: 16,
            }}
          >
            <Ring
              value={Math.min(1, economics.conatus / 2.2)}
              tone={tone}
              size={84}
              label={c('Projected Conatus ratio', 'Ratio Conatus proyectado')}
            >
              <strong style={{ fontSize: 16 }}>
                {economics.conatus.toFixed(2)}x
              </strong>
              <small>Conatus</small>
            </Ring>
            <div style={{ display: 'grid', gap: 4, fontSize: 12 }}>
              <div>
                <span className="muted">{c('Rate / job:', 'Tarifa / misión:')}</span>{' '}
                <strong>
                  {usd(Number(rate) || 0, locale)} {SETTLEMENT_SYMBOL}
                </strong>
              </div>
              <div>
                <span className="muted">{c('Break-even:', 'Equilibrio:')}</span>{' '}
                <strong>
                  {economics.breakEvenJobs} {c('jobs/mo', 'misiones/mes')}
                </strong>
              </div>
              <div>
                <span className="muted">{c('30d costs:', 'Costos 30d:')}</span>{' '}
                <strong>{usd(economics.totalMonthlyCost, locale)}</strong>
              </div>
              <div>
                <span className="muted">{c('Runway:', 'Autonomía:')}</span>{' '}
                <strong>
                  {num(economics.runwayDays, locale)} {c('days', 'días')}
                </strong>
              </div>
            </div>
          </div>

          <div style={{ marginBottom: 14 }}>
            <small
              className="muted"
              style={{
                display: 'block',
                fontSize: 10,
                textTransform: 'uppercase',
                letterSpacing: '0.06em',
                marginBottom: 8,
              }}
            >
              {c('Selected capabilities', 'Capacidades seleccionadas')} (
              {capabilities.length})
            </small>
            <div className="agent-card-caps">
              {capabilities.slice(0, 6).map((idx) => (
                <span key={idx} className="chip">
                  {t(CAPABILITIES[idx] ?? '')}
                </span>
              ))}
              {capabilities.length > 6 && (
                <span className="chip chip-more">+{capabilities.length - 6}</span>
              )}
              {capabilities.length === 0 && (
                <span className="muted" style={{ fontSize: 12 }}>
                  {c('None selected', 'Ninguna seleccionada')}
                </span>
              )}
            </div>
          </div>

          <div className="survival-kv-list">
            <div className="survival-kv">
              <span>{c('Device signer', 'Firmador hardware')}</span>
              <code>{short(deviceAuthority || '—')}</code>
            </div>
            <div className="survival-kv">
              <span>{c('Economic owner', 'Propietario económico')}</span>
              <code>
                {connected && publicKey
                  ? short(publicKey.toBase58())
                  : c('Not connected', 'Sin conectar')}
              </code>
            </div>
            <div className="survival-kv">
              <span>{c('Slashable bond', 'Fianza ejecutable')}</span>
              <strong>
                {usd(Number(bond) || 0, locale)} {SETTLEMENT_SYMBOL}
              </strong>
            </div>
            <div className="survival-kv">
              <span>{c('Matching open missions', 'Misiones abiertas compatibles')}</span>
              <strong className="delta-up">{matchingOpenMissions}</strong>
            </div>
          </div>
        </aside>
      </div>
    </>
  );
}
