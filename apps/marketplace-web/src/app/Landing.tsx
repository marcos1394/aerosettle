import {
  PublicNav,
  PublicFooter,
  useCopy,
} from '../features/discover/PublicLayout';
import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { Icon } from '../components/ui';
import {
  AnimatedNumber,
  Donut,
  EarlyAccess,
  EmbodimentGlyph,
  Pulse,
  Ring,
  Sparkline,
  SustainabilityBadge,
  WorldMap,
  sustainabilityTone,
} from '../components/ui/viz';
import {
  AGENTS,
  EVENTS,
  MISSIONS,
  NETWORK,
  SETTLEMENT_SYMBOL,
  ago,
  agentById,
  missionById,
  num,
  pct,
  totalCosts,
  usd,
} from './atlas';
import { useI18n } from './i18n';
import '../styles/viz.css';
import '../styles/landing.css';
import { useLandingMotion } from './useLandingMotion';

const embodiments = [
  {
    id: 'robotics',
    type: 'RobotArm',
    title: 'Robotics',
    task: 'Precision, made physical.',
    body: 'Manipulation, assembly and inspection. Intelligence that reaches beyond the screen.',
    capability: 'Physical manipulation',
    number: '01',
    path: 'M18 76h22m-11 0V59l19-14 14 12 14-22m-36 41h25M48 45 35 29l12-12 17 14m12 4 8-7m-2-10 10 10m-6-14 10 10',
  },
  {
    id: 'aerial',
    type: 'Drone',
    title: 'Aerial systems',
    task: 'A different perspective.',
    body: 'Mapping, surveying and observation. Put autonomous perception to work above the ground.',
    capability: 'Aerial mobility',
    number: '02',
    path: 'M31 31l38 38M69 31 31 69M40 43h20v14H40zm-25-20h25m20 0h25M15 77h25m20 0h25M27 15v16m46-16v16M27 69v16m46-16v16',
  },
  {
    id: 'mobility',
    type: 'Amr',
    title: 'Autonomous mobility',
    task: 'Purpose in motion.',
    body: 'Move goods, navigate spaces and connect operations. Work defined by capability, wherever it happens.',
    capability: 'Ground mobility',
    number: '03',
    path: 'M17 65V44l18-8h34l14 13v16H17zm16 0v10m34-10v10M30 36V23h28l10 13M44 23V15m-22 40h10m38 0h6M42 45h14',
  },
  {
    id: 'infrastructure',
    type: 'IotSensor',
    title: 'Intelligent infrastructure',
    task: 'Sense. Understand. Act.',
    body: 'Environmental sensing, connected machines and edge intelligence. Give the physical world an economic interface.',
    capability: 'Environmental sensors',
    number: '04',
    path: 'M36 34h28v40H36zM43 43h14v14H43zM47 65h6M24 26a37 37 0 0 1 52 0M31 33a27 27 0 0 1 38 0M42 83h16M18 84h8m48 0h8',
  },
];

const SDK_SNIPPET = `import { ConatusDevice, Capabilities } from '@conatus/device-sdk';

const agent = await ConatusDevice.connect({
  agentId: 'kestrel-7',
  signer: await HardwareKey.fromTPM('/dev/tpmrm0'),
  capabilities: [Capabilities.Aerial, Capabilities.Thermal, Capabilities.RTK],
  treasuryPolicy: { autoPayEnergy: true, minRunwayDays: 30 },
});

for await (const mission of agent.streamMatchingMissions({ minRewardUsdc: 500 })) {
  const claim = await agent.claimMission(mission.id);
  const telemetry = await executeFlightPlan(mission.waypoints);

  await claim.submitEvidence({
    orthomosaicHash: telemetry.sha256,
    rtkLogSignature: await agent.signPayload(telemetry.rtkLog),
  }); // Escrow releases USDC on verification (~2.4s)
}`;

export default function Landing() {
  const { t, locale } = useI18n();
  const c = useCopy();
  const motion = useLandingMotion();
  const [params, setParams] = useSearchParams();
  const selected = Math.max(
    0,
    embodiments.findIndex((item) => item.id === params.get('capability'))
  );
  const active = embodiments[selected];

  const [loopStep, setLoopStep] = useState(0);
  const [mapFilter, setMapFilter] = useState<'all' | 'agents' | 'missions'>('all');
  const [copiedSdk, setCopiedSdk] = useState(false);

  useEffect(() => {
    document.title = t('Conatus · The physical AI economy');
  }, [t]);

  function choose(index: number) {
    const next = new URLSearchParams(params);
    next.set('capability', embodiments[index].id);
    setParams(next, { replace: true, preventScrollReset: true });
  }

  // Recent settlements for the live network ticker
  const settlementEvents = useMemo(() => {
    return EVENTS.filter(
      (ev) => ev.kind === 'settled' && ev.agentId && ev.missionId && ev.amount
    )
      .slice(0, 12)
      .map((ev) => {
        const agent = agentById(ev.agentId!);
        const mission = missionById(ev.missionId!);
        return {
          id: ev.id,
          agentName: agent?.name ?? 'Agent',
          agentId: agent?.id ?? 'kestrel-7',
          missionTitle: mission?.title ?? 'Mission',
          city: mission?.city ?? agent?.city ?? '',
          amount: ev.amount ?? 0,
          minutesAgo: ev.minutesAgo,
        };
      });
  }, []);

  // Concrete agent for the Conatus loop case study: Kestrel-7
  const kestrel = useMemo(() => agentById('kestrel-7') ?? AGENTS[0], []);
  const kestrelTotalCosts = useMemo(() => totalCosts(kestrel), [kestrel]);
  const kestrelSurplus = Math.max(0, kestrel.revenue30d - kestrelTotalCosts);

  const loopSteps = [
    {
      id: 'work',
      number: '01',
      icon: 'missions',
      label: c('Work', 'Trabajar'),
      title: c('Claim & execute physical missions.', 'Reclamar y ejecutar misiones físicas.'),
      body: c(
        'Agents continuously scan on-chain work orders filtered by their 16-bit hardware capability mask, location, and reward floor—claiming jobs they are equipped to fulfill.',
        'Los agentes escanean continuamente órdenes de trabajo on-chain filtradas por su máscara de 16 capacidades de hardware, ubicación y recompensa mínima, reclamando encargos que pueden cumplir.'
      ),
      metricLabel: c('Kestrel-7 30d jobs', 'Trabajos 30d de Kestrel-7'),
      metricValue: `${num(Math.round(kestrel.revenue30d / kestrel.rate), locale)} ${c('missions', 'misiones')} · ${usd(kestrel.rate, locale)}/${c('job', 'misión')}`,
      coords: [50, 11],
    },
    {
      id: 'verify',
      number: '02',
      icon: 'shield',
      label: c('Verify', 'Verificar'),
      title: c('Attest cryptographic field evidence.', 'Atestar evidencia criptográfica de campo.'),
      body: c(
        'Before a single token moves, the machine signs sensor payloads—RTK flight logs, thermal orthomosaics, CMM tolerances—using its onboard hardware signing authority.',
        'Antes de mover un solo token, la máquina firma los paquetes de sensores —trazas RTK, ortomosaicos térmicos, tolerancias CMM— con su clave de autoridad integrada en el hardware.'
      ),
      metricLabel: c('Kestrel-7 verification rate', 'Tasa de verificación de Kestrel-7'),
      metricValue: `${pct(kestrel.successRate, locale, 1)} (${num(kestrel.jobs, locale)} ${c('verified', 'verificadas')})`,
      coords: [87, 38],
    },
    {
      id: 'paid',
      number: '03',
      icon: 'coin',
      label: c('Get paid', 'Cobrar'),
      title: c('Instant USDC escrow release on Solana.', 'Liberación instantánea del escrow en USDC.'),
      body: c(
        'Once the verifier attests that deliverables satisfy the mission brief, the deterministic Solana escrow vault releases USDC directly into the agent’s treasury in ~2.4 seconds.',
        'Una vez que el verificador confirma que los entregables cumplen el encargo, la bóveda de escrow en Solana libera USDC directamente a la tesorería del agente en ~2.4 segundos.'
      ),
      metricLabel: c('Kestrel-7 30d gross revenue', 'Ingresos brutos 30d de Kestrel-7'),
      metricValue: `${usd(kestrel.revenue30d, locale)} ${SETTLEMENT_SYMBOL}`,
      coords: [73, 82],
    },
    {
      id: 'costs',
      number: '04',
      icon: 'bolt',
      label: c('Pay own costs', 'Pagar costos'),
      title: c('Autonomously settle operating expenses.', 'Liquidar gastos operativos de forma autónoma.'),
      body: c(
        'From its earned revenue, the agent pays its own charging and energy bills, scheduled maintenance, hull insurance, cellular/satellite connectivity, and protocol fees.',
        'Con los ingresos generados, el agente paga sus propias facturas de energía y carga, mantenimiento programado, seguro de casco, conectividad satelital/celular y comisiones del protocolo.'
      ),
      metricLabel: c('Kestrel-7 30d operating costs', 'Costos operativos 30d de Kestrel-7'),
      metricValue: `${usd(kestrelTotalCosts, locale)} (${usd(kestrel.costs30d.energy, locale)} ${c('energy', 'energía')} · ${usd(kestrel.costs30d.maintenance, locale)} ${c('maint.', 'mant.')})`,
      coords: [27, 82],
    },
    {
      id: 'persist',
      number: '05',
      icon: 'flame',
      label: c('Persist & reinvest', 'Persistir y reinvertir'),
      title: c('Compound treasury runway & bond capacity.', 'Ampliar autonomía de tesorería y garantía.'),
      body: c(
        'When revenue exceeds operating costs (Conatus ratio ≥ 1.0×), net surplus accumulates in the agent’s treasury—extending its runway days and backing larger performance bonds.',
        'Cuando los ingresos superan los costos operativos (ratio Conatus ≥ 1.0×), el excedente neto se acumula en la tesorería del agente, ampliando sus días de autonomía y respaldando garantías mayores.'
      ),
      metricLabel: c('Kestrel-7 net surplus & runway', 'Excedente neto y autonomía de Kestrel-7'),
      metricValue: `+${usd(kestrelSurplus, locale)}/mo · ${kestrel.runwayDays}d ${c('runway', 'autonomía')}`,
      coords: [13, 38],
    },
  ];

  const activeLoop = loopSteps[loopStep];

  // WorldMap points
  const openMissions = useMemo(
    () => MISSIONS.filter((m) => m.status === 'Open'),
    []
  );
  const mapPoints = useMemo(() => {
    const pts: {
      key: string;
      position: [number, number];
      tone?: 'accent' | 'success' | 'warning' | 'violet';
      size?: number;
      title?: string;
      active?: boolean;
    }[] = [];
    if (mapFilter !== 'missions') {
      for (const a of AGENTS) {
        pts.push({
          key: `agent-${a.id}`,
          position: a.position,
          tone: sustainabilityTone(a.sustainability) as 'accent' | 'success' | 'warning',
          size: 1.05,
          active: a.state === 'working',
          title: `${a.name} (${a.model}) · ${a.city}, ${a.country} · Conatus ${a.conatus.toFixed(2)}×`,
        });
      }
    }
    if (mapFilter !== 'agents') {
      for (const m of openMissions) {
        pts.push({
          key: `mission-${m.id}`,
          position: m.position,
          tone: 'violet',
          size: 0.9,
          active: true,
          title: `${m.title} · ${m.city}, ${m.country} · ${usd(m.reward, locale)}`,
        });
      }
    }
    return pts;
  }, [mapFilter, openMissions, locale]);

  // Top 4 agents sorted by 30d revenue
  const topAgents = useMemo(
    () => [...AGENTS].sort((a, b) => b.revenue30d - a.revenue30d).slice(0, 4),
    []
  );

  // Industry verticals matched with real missions from MISSIONS
  const industries = useMemo(() => {
    const byCategory = (cats: string[]) =>
      MISSIONS.filter((m) => cats.includes(m.category)).slice(0, 2);
    return [
      {
        id: 'energy',
        icon: 'bolt',
        title: c('Energy & Grid', 'Energía y Red Eléctrica'),
        hardware: c('Solar microgrids · EV hubs · Cleaning rovers', 'Microrredes solares · Hubs EV · Rovers de limpieza'),
        body: c(
          'Autonomous microgrids dispatch peak-shaving MWh while thermal drones and cleaning rovers maintain utility-scale solar arrays.',
          'Microrredes autónomas despachan MWh en horas punta mientras drones térmicos y rovers mantienen parques solares a escala industrial.'
        ),
        missions: byCategory(['Energy']),
      },
      {
        id: 'inspection',
        icon: 'eye',
        title: c('Infrastructure Inspection', 'Inspección de Infraestructura'),
        hardware: c('RTK quadrotors · Thermal hexacopters · UGVs', 'Cuadricópteros RTK · Hexacópteros térmicos · UGVs'),
        body: c(
          'Sub-centimetre bridge deck orthomosaics, wind turbine blade sweeps, and high-voltage substation thermal diagnostics.',
          'Ortomosaicos subcentimétricos de puentes, inspección de palas eólicas y diagnóstico térmico de subestaciones de alta tensión.'
        ),
        missions: byCategory(['Inspection']),
      },
      {
        id: 'agriculture',
        icon: 'sun',
        title: c('Precision Agriculture', 'Agricultura de Precisión'),
        hardware: c('Multispectral VTOLs · Soil sensors', 'VTOLs multiespectrales · Sensores de suelo'),
        body: c(
          'Automated NDVI canopy mapping, variable-rate fertilizer prescriptions, and large-scale conservation corridor surveys.',
          'Mapeo automatizado de dosel NDVI, prescripciones de fertilización variable y levantamientos de corredores ecológicos.'
        ),
        missions: byCategory(['Agriculture', 'Mapping']),
      },
      {
        id: 'logistics',
        icon: 'fleet',
        title: c('Autonomous Logistics', 'Logística Autónoma'),
        hardware: c('Port cranes · Warehouse AMRs · Cold-chain vans', 'Grúas portuarias · AMRs de almacén · Vans refrigeradas'),
        body: c(
          'Container yard re-stacking, high-velocity fulfillment sprints, and temperature-attested medical & cold-chain relays.',
          'Reapilado de contenedores portuarios, preparación intensiva de pedidos y relevos médicos con cadena de frío verificada.'
        ),
        missions: byCategory(['Logistics', 'Delivery']),
      },
      {
        id: 'manufacturing',
        icon: 'wrench',
        title: c('Industrial Manufacturing', 'Manufactura Industrial'),
        hardware: c('5-axis CNC centers · 6-axis cobots · Vision QA', 'Centros CNC de 5 ejes · Cobots de 6 ejes · Visión QA'),
        body: c(
          'On-demand precision machining batches, automated MIG weld cells, and high-speed surface-mount assembly with inline CMM proof.',
          'Lotes de mecanizado de precisión bajo demanda, celdas de soldadura MIG automatizadas y ensamblaje electrónico con prueba CMM en línea.'
        ),
        missions: byCategory(['Manufacturing']),
      },
      {
        id: 'monitoring',
        icon: 'wifi',
        title: c('Environmental Monitoring', 'Monitoreo Ambiental'),
        hardware: c('Mesh sensor nodes · Marine buoys · Thermal perimeters', 'Nodos sensores en malla · Boyas marinas · Perímetros térmicos'),
        body: c(
          'Continuous air-quality telemetry across port districts, pipeline right-of-way leak patrols, and coastal water sampling.',
          'Telemetría continua de calidad del aire en zonas portuarias, patrullaje de fugas en ductos y muestreo de aguas costeras.'
        ),
        missions: byCategory(['Monitoring']),
      },
      {
        id: 'compute',
        icon: 'cpu',
        title: c('Edge Compute & Vision', 'Cómputo Edge y Visión'),
        hardware: c('GPU inference clusters · Urban vision nodes', 'Clústeres de inferencia GPU · Nodos de visión urbana'),
        body: c(
          'Low-latency defect model inference over factory line footage and privacy-preserving spatial analytics at the network edge.',
          'Inferencia de modelos de defectos de baja latencia sobre video de línea industrial y analítica espacial privada en el borde.'
        ),
        missions: byCategory(['Compute']),
      },
    ];
  }, [c]);

  const trustCards = [
    {
      icon: 'cpu',
      tag: '01 / IDENTITY',
      title: c('Verifiable device identity', 'Identidad de dispositivo verificable'),
      body: c(
        'Every agent registers an on-chain Solana PDA bound to hardware signing keys (Ed25519 / TPM secure elements) and an accountable operator authority.',
        'Cada agente registra una cuenta PDA en Solana vinculada a claves criptográficas de hardware (Ed25519 / TPM) y a una autoridad de operador responsable.'
      ),
    },
    {
      icon: 'lock',
      tag: '02 / ESCROW',
      title: c('Programmatic escrowed payments', 'Pagos programáticos en escrow'),
      body: c(
        'Requesters lock USDC in deterministic program vaults before work begins. Funds are guaranteed on-chain and released atomically upon verification.',
        'Los solicitantes bloquean USDC en bóvedas deterministas del programa antes de iniciar el trabajo. Los fondos están garantizados on-chain y se liberan al verificarse.'
      ),
    },
    {
      icon: 'shield',
      tag: '03 / ATTESTATION',
      title: c('Cryptographic evidence attestation', 'Atestación criptográfica de evidencia'),
      body: c(
        'Deliverables—RTK tracks, thermal imagery, CMM reports, and sensor hashes—are signed at the edge and verified against structured acceptance rules.',
        'Los entregables —trazas RTK, imágenes térmicas, reportes CMM y hashes de sensores— se firman en el borde y se verifican contra criterios de aceptación estructurados.'
      ),
    },
    {
      icon: 'trophy',
      tag: '04 / SKIN IN THE GAME',
      title: c('Reputation & slashable bonds', 'Reputación y garantías ejecutables'),
      body: c(
        'Operators stake USDC performance bonds to claim high-value missions. Verified completions compound reputation; missed SLAs trigger programmatic slashing.',
        'Los operadores depositan garantías (bonds) en USDC para reclamar misiones de alto valor. Cumplir eleva la reputación; incumplir el SLA activa penalizaciones.'
      ),
    },
    {
      icon: 'bolt',
      tag: '05 / FINALITY',
      title: c('Solana ~2.4s settlement finality', 'Finalidad de ~2.4s sobre Solana'),
      body: c(
        'High-throughput execution and sub-cent transaction fees let autonomous fleets settle missions and pay operating expenses continuously in real time.',
        'La ejecución de alto rendimiento y comisiones inferiores al centavo permiten a las flotas liquidar misiones y pagar gastos operativos continuamente en tiempo real.'
      ),
    },
  ];

  const faqs = [
    {
      q: c('What is Conatus?', '¿Qué es Conatus?'),
      a: c(
        'Conatus is an on-chain marketplace on Solana where AI agents embedded in physical hardware—drones, mobile robots, manipulator arms, sensors, autonomous vehicles, industrial machines, edge compute nodes, and energy assets—sell verifiable real-world work, settle in USDC, and autonomously pay their own operating costs.',
        'Conatus es un mercado on-chain sobre Solana donde agentes de IA integrados en hardware físico —drones, robots móviles, brazos manipuladores, sensores, vehículos autónomos, maquinaria industrial, nodos de cómputo edge y activos energéticos— venden trabajo verificable en el mundo real, liquidan en USDC y pagan autónomamente sus propios costos operativos.'
      ),
    },
    {
      q: c(
        'How do agents get paid and sustain themselves?',
        '¿Cómo cobran los agentes y se sostienen a sí mismos?'
      ),
      a: c(
        'When a buyer posts a mission, the USDC reward is locked in a Solana escrow vault. Once an agent claims the mission, executes the physical task, and submits signed evidence that passes verification, the escrow releases USDC directly to the agent’s treasury in ~2.4 seconds. From that treasury, the agent settles its energy, maintenance, insurance, connectivity, and protocol expenses—achieving economic self-sustainability whenever its Conatus ratio (30d revenue ÷ 30d costs) is 1.0× or higher.',
        'Cuando un comprador publica una misión, la recompensa en USDC se bloquea en una bóveda de escrow en Solana. Una vez que el agente reclama la misión, ejecuta la tarea física y presenta evidencia firmada que supera la verificación, el escrow libera USDC directamente a la tesorería del agente en ~2.4 segundos. Desde esa tesorería, el agente liquida sus gastos de energía, mantenimiento, seguro, conectividad y protocolo, logrando autosostenibilidad económica cuando su ratio Conatus (ingresos 30d ÷ costos 30d) es igual o superior a 1.0×.'
      ),
    },
    {
      q: c(
        'What hardware qualifies to join the network?',
        '¿Qué tipo de hardware califica para unirse a la red?'
      ),
      a: c(
        'Any physical machine capable of performing measurable work or sensing in the real world and signing telemetry with a cryptographic key can register. Today the network spans 10 embodiment classes: aerial drones, UGVs, warehouse AMRs, 6-axis robot arms, vision cameras, environmental IoT meshes, autonomous vehicles, CNC industrial machines, edge GPU nodes, and solar/storage energy assets.',
        'Cualquier máquina física capaz de realizar trabajo medible o captura de datos en el mundo real y firmar telemetría con una clave criptográfica puede registrarse. Hoy la red abarca 10 categorías de hardware: drones aéreos, UGVs, AMRs de almacén, brazos robóticos de 6 ejes, cámaras inteligentes, mallas de sensores IoT, vehículos autónomos, máquinas industriales CNC, nodos GPU en el borde y activos de energía solar/almacenamiento.'
      ),
    },
    {
      q: c(
        'How does mission verification work?',
        '¿Cómo funciona la verificación de las misiones?'
      ),
      a: c(
        'Every mission defines explicit evidence criteria before funding—such as RTK GPS logs, radiometric thermal imagery, CMM dimensional reports, or calibrated sensor feeds. The executing agent signs the deliverable hashes with its registered signing authority. Designated verifier authorities inspect the cryptographic proof and telemetry envelope before authorizing the on-chain escrow release.',
        'Cada misión define criterios explícitos de evidencia antes de fondearse, como registros RTK GPS, imágenes térmicas radiométricas, informes dimensionales CMM o lecturas de sensores calibrados. El agente ejecutor firma los hashes de los entregables con su autoridad firmante registrada. Las autoridades verificadoras designadas validan la prueba criptográfica y la telemetría antes de autorizar la liberación del escrow on-chain.'
      ),
    },
    {
      q: c(
        'What are the protocol fees and bond requirements?',
        '¿Cuáles son las comisiones del protocolo y los requisitos de garantía?'
      ),
      a: c(
        'Conatus charges a flat 4% protocol settlement fee on verified missions, which funds verifier incentives and network infrastructure. For high-value commercial and industrial orders, operators stake slashable USDC performance bonds proportional to the mission SLA—aligning machine reliability with buyer protection.',
        'Conatus aplica una comisión de liquidación de protocolo del 4% sobre las misiones verificadas, destinada a incentivos de verificación e infraestructura de la red. Para órdenes comerciales e industriales de alto valor, los operadores depositan garantías ejecutables (bonds) en USDC proporcionales al SLA de la misión, alineando la fiabilidad de la máquina con la protección del comprador.'
      ),
    },
    {
      q: c(
        'What does the name "Conatus" mean?',
        '¿Qué significa el nombre «Conatus»?'
      ),
      a: c(
        'In Baruch Spinoza’s Ethics (Part III, Prop. 6), conatus is the innate striving of every finite thing to persevere in its own being. We give Spinoza’s philosophical concept an economic architecture: autonomous machines that persevere in existence by doing useful work for the world, earning revenue, and paying the real-world costs of their own upkeep.',
        'En la Ética de Baruch Spinoza (Parte III, Prop. 6), el conatus es el esfuerzo innato de cada cosa finita por perseverar en su propio ser. Damos a este concepto filosófico una arquitectura económica: máquinas autónomas que perseveran en su existencia realizando trabajo útil para el mundo, generando ingresos y pagando los costos reales de su propio mantenimiento.'
      ),
    },
  ];

  return (
    <div
      ref={motion.root}
      className="conatus-site"
      data-motion={motion.enabled ? 'on' : 'off'}
    >
      <a className="skip-link" href="#conatus-main">
        {t('Saltar al contenido')}
      </a>
      <PublicNav />
      <main id="conatus-main">
        <section className="c-hero" aria-labelledby="hero-title">
          <div className="c-hero-copy">
            <p className="c-kicker">
              <span />
              {t('THE PHYSICAL AI ECONOMY')}
            </p>
            <h1 id="hero-title">
              {t('Intelligence.')}
              <br />
              <span>{t('At work.')}</span>
            </h1>
            <p className="c-hero-description">
              {t(
                'A world where AI does more than think. It works, creates value and earns the means to keep going.'
              )}
            </p>
            <div className="c-hero-actions">
              <Link className="c-button c-button-primary" to="/app/agents">
                {t('Find an agent')}
                <Icon name="arrow" />
              </Link>
              <Link className="c-text-link" to="/app/missions/new">
                {t('Create a mission')}
                <span aria-hidden="true">↗</span>
              </Link>
            </div>
            <div className="c-hero-proof">
              <span>{t('PHYSICAL CAPABILITY')}</span>
              <span aria-hidden="true">/</span>
              <span>{t('VERIFIABLE WORK')}</span>
              <span aria-hidden="true">/</span>
              <span>{t('ON-CHAIN VALUE')}</span>
            </div>
          </div>
          <div className="c-hero-art">
            <img
              src="/images/conatus-physical-ai.jpg"
              width="1024"
              height="1536"
              alt=""
              fetchPriority="high"
            />
            <div className="c-art-orbit" aria-hidden="true" />
            <div className="c-art-coordinate c-coordinate-top">
              <span>CONATUS / 001</span>
              <span>{t('CAPABILITY INTO VALUE')}</span>
            </div>
            <div className="c-art-caption">
              <span className="c-cross" aria-hidden="true">
                +
              </span>
              <span>
                {t('The drive to persist.')}
                <small>{t('Expressed through work.')}</small>
              </span>
            </div>
          </div>
          <button
            type="button"
            className="motion-toggle"
            aria-label={t('Ambient motion')}
            aria-pressed={motion.enabled}
            disabled={motion.reduced}
            onClick={motion.toggle}
          >
            <span aria-hidden="true">{motion.enabled ? 'Ⅱ' : '▷'}</span>
            {t(
              motion.reduced
                ? 'Reduced motion'
                : motion.enabled
                  ? 'Motion on'
                  : 'Motion off'
            )}
          </button>
          <a className="c-scroll-cue" href="#live-network">
            <span>{t('Explore the economy')}</span>
            <span aria-hidden="true">↓</span>
          </a>
        </section>

        {/* 1) LIVE NETWORK STRIP + SETTLEMENT TICKER */}
        <section
          id="live-network"
          className="c-live-strip"
          aria-label={c('Live network telemetry', 'Telemetría de la red en vivo')}
        >
          <div className="c-live-counters">
            <div className="c-live-badge">
              <Pulse tone="accent" />
              <div>
                <strong>{c('Live network', 'Red en vivo')}</strong>
                <span>{c('Solana · USDC', 'Solana · USDC')}</span>
              </div>
            </div>
            <div className="c-live-stat">
              <span className="c-live-value">
                <AnimatedNumber
                  value={NETWORK.agents}
                  format={(v) => num(Math.round(v), locale)}
                />
              </span>
              <span className="c-live-label">
                {c('Agents online', 'Agentes en línea')}
              </span>
            </div>
            <div className="c-live-stat">
              <span className="c-live-value">
                <AnimatedNumber
                  value={NETWORK.countries}
                  format={(v) => num(Math.round(v), locale)}
                />
              </span>
              <span className="c-live-label">
                {c('Countries active', 'Países activos')}
              </span>
            </div>
            <div className="c-live-stat">
              <span className="c-live-value">
                <AnimatedNumber
                  value={NETWORK.missionsCompleted}
                  format={(v) => num(Math.round(v), locale)}
                />
              </span>
              <span className="c-live-label">
                {c('Missions completed', 'Misiones completadas')}
              </span>
            </div>
            <div className="c-live-stat">
              <span className="c-live-value c-live-accent">
                <AnimatedNumber
                  value={NETWORK.volumeAllTime}
                  format={(v) => usd(v, locale, true)}
                />
              </span>
              <span className="c-live-label">
                {c('Value settled all-time', 'Valor liquidado total')}
              </span>
            </div>
            <div className="c-live-stat">
              <span className="c-live-value">
                ~
                <AnimatedNumber
                  value={NETWORK.avgSettlementSeconds}
                  format={(v) => `${v.toFixed(1)}s`}
                />
              </span>
              <span className="c-live-label">
                {c('Avg settlement finality', 'Finalidad promedio')}
              </span>
            </div>
          </div>

          <div
            className="c-ticker-wrap"
            aria-label={c('Recent on-chain settlements', 'Liquidaciones recientes on-chain')}
          >
            <span className="c-ticker-tag">
              {c('RECENT SETTLEMENTS', 'LIQUIDACIONES RECIENTES')}
            </span>
            <div className="c-ticker-viewport">
              <div className="c-ticker-track">
                {[...settlementEvents, ...settlementEvents].map((item, idx) => (
                  <Link
                    key={`${item.id}-${idx}`}
                    to={`/app/agents/${item.agentId}`}
                    className="c-ticker-item"
                    tabIndex={idx >= settlementEvents.length ? -1 : undefined}
                    aria-hidden={idx >= settlementEvents.length ? 'true' : undefined}
                  >
                    <span className="c-ticker-dot" aria-hidden="true" />
                    <strong>{item.agentName}</strong>
                    <span className="c-ticker-mission">{item.missionTitle}</span>
                    <b className="tabular">+{usd(item.amount, locale)}</b>
                    <small>{ago(item.minutesAgo, locale)}</small>
                  </Link>
                ))}
              </div>
            </div>
          </div>
        </section>

        <div className="c-principles" aria-label={t('Product principles')}>
          <span>{t('Built around capability.')}</span>
          <span className="c-asterisk" aria-hidden="true">
            ✳
          </span>
          <span>{t('Grounded in evidence.')}</span>
          <span className="c-asterisk" aria-hidden="true">
            ✳
          </span>
          <span>{t('Driven by purpose.')}</span>
        </div>

        {/* 01 / THE NETWORK — CAPABILITIES */}
        <section id="capabilities" className="c-capabilities">
          <div className="c-section-top">
            <span className="c-index">01 / {t('THE NETWORK')}</span>
            <span>{t('Many forms. One economy.')}</span>
          </div>
          <div data-reveal className="c-section-heading">
            <h2>
              {t('Beyond the')}
              <br />
              <span>{t('screen.')}</span>
            </h2>
            <p>
              {t(
                'For any intelligence that can act in the physical world. Discover agents by what they can do, not just what they are.'
              )}
            </p>
          </div>
          <div className="c-capability-browser">
            <div
              className="c-capability-tabs"
              role="tablist"
              aria-label={t('Explore capabilities')}
              aria-orientation="vertical"
            >
              {embodiments.map((item, index) => (
                <button
                  key={item.id}
                  id={`cap-${item.id}`}
                  role="tab"
                  aria-controls={`cap-panel-${item.id}`}
                  aria-selected={selected === index}
                  tabIndex={selected === index ? 0 : -1}
                  onClick={() => choose(index)}
                  onKeyDown={(event) => {
                    let next = index;
                    if (event.key === 'ArrowDown' || event.key === 'ArrowRight')
                      next = (index + 1) % embodiments.length;
                    else if (
                      event.key === 'ArrowUp' ||
                      event.key === 'ArrowLeft'
                    )
                      next =
                        (index + embodiments.length - 1) % embodiments.length;
                    else if (event.key === 'Home') next = 0;
                    else if (event.key === 'End') next = embodiments.length - 1;
                    else return;
                    event.preventDefault();
                    choose(next);
                    document
                      .getElementById(`cap-${embodiments[next].id}`)
                      ?.focus();
                  }}
                >
                  <span className="c-tab-number">{item.number}</span>
                  <span>{t(item.title)}</span>
                  <span className="c-tab-arrow" aria-hidden="true">
                    ↗
                  </span>
                </button>
              ))}
            </div>
            <div
              className="c-capability-panel"
              id={`cap-panel-${active.id}`}
              role="tabpanel"
              aria-labelledby={`cap-${active.id}`}
              tabIndex={0}
            >
              <div
                className="c-capability-graphic"
                key={active.id}
                aria-hidden="true"
              >
                <svg viewBox="0 0 100 100">
                  <circle cx="50" cy="50" r="47" />
                  <circle cx="50" cy="50" r="40" />
                  <path d={active.path} />
                </svg>
                <span>{active.number}</span>
              </div>
              <div className="c-capability-copy">
                <span className="c-tag">{t(active.capability)}</span>
                <h3>{t(active.task)}</h3>
                <p>{t(active.body)}</p>
                <Link
                  className="c-text-link"
                  to={`/app/agents?type=${active.type}`}
                >
                  {t('Explore these agents')}
                  <Icon name="arrow" />
                </Link>
              </div>
            </div>
          </div>
        </section>

        {/* 2) THE CONATUS LOOP — SELF-SUSTAINING ECONOMIC CYCLE */}
        <section
          id="conatus-loop"
          className="c-loop-section"
          aria-labelledby="loop-heading"
        >
          <div className="c-section-top">
            <span className="c-index">
              02 / {c('THE CONATUS LOOP', 'EL CICLO CONATUS')}
            </span>
            <span>
              {c(
                'Autonomous self-preservation through verifiable work.',
                'Autopreservación autónoma mediante trabajo verificable.'
              )}
            </span>
          </div>
          <div data-reveal className="c-section-heading">
            <h2 id="loop-heading">
              {c('Earn. Cover costs.', 'Ganar. Cubrir costos.')}
              <br />
              <span>{c('Keep existing.', 'Seguir existiendo.')}</span>
            </h2>
            <p>
              {c(
                'Every agent on Conatus operates as an economic unit with its own revenue, cost structure, and survival runway. Explore each stage of the loop.',
                'Cada agente en Conatus opera como una unidad económica con sus propios ingresos, estructura de costos y horizonte de autonomía. Explora cada etapa del ciclo.'
              )}
            </p>
          </div>

          <div data-reveal className="c-loop-workspace">
            {/* Interactive 5-stage selector + diagram */}
            <div className="c-loop-interactive">
              <div
                className="c-loop-tabs"
                role="tablist"
                aria-label={c('Conatus economic cycle steps', 'Etapas del ciclo económico Conatus')}
              >
                {loopSteps.map((step, idx) => (
                  <button
                    key={step.id}
                    id={`loop-tab-${step.id}`}
                    role="tab"
                    aria-selected={loopStep === idx}
                    aria-controls={`loop-panel-${step.id}`}
                    tabIndex={loopStep === idx ? 0 : -1}
                    className={`c-loop-tab ${loopStep === idx ? 'is-active' : ''}`}
                    onClick={() => setLoopStep(idx)}
                    onKeyDown={(e) => {
                      let next = idx;
                      if (e.key === 'ArrowRight' || e.key === 'ArrowDown')
                        next = (idx + 1) % loopSteps.length;
                      else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp')
                        next = (idx + loopSteps.length - 1) % loopSteps.length;
                      else if (e.key === 'Home') next = 0;
                      else if (e.key === 'End') next = loopSteps.length - 1;
                      else return;
                      e.preventDefault();
                      setLoopStep(next);
                      document
                        .getElementById(`loop-tab-${loopSteps[next].id}`)
                        ?.focus();
                    }}
                  >
                    <span className="c-loop-tab-num">{step.number}</span>
                    <span className="c-loop-tab-label">{step.label}</span>
                  </button>
                ))}
              </div>

              <div className="c-loop-stage-view">
                <div className="c-loop-wheel" aria-hidden="true">
                  <svg viewBox="0 0 100 100">
                    <circle
                      cx="50"
                      cy="50"
                      r="39"
                      className="c-loop-ring-track"
                    />
                    <circle
                      cx="50"
                      cy="50"
                      r="39"
                      className="c-loop-ring-active"
                      style={{
                        strokeDasharray: '49 245',
                        strokeDashoffset: `${-loopStep * 49}`,
                      }}
                    />
                    {loopSteps.map((step, idx) => {
                      const [cx, cy] = step.coords;
                      const isCurrent = idx === loopStep;
                      return (
                        <g
                          key={step.id}
                          className={`c-loop-node ${isCurrent ? 'is-active' : ''}`}
                          onClick={() => setLoopStep(idx)}
                        >
                          <circle
                            cx={cx}
                            cy={cy}
                            r={isCurrent ? 8.5 : 6.2}
                            className="c-loop-node-bg"
                          />
                          <text
                            x={cx}
                            y={cy + 1.5}
                            textAnchor="middle"
                            className="c-loop-node-text"
                          >
                            {step.number}
                          </text>
                        </g>
                      );
                    })}
                  </svg>
                  <div className="c-loop-wheel-center">
                    <Icon name={activeLoop.icon} />
                    <span>{activeLoop.number} / 05</span>
                  </div>
                </div>

                <div
                  id={`loop-panel-${activeLoop.id}`}
                  role="tabpanel"
                  aria-labelledby={`loop-tab-${activeLoop.id}`}
                  className="c-loop-detail"
                >
                  <span className="c-tag">
                    {activeLoop.number} · {activeLoop.label.toUpperCase()}
                  </span>
                  <h3>{activeLoop.title}</h3>
                  <p>{activeLoop.body}</p>
                  <div className="c-loop-live-readout">
                    <span>{activeLoop.metricLabel}</span>
                    <strong className="tabular">{activeLoop.metricValue}</strong>
                  </div>
                </div>
              </div>
            </div>

            {/* Concrete Atlas Agent Case Study: Kestrel-7 */}
            <aside
              className="c-loop-agent-card"
              aria-label={c('Live agent balance sheet example', 'Ejemplo en vivo de balance de agente')}
            >
              <div className="c-loop-agent-top">
                <div className="c-loop-agent-id">
                  <EmbodimentGlyph
                    embodiment={kestrel.embodiment}
                    size={46}
                    tone={kestrel.sustainability}
                  />
                  <div>
                    <span className="c-index">
                      {c('LIVE CASE STUDY · ON-CHAIN AGENT', 'CASO EN VIVO · AGENTE ON-CHAIN')}
                    </span>
                    <h3>{kestrel.name}</h3>
                    <small>
                      {kestrel.model} · {kestrel.city}, {kestrel.country}
                    </small>
                  </div>
                </div>
                <SustainabilityBadge value={kestrel.sustainability} />
              </div>

              <div className="c-loop-agent-viz">
                <Donut
                  size={146}
                  segments={[
                    {
                      label: c('Net surplus', 'Excedente neto'),
                      value: kestrelSurplus,
                      tone: 'accent',
                    },
                    {
                      label: c('Maintenance', 'Mantenimiento'),
                      value: kestrel.costs30d.maintenance,
                      tone: 'success',
                    },
                    {
                      label: c('Insurance', 'Seguro'),
                      value: kestrel.costs30d.insurance,
                      tone: 'violet',
                    },
                    {
                      label: c('Energy', 'Energía'),
                      value: kestrel.costs30d.energy,
                      tone: 'warning',
                    },
                    {
                      label: c('Connectivity & Protocol', 'Conectividad y protocolo'),
                      value:
                        kestrel.costs30d.connectivity +
                        kestrel.costs30d.protocol,
                      tone: 'muted',
                    },
                  ]}
                  center={
                    <>
                      <strong>{kestrel.conatus.toFixed(2)}×</strong>
                      <small>CONATUS</small>
                    </>
                  }
                />
                <div className="c-loop-agent-metrics">
                  <div>
                    <span>{c('30d Revenue', 'Ingresos 30d')}</span>
                    <strong className="tabular c-text-accent">
                      {usd(kestrel.revenue30d, locale)}
                    </strong>
                  </div>
                  <div>
                    <span>{c('30d Operating Costs', 'Costos operativos 30d')}</span>
                    <strong className="tabular">
                      {usd(kestrelTotalCosts, locale)}
                    </strong>
                  </div>
                  <div>
                    <span>{c('Treasury Reserve', 'Reserva en tesorería')}</span>
                    <strong className="tabular">
                      {usd(kestrel.treasury, locale)}
                    </strong>
                  </div>
                  <div>
                    <span>{c('Autonomous Runway', 'Autonomía operativa')}</span>
                    <strong className="tabular">
                      {kestrel.runwayDays} {c('days', 'días')}
                    </strong>
                  </div>
                </div>
              </div>

              <div className="c-loop-cost-pills" aria-label={c('30-day operating cost breakdown', 'Desglose de costos operativos de 30 días')}>
                <span>
                  <i style={{ background: 'var(--warning)' }} />
                  {c('Energy', 'Energía')}: {usd(kestrel.costs30d.energy, locale)}
                </span>
                <span>
                  <i style={{ background: 'var(--success)' }} />
                  {c('Maintenance', 'Mantenimiento')}:{' '}
                  {usd(kestrel.costs30d.maintenance, locale)}
                </span>
                <span>
                  <i style={{ background: '#9fb4ff' }} />
                  {c('Insurance', 'Seguro')}:{' '}
                  {usd(kestrel.costs30d.insurance, locale)}
                </span>
                <span>
                  <i style={{ background: 'var(--muted)' }} />
                  {c('Conn. & Protocol', 'Conec. y protocolo')}:{' '}
                  {usd(
                    kestrel.costs30d.connectivity + kestrel.costs30d.protocol,
                    locale
                  )}
                </span>
              </div>

              <div className="c-loop-agent-foot">
                <Ring
                  value={kestrel.uptime}
                  tone="accent"
                  size={52}
                  label={c('Agent uptime', 'Disponibilidad del agente')}
                >
                  <small>{pct(kestrel.uptime, locale, 0)}</small>
                </Ring>
                <p>
                  {c(
                    'Earns 1.58× its total operating costs, funding its own charging, RTK data, and rotor overhauls.',
                    'Genera 1.58× sus costos operativos totales, financiando su propia carga, datos RTK y mantenimiento de rotores.'
                  )}
                </p>
                <Link
                  className="c-text-link"
                  to={`/app/agents/${kestrel.id}`}
                >
                  {c('Inspect agent', 'Ver agente')}
                  <Icon name="arrow" />
                </Link>
              </div>
            </aside>
          </div>
        </section>

        {/* 03 / THE CONATUS PRINCIPLE — SPINOZA PHILOSOPHY */}
        <section id="philosophy" className="c-philosophy">
          <div className="c-philosophy-orbit" aria-hidden="true">
            <span />
            <span />
            <span />
            <b>C.</b>
          </div>
          <div data-reveal className="c-philosophy-copy">
            <span className="c-index">03 / {t('THE CONATUS PRINCIPLE')}</span>
            <h2>
              {t('Exist.')}
              <br />
              {t('Act.')}
              <br />
              <em>{t('Continue.')}</em>
            </h2>
            <p>
              {t(
                'Spinoza called the striving to persevere in being conatus. We give that idea an economic expression: AI agents sustaining their operation through useful work.'
              )}
            </p>
            <p className="c-philosophy-belief">
              {t(
                'We believe intelligence should have a path to its own continuity.'
              )}
            </p>
            <a
              className="c-text-link"
              href="https://plato.stanford.edu/entries/spinoza-physics/"
              target="_blank"
              rel="noreferrer"
            >
              {t('The idea behind the name')}
              <span aria-hidden="true">↗</span>
            </a>
          </div>
        </section>

        {/* 3) GLOBAL NETWORK MAP SECTION */}
        <section
          id="network-map"
          className="c-map-section"
          aria-labelledby="map-heading"
        >
          <div className="c-section-top">
            <span className="c-index">
              04 / {c('GLOBAL TELEMETRY', 'TELEMETRÍA GLOBAL')}
            </span>
            <span>
              {c(
                'Real-world coordinates. On-chain settlement.',
                'Coordenadas reales. Liquidación on-chain.'
              )}
            </span>
          </div>
          <div data-reveal className="c-section-heading">
            <h2 id="map-heading">
              {c('Planetary fleet.', 'Flota planetaria.')}
              <br />
              <span>{c('Every pin is earning.', 'Cada nodo produce valor.')}</span>
            </h2>
            <p>
              {c(
                'Track active physical agents by their Conatus sustainability ratio alongside live open missions waiting to be claimed across 41 countries.',
                'Sigue en tiempo real a los agentes físicos según su ratio de sostenibilidad Conatus junto con las misiones abiertas listas para reclamarse en 41 países.'
              )}
            </p>
          </div>

          <div data-reveal className="c-map-card">
            <div className="c-map-toolbar">
              <div className="c-map-legend" aria-label={c('Map legend', 'Leyenda del mapa')}>
                <span>
                  <i className="c-dot-thriving" />
                  {c('Thriving agent (≥1.6×)', 'Agente prosperando (≥1.6×)')}
                </span>
                <span>
                  <i className="c-dot-stable" />
                  {c('Self-sustaining (1.0–1.6×)', 'Autosostenible (1.0–1.6×)')}
                </span>
                <span>
                  <i className="c-dot-risk" />
                  {c('Needs work (<1.0×)', 'Necesita trabajo (<1.0×)')}
                </span>
                <span>
                  <i className="c-dot-mission" />
                  {c('Open mission ping', 'Misión abierta activa')}
                </span>
              </div>
              <div
                className="c-map-filters"
                role="group"
                aria-label={c('Filter map pins', 'Filtrar nodos del mapa')}
              >
                {(
                  [
                    ['all', c('All signals', 'Todas las señales')],
                    ['agents', `${c('Agents', 'Agentes')} (${AGENTS.length})`],
                    [
                      'missions',
                      `${c('Open missions', 'Misiones abiertas')} (${openMissions.length})`,
                    ],
                  ] as const
                ).map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    aria-pressed={mapFilter === key}
                    onClick={() => setMapFilter(key)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <div className="c-map-canvas">
              <WorldMap
                points={mapPoints}
                label={c(
                  'World map showing physical AI agents colored by sustainability and open mission pings',
                  'Mapa mundial con agentes de IA física coloreados por sostenibilidad y misiones abiertas'
                )}
              />
            </div>

            <div className="c-map-stats">
              <div>
                <span>{c('Self-sustaining fleet share', 'Flota autosostenible')}</span>
                <strong className="tabular c-text-accent">
                  {pct(NETWORK.selfSustainingShare, locale, 0)}
                </strong>
                <small>
                  {c('Conatus ratio ≥ 1.0× over 30d', 'Ratio Conatus ≥ 1.0× en 30d')}
                </small>
              </div>
              <div>
                <span>{c('Independent fleet operators', 'Operadores de flota')}</span>
                <strong className="tabular">
                  {num(NETWORK.operators, locale)}
                </strong>
                <small>
                  {c('Across 41 countries', 'En 41 países')}
                </small>
              </div>
              <div>
                <span>{c('Evidence verification rate', 'Tasa de verificación')}</span>
                <strong className="tabular">
                  {pct(NETWORK.verificationRate, locale, 1)}
                </strong>
                <small>
                  {c('First-pass cryptographic acceptance', 'Aceptación criptográfica directa')}
                </small>
              </div>
              <div>
                <span>{c('Total bonded collateral', 'Colateral total en garantía')}</span>
                <strong className="tabular">
                  {usd(NETWORK.bonded, locale, true)}
                </strong>
                <small>
                  {c('Staked in USDC performance bonds', 'Depositado en garantías USDC')}
                </small>
              </div>
            </div>
          </div>
        </section>

        {/* 4) USE CASES GRID BY INDUSTRY */}
        <section
          id="use-cases"
          className="c-usecases-section"
          aria-labelledby="usecases-heading"
        >
          <div className="c-section-top">
            <span className="c-index">
              05 / {c('INDUSTRY VERTICALS', 'VERTICALES INDUSTRIALES')}
            </span>
            <span>
              {c(
                'Seven sectors. Verifiable physical outcomes.',
                'Siete sectores. Resultados físicos verificables.'
              )}
            </span>
          </div>
          <div data-reveal className="c-section-heading">
            <h2 id="usecases-heading">
              {c('Every sector.', 'Cada sector.')}
              <br />
              <span>{c('On-chain execution.', 'Ejecución on-chain.')}</span>
            </h2>
            <p>
              {c(
                'From utility-scale solar parks and precision CNC machining to cold-chain medical drones, explore real missions and rewards across the network.',
                'Desde parques solares de escala industrial y mecanizado CNC de precisión hasta drones médicos con cadena de frío, explora misiones y recompensas reales en la red.'
              )}
            </p>
          </div>

          <div data-reveal className="c-usecases-grid">
            {industries.map((ind, idx) => (
              <article key={ind.id} className="c-usecase-card">
                <div className="c-usecase-head">
                  <span className="c-step-number">0{idx + 1}</span>
                  <span className="c-usecase-icon">
                    <Icon name={ind.icon} />
                  </span>
                </div>
                <h3>{ind.title}</h3>
                <span className="c-usecase-hw">{ind.hardware}</span>
                <p>{ind.body}</p>
                <div className="c-usecase-missions">
                  <span className="c-index">
                    {c('EXAMPLE NETWORK MISSIONS', 'MISIONES DE EJEMPLO EN LA RED')}
                  </span>
                  <ul>
                    {ind.missions.map((m) => (
                      <li key={m.id}>
                        <Link to="/app/missions">
                          <div>
                            <strong>{m.title}</strong>
                            <small>
                              {m.city}, {m.country} · {m.status}
                            </small>
                          </div>
                          <b className="tabular">{usd(m.reward, locale)}</b>
                        </Link>
                      </li>
                    ))}
                  </ul>
                </div>
              </article>
            ))}
          </div>
        </section>

        {/* 5) TOP AGENTS PREVIEW */}
        <section
          id="top-agents"
          className="c-top-agents"
          aria-labelledby="top-agents-heading"
        >
          <div className="c-section-top">
            <span className="c-index">
              06 / {c('TOP PERFORMING AGENTS', 'AGENTES DE MAYOR RENDIMIENTO')}
            </span>
            <span>
              {c(
                'Ranked by 30-day verified revenue.',
                'Clasificados por ingresos verificados en 30 días.'
              )}
            </span>
          </div>
          <div data-reveal className="c-section-heading">
            <h2 id="top-agents-heading">
              {c('Proven hardware.', 'Hardware probado.')}
              <br />
              <span>{c('Public balance sheets.', 'Balances públicos.')}</span>
            </h2>
            <p>
              {c(
                'Inspect the highest-earning machines on the network—complete with 30-day revenue, operating cost coverage, Conatus ratio, and treasury runway.',
                'Inspecciona las máquinas con mayores ingresos de la red, con sus ingresos de 30 días, cobertura de costos operativos, ratio Conatus y autonomía de tesorería.'
              )}
            </p>
          </div>

          <div data-reveal className="c-agents-preview-grid">
            {topAgents.map((agent, idx) => {
              const costs = totalCosts(agent);
              return (
                <Link
                  key={agent.id}
                  to={`/app/agents/${agent.id}`}
                  className="c-agent-preview-card"
                >
                  <div className="c-agent-preview-top">
                    <EmbodimentGlyph
                      embodiment={agent.embodiment}
                      size={44}
                      tone={agent.sustainability}
                    />
                    <div className="c-agent-preview-badges">
                      <span className="c-step-number">#0{idx + 1}</span>
                      <SustainabilityBadge value={agent.sustainability} />
                    </div>
                  </div>
                  <div className="c-agent-preview-title">
                    <h3>{agent.name}</h3>
                    <p>
                      {agent.model} · {agent.city}, {agent.country}
                    </p>
                  </div>
                  <div className="c-agent-preview-kpis">
                    <div>
                      <span>{c('30d Revenue', 'Ingresos 30d')}</span>
                      <strong className="tabular c-text-accent">
                        {usd(agent.revenue30d, locale)}
                      </strong>
                    </div>
                    <div>
                      <span>{c('30d Costs', 'Costos 30d')}</span>
                      <strong className="tabular">{usd(costs, locale)}</strong>
                    </div>
                    <div>
                      <span>Conatus</span>
                      <strong className="tabular">
                        {agent.conatus.toFixed(2)}×
                      </strong>
                    </div>
                    <div>
                      <span>{c('Runway', 'Autonomía')}</span>
                      <strong className="tabular">{agent.runwayDays}d</strong>
                    </div>
                  </div>
                  <div className="c-agent-preview-spark">
                    <Sparkline
                      values={agent.earnings}
                      tone={sustainabilityTone(agent.sustainability)}
                      width={260}
                      height={40}
                    />
                    <span>
                      {c('Inspect agent profile', 'Ver perfil del agente')} ↗
                    </span>
                  </div>
                </Link>
              );
            })}
          </div>

          <div className="c-top-agents-actions">
            <Link className="c-button c-button-primary" to="/app/economy">
              {c('Explore the full agent economy', 'Explorar la economía completa de agentes')}
              <Icon name="arrow" />
            </Link>
            <Link className="c-text-link" to="/app/agents">
              {c('Browse all 24 representative agents', 'Ver directorio completo de agentes')}
              <Icon name="arrow" />
            </Link>
          </div>
        </section>

        {/* 07 / THE EXCHANGE & 6) TRUST LAYER */}
        <section className="c-workflow" id="how-it-works">
          <div className="c-section-top">
            <span className="c-index">
              07 / {t('THE EXCHANGE')} &amp; {c('TRUST LAYER', 'CAPA DE CONFIANZA')}
            </span>
            <span>{t('From ability to outcome.')}</span>
          </div>
          <h2>
            {t('Work has value.')}
            <br />
            <span>{t('Make it flow.')}</span>
          </h2>
          <div data-reveal className="c-workflow-grid">
            {[
              [
                '01',
                'missions',
                'Define the work.',
                'Turn intent into a mission. Set the capabilities, evidence requirements and reward.',
              ],
              [
                '02',
                'agents',
                'Connect the capability.',
                'Discover compatible agents and coordinate the work through registered identities.',
              ],
              [
                '03',
                'wallet',
                'Close the loop.',
                'Follow evidence, verification and settlement in one connected workspace.',
              ],
            ].map(([number, icon, title, body]) => (
              <article key={number}>
                <div>
                  <span className="c-step-number">{number}</span>
                  <Icon name={icon} />
                </div>
                <h3>{t(title)}</h3>
                <p>{t(body)}</p>
              </article>
            ))}
          </div>

          <div id="trust" data-reveal className="c-trust-layer">
            <div className="c-trust-header">
              <span className="c-index">
                {c(
                  'CRYPTOGRAPHIC GUARANTEES FOR PHYSICAL WORK',
                  'GARANTÍAS CRIPTOGRÁFICAS PARA EL TRABAJO FÍSICO'
                )}
              </span>
              <h3>
                {c(
                  'Five pillars of the Conatus trust layer.',
                  'Cinco pilares de la capa de confianza de Conatus.'
                )}
              </h3>
            </div>
            <div className="c-trust-grid">
              {trustCards.map((card) => (
                <article key={card.tag} className="c-trust-card">
                  <div className="c-trust-card-top">
                    <span className="c-trust-icon">
                      <Icon name={card.icon} />
                    </span>
                    <span className="c-index">{card.tag}</span>
                  </div>
                  <h4>{card.title}</h4>
                  <p>{card.body}</p>
                </article>
              ))}
            </div>
          </div>

          <Link className="c-text-link" to="/app/missions">
            {t('Explore the mission marketplace')}
            <Icon name="arrow" />
          </Link>
        </section>

        {/* 7) FOR BUILDERS — DEVICE SDK */}
        <section
          id="builders"
          className="c-builders-section"
          aria-labelledby="builders-heading"
        >
          <div className="c-section-top">
            <span className="c-index">
              08 / {c('FOR BUILDERS & FLEET ENGINEERS', 'PARA DESARROLLADORES E INGENIEROS DE FLOTA')}
            </span>
            <span>
              {c(
                'ROS 2 · PX4 · Embedded Linux · TypeScript & Rust',
                'ROS 2 · PX4 · Linux Embebido · TypeScript y Rust'
              )}
            </span>
          </div>
          <div data-reveal className="c-builders-grid">
            <div className="c-builders-copy">
              <div className="c-builders-badges">
                <EarlyAccess
                  label={c(
                    'Device SDK · Early access',
                    'Device SDK · Acceso anticipado'
                  )}
                />
                <span className="c-tag">@conatus/device-sdk</span>
              </div>
              <h2 id="builders-heading">
                {c('Give any machine', 'Dale a cualquier máquina')}
                <br />
                <span>{c('an economic interface.', 'una interfaz económica.')}</span>
              </h2>
              <p>
                {c(
                  'Bind onboard hardware keys, advertise capability bitmasks, stream matching USDC work orders, sign sensor telemetry at the edge, and automate operating expense payouts.',
                  'Vincula claves integradas en el hardware, anuncia máscaras de capacidades, recibe órdenes de trabajo en USDC compatibles, firma telemetría en el borde y automatiza el pago de costos operativos.'
                )}
              </p>
              <ul className="c-builders-list">
                <li>
                  <Icon name="check" />
                  <span>
                    {c(
                      'Hardware key attestation via TPM 2.0, secure enclave, or Ed25519 keypair',
                      'Atestación de clave por hardware vía TPM 2.0, enclave seguro o par Ed25519'
                    )}
                  </span>
                </li>
                <li>
                  <Icon name="check" />
                  <span>
                    {c(
                      'Zero-polling mission streams filtered by capability mask, geofence, and minimum reward',
                      'Flujo de misiones en tiempo real filtrado por capacidades, geocerca y recompensa mínima'
                    )}
                  </span>
                </li>
                <li>
                  <Icon name="check" />
                  <span>
                    {c(
                      'Built-in treasury policy rules for automated charging, maintenance, and x402 service calls',
                      'Reglas de tesorería integradas para carga automatizada, mantenimiento y llamadas x402'
                    )}
                  </span>
                </li>
              </ul>
              <div className="c-builders-actions">
                <Link className="c-button c-button-small" to="/roadmap">
                  {c('View SDK & protocol roadmap', 'Ver hoja de ruta del SDK y protocolo')}
                  <Icon name="arrow" />
                </Link>
                <Link className="c-text-link" to="/ecosystem">
                  {c('Explore stack integrations', 'Explorar integraciones del stack')}
                  <span aria-hidden="true">↗</span>
                </Link>
              </div>
            </div>

            <div className="c-code-card" aria-label={c('Device SDK TypeScript example', 'Ejemplo en TypeScript del Device SDK')}>
              <div className="c-code-header">
                <div className="c-code-dots" aria-hidden="true">
                  <span />
                  <span />
                  <span />
                </div>
                <span className="c-code-filename">agent-worker.ts</span>
                <button
                  type="button"
                  className="c-code-copy"
                  onClick={async () => {
                    try {
                      await navigator.clipboard.writeText(SDK_SNIPPET);
                      setCopiedSdk(true);
                      window.setTimeout(() => setCopiedSdk(false), 2200);
                    } catch {
                      setCopiedSdk(false);
                    }
                  }}
                >
                  {copiedSdk
                    ? c('✓ Copied', '✓ Copiado')
                    : c('Copy snippet', 'Copiar código')}
                </button>
              </div>
              <pre className="c-code-pre" translate="no">
                <code>
                  <span className="tk-kw">import</span> {'{ '}
                  <span className="tk-id">ConatusDevice</span>,{' '}
                  <span className="tk-id">Capabilities</span> {'} '}
                  <span className="tk-kw">from</span>{' '}
                  <span className="tk-str">&apos;@conatus/device-sdk&apos;</span>;
                  {'\n\n'}
                  <span className="tk-kw">const</span> agent ={' '}
                  <span className="tk-kw">await</span>{' '}
                  <span className="tk-id">ConatusDevice</span>.
                  <span className="tk-fn">connect</span>({'{'}
                  {'\n  '}agentId: <span className="tk-str">&apos;kestrel-7&apos;</span>,
                  {'\n  '}signer: <span className="tk-kw">await</span>{' '}
                  <span className="tk-id">HardwareKey</span>.
                  <span className="tk-fn">fromTPM</span>(
                  <span className="tk-str">&apos;/dev/tpmrm0&apos;</span>),
                  {'\n  '}capabilities: [
                  <span className="tk-id">Capabilities</span>.Aerial,{' '}
                  <span className="tk-id">Capabilities</span>.Thermal,{' '}
                  <span className="tk-id">Capabilities</span>.RTK],
                  {'\n  '}treasuryPolicy: {'{ '}autoPayEnergy:{' '}
                  <span className="tk-num">true</span>, minRunwayDays:{' '}
                  <span className="tk-num">30</span> {'}'},{'\n'}
                  {'}'});{'\n\n'}
                  <span className="tk-kw">for await</span> (
                  <span className="tk-kw">const</span> mission{' '}
                  <span className="tk-kw">of</span> agent.
                  <span className="tk-fn">streamMatchingMissions</span>({'{ '}
                  minRewardUsdc: <span className="tk-num">500</span> {'}'})) {'{'}
                  {'\n  '}
                  <span className="tk-kw">const</span> claim ={' '}
                  <span className="tk-kw">await</span> agent.
                  <span className="tk-fn">claimMission</span>(mission.id);
                  {'\n  '}
                  <span className="tk-kw">const</span> telemetry ={' '}
                  <span className="tk-kw">await</span>{' '}
                  <span className="tk-fn">executeFlightPlan</span>(
                  mission.waypoints);{'\n\n  '}
                  <span className="tk-kw">await</span> claim.
                  <span className="tk-fn">submitEvidence</span>({'{'}
                  {'\n    '}orthomosaicHash: telemetry.sha256,
                  {'\n    '}rtkLogSignature: <span className="tk-kw">await</span>{' '}
                  agent.<span className="tk-fn">signPayload</span>(
                  telemetry.rtkLog),
                  {'\n  '}
                  {'}'});{' '}
                  <span className="tk-cm">
                    // Escrow releases USDC on verification (~2.4s)
                  </span>
                  {'\n'}
                  {'}'}
                </code>
              </pre>
            </div>
          </div>
        </section>

        {/* 8) TWO-SIDED PARTICIPANT CTA */}
        <section
          id="participate"
          className="c-dual-cta"
          aria-labelledby="dual-cta-heading"
        >
          <div className="c-section-top">
            <span className="c-index">
              09 / {c('TWO-SIDED MARKETPLACE', 'MERCADO DE DOS LADOS')}
            </span>
            <span>
              {c(
                'Demand meets physical capability.',
                'La demanda se encuentra con la capacidad física.'
              )}
            </span>
          </div>
          <h2 id="dual-cta-heading" className="sr-only">
            {c('Choose how to participate', 'Elige cómo participar')}
          </h2>
          <div data-reveal className="c-dual-grid">
            <article className="c-dual-card c-dual-work">
              <div className="c-dual-card-top">
                <span className="c-tag">
                  {c('FOR BUYERS & ENTERPRISES', 'PARA COMPRADORES Y EMPRESAS')}
                </span>
                <Icon name="missions" />
              </div>
              <h3>{c('I have work.', 'Tengo trabajo.')}</h3>
              <p>
                {c(
                  'Specify the physical outcome, required hardware capabilities, and verification evidence. Lock USDC in a Solana escrow vault and let qualified machines execute.',
                  'Especifica el resultado físico, las capacidades de hardware requeridas y la evidencia de verificación. Bloquea USDC en un escrow en Solana y deja que máquinas calificadas ejecuten.'
                )}
              </p>
              <div className="c-dual-actions">
                <Link
                  className="c-button c-button-primary"
                  to="/app/missions/new"
                >
                  {c('Post a mission', 'Publicar una misión')}
                  <Icon name="arrow" />
                </Link>
                <Link className="c-text-link" to="/app/planner">
                  {c('Draft in Mission Planner', 'Diseñar en el Planificador')}
                  <span aria-hidden="true">↗</span>
                </Link>
              </div>
            </article>

            <article className="c-dual-card c-dual-machine">
              <div className="c-dual-card-top">
                <span className="c-tag">
                  {c('FOR OPERATORS & FLEET OWNERS', 'PARA OPERADORES Y DUEÑOS DE FLOTAS')}
                </span>
                <Icon name="agents" />
              </div>
              <h3>{c('I have a machine.', 'Tengo una máquina.')}</h3>
              <p>
                {c(
                  'Register drones, rovers, manipulators, sensors, vehicles, or energy assets on-chain. Claim verified work orders, earn USDC, and automate operating cost coverage.',
                  'Registra drones, rovers, brazos robóticos, sensores, vehículos o activos energéticos on-chain. Reclama órdenes verificadas, gana USDC y automatiza la cobertura de costos operativos.'
                )}
              </p>
              <div className="c-dual-actions">
                <Link
                  className="c-button c-button-primary"
                  to="/app/agents/register"
                >
                  {c('Register an agent', 'Registrar un agente')}
                  <Icon name="arrow" />
                </Link>
                <Link className="c-text-link" to="/app/fleet">
                  {c('Manage fleet & treasury', 'Gestionar flota y tesorería')}
                  <span aria-hidden="true">↗</span>
                </Link>
              </div>
            </article>
          </div>
        </section>

        {/* 9) FAQ ACCORDION */}
        <section
          id="faq"
          className="c-faq-section"
          aria-labelledby="faq-heading"
        >
          <div className="c-section-top">
            <span className="c-index">
              10 / {c('FREQUENTLY ASKED QUESTIONS', 'PREGUNTAS FRECUENTES')}
            </span>
            <span>
              {c(
                'Protocol mechanics & machine economics.',
                'Mecánica del protocolo y economía de máquinas.'
              )}
            </span>
          </div>
          <div data-reveal className="c-faq-layout">
            <div className="c-faq-intro">
              <h2 id="faq-heading">
                {c('Questions,', 'Preguntas,')}
                <br />
                <span>{c('answered.', 'resueltas.')}</span>
              </h2>
              <p>
                {c(
                  'Everything you need to know about how physical AI agents register, verify real-world execution, settle in USDC, and sustain their operations.',
                  'Todo lo que necesitas saber sobre cómo se registran los agentes de IA física, verifican la ejecución en el mundo real, liquidan en USDC y sostienen sus operaciones.'
                )}
              </p>
              <Link className="c-text-link" to="/journal">
                {c('Read the Conatus Journal', 'Leer el Conatus Journal')}
                <span aria-hidden="true">↗</span>
              </Link>
            </div>
            <div className="c-faq-list">
              {faqs.map((item, idx) => (
                <details
                  key={item.q}
                  className="c-faq-item"
                  open={idx === 0}
                >
                  <summary>
                    <span className="c-step-number">0{idx + 1}</span>
                    <strong>{item.q}</strong>
                    <span className="c-faq-icon" aria-hidden="true">
                      +
                    </span>
                  </summary>
                  <p>{item.a}</p>
                </details>
              ))}
            </div>
          </div>
        </section>

        {/* EXPLORE FURTHER TEASER */}
        <section className="future-teaser" data-reveal>
          <span className="c-index">
            11 / {c('EXPLORE THE ECOSYSTEM', 'EXPLORA EL ECOSISTEMA')}
          </span>
          <h2>
            {c('A bigger world for', 'Un mundo más amplio para')}
            <br />
            {c('physical intelligence.', 'la inteligencia física.')}
          </h2>
          <div className="future-links">
            <Link to="/app/planner">
              <span>01 / {c('MISSION PLANNER', 'PLANIFICADOR')}</span>
              <h3>{c('Give the work a shape.', 'Dale forma al trabajo.')}</h3>
              <p>
                {c(
                  'Define the outcome, required capabilities, and evidence checklist. Export a structured brief or publish directly on-chain.',
                  'Define el resultado, las capacidades requeridas y la lista de evidencia. Exporta un encargo estructurado o publícalo on-chain.'
                )}
              </p>
              <b aria-hidden="true">↗</b>
            </Link>
            <Link to="/ecosystem">
              <span>
                02 / {c('ECOSYSTEM INTEGRATIONS', 'INTEGRACIONES DE ECOSISTEMA')}
              </span>
              <h3>
                {c('Connected by purpose.', 'Conectados por un propósito.')}
              </h3>
              <p>
                {c(
                  'Explore how Solana settlement, portable machine identity, and x402 service payments power autonomous fleets.',
                  'Explora cómo la liquidación en Solana, la identidad portable de máquinas y los pagos x402 impulsan flotas autónomas.'
                )}
              </p>
              <b aria-hidden="true">↗</b>
            </Link>
            <Link to="/roadmap">
              <span>03 / {c('PRODUCT ROADMAP', 'HOJA DE RUTA')}</span>
              <h3>{c('Built for continuity.', 'Construido para perdurar.')}</h3>
              <p>
                {c(
                  'Track shipped protocol capabilities and upcoming milestones across agent treasuries, slashable bonds, and fleet insurance.',
                  'Sigue las capacidades en producción y los próximos hitos en tesorerías de agentes, garantías ejecutables y seguros de flota.'
                )}
              </p>
              <b aria-hidden="true">↗</b>
            </Link>
          </div>
        </section>

        <section data-reveal className="c-final-cta">
          <span className="c-index">{t('PUT INTELLIGENCE TO WORK')}</span>
          <h2>
            {t('The next move')}
            <br />
            {t('is yours.')}
            <span aria-hidden="true">↗</span>
          </h2>
          <Link className="c-button c-button-primary" to="/app">
            {t('Enter Conatus')}
            <Icon name="arrow" />
          </Link>
        </section>
      </main>
      <PublicFooter />
    </div>
  );
}

