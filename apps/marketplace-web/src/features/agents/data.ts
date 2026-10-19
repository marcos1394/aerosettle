import type { AgentFilters } from '@aerosettle/marketplace-sdk';
import { PublicKey, type Connection } from '@solana/web3.js';
import { api, verifyMeta, verifyNetwork } from '../../app/api';
import type {
  AtlasAgent,
  Embodiment,
  OperationalState,
} from '../../app/atlas';
import { CAPABILITIES, short } from '../../app/config';
import { decodeAccount } from '../../app/readAccount';
import type { Tone } from '../../components/ui/viz';

export interface MarketAgent extends AtlasAgent {
  onChain?: boolean;
  rawStatus?: string;
}

export const EMBODIMENTS: readonly Embodiment[] = [
  'Drone',
  'Ugv',
  'Amr',
  'RobotArm',
  'Camera',
  'IotSensor',
  'Vehicle',
  'IndustrialMachine',
  'EdgeCompute',
  'EnergyAsset',
] as const;

export function embodimentLabel(
  embodiment: string,
  c: (en: string, es: string) => string
): string {
  switch (embodiment as Embodiment) {
    case 'Drone':
      return c('Aerial Drone', 'Dron aéreo');
    case 'Ugv':
      return c('Ground Rover (UGV)', 'Rover terrestre (UGV)');
    case 'Amr':
      return c('Mobile Robot (AMR)', 'Robot móvil (AMR)');
    case 'RobotArm':
      return c('Robotic Arm', 'Brazo robótico');
    case 'Camera':
      return c('Vision Node', 'Nodo de visión');
    case 'IotSensor':
      return c('Environmental Sensor', 'Sensor ambiental');
    case 'Vehicle':
      return c('Autonomous Vehicle', 'Vehículo autónomo');
    case 'IndustrialMachine':
      return c('Industrial Machine', 'Máquina industrial');
    case 'EdgeCompute':
      return c('Edge Compute Node', 'Nodo de cómputo Edge');
    case 'EnergyAsset':
      return c('Energy & Grid Asset', 'Activo energético');
    default:
      return embodiment;
  }
}

export function embodimentShortLabel(
  embodiment: string,
  c: (en: string, es: string) => string
): string {
  switch (embodiment as Embodiment) {
    case 'Drone':
      return c('Drones', 'Drones');
    case 'Ugv':
      return c('UGV Rovers', 'Rovers UGV');
    case 'Amr':
      return c('AMR Bots', 'Robots AMR');
    case 'RobotArm':
      return c('Robot Arms', 'Brazos robóticos');
    case 'Camera':
      return c('Vision', 'Visión');
    case 'IotSensor':
      return c('Sensors', 'Sensores');
    case 'Vehicle':
      return c('Vehicles', 'Vehículos');
    case 'IndustrialMachine':
      return c('Industrial', 'Industrial');
    case 'EdgeCompute':
      return c('Edge Compute', 'Cómputo Edge');
    case 'EnergyAsset':
      return c('Energy', 'Energía');
    default:
      return embodiment;
  }
}

export function stateMeta(
  state: OperationalState,
  c: (en: string, es: string) => string
): { label: string; tone: Tone } {
  switch (state) {
    case 'working':
      return { label: c('Executing mission', 'En misión'), tone: 'accent' };
    case 'available':
      return { label: c('Available now', 'Disponible'), tone: 'success' };
    case 'charging':
      return { label: c('Charging energy', 'Cargando energía'), tone: 'violet' };
    case 'maintenance':
      return { label: c('Maintenance cycle', 'En mantenimiento'), tone: 'warning' };
  }
}

export interface EmbodimentPreset {
  tagline: [string, string];
  defaultModel: string;
  defaultCapabilities: number[];
  defaultRate: number;
  defaultCosts: {
    energy: number;
    maintenance: number;
    insurance: number;
    connectivity: number;
  };
  defaultBond: number;
  specs: { label: [string, string]; value: [string, string] }[];
}

export const EMBODIMENT_PRESETS: Record<Embodiment, EmbodimentPreset> = {
  Drone: {
    tagline: ['Aerial survey, thermal inspection & rapid delivery', 'Inspección aérea, termografía y entrega rápida'],
    defaultModel: 'RTK survey quadrotor · 42 min flight',
    defaultCapabilities: [0, 2, 5, 6, 14, 15],
    defaultRate: 185,
    defaultCosts: { energy: 420, maintenance: 890, insurance: 760, connectivity: 190 },
    defaultBond: 1200,
    specs: [
      { label: ['Flight endurance', 'Autonomía de vuelo'], value: ['44 min · Hot-swap LiPo 6S', '44 min · LiPo 6S intercambiable'] },
      { label: ['Navigation & positioning', 'Navegación y posicionamiento'], value: ['Dual-band RTK GNSS (±1.2 cm)', 'GNSS RTK doble banda (±1.2 cm)'] },
      { label: ['Onboard compute', 'Cómputo a bordo'], value: ['NVIDIA Orin NX 16GB · 100 TOPS', 'NVIDIA Orin NX 16GB · 100 TOPS'] },
      { label: ['Cryptographic enclave', 'Enclave criptográfico'], value: ['ATECC608B Ed25519 hardware signer', 'Firmador hardware ATECC608B Ed25519'] },
      { label: ['Telemetry link', 'Enlace de telemetría'], value: ['5G Sub-6 + Iridium Certus fallback', '5G Sub-6 + respaldo Iridium Certus'] },
      { label: ['Ingress protection', 'Protección ambiental'], value: ['IP55 · -15 °C to 45 °C', 'IP55 · -15 °C a 45 °C'] },
    ],
  },
  Ugv: {
    tagline: ['All-terrain patrol, utility cleaning & field work', 'Patrullaje todoterreno, limpieza y campo'],
    defaultModel: 'All-terrain 4WD inspection rover',
    defaultCapabilities: [1, 3, 6, 8, 15],
    defaultRate: 160,
    defaultCosts: { energy: 480, maintenance: 840, insurance: 540, connectivity: 150 },
    defaultBond: 1000,
    specs: [
      { label: ['Runtime & battery', 'Autonomía y batería'], value: ['8.5 hrs · 3.8 kWh LiFePO₄', '8.5 h · 3.8 kWh LiFePO₄'] },
      { label: ['Perception stack', 'Sistema de percepción'], value: ['3D LiDAR + radiometric thermal', 'LiDAR 3D + cámara térmica radiométrica'] },
      { label: ['Onboard compute', 'Cómputo a bordo'], value: ['Jetson AGX Orin · 200 TOPS', 'Jetson AGX Orin · 200 TOPS'] },
      { label: ['Cryptographic enclave', 'Enclave criptográfico'], value: ['TPM 2.0 + Ed25519 secure key slot', 'TPM 2.0 + ranura segura Ed25519'] },
      { label: ['Payload capacity', 'Capacidad de carga'], value: ['65 kg modular deck', 'Plataforma modular de 65 kg'] },
      { label: ['Ingress protection', 'Protección ambiental'], value: ['IP67 sealed chassis', 'Chasis sellado IP67'] },
    ],
  },
  Amr: {
    tagline: ['Warehouse fulfillment, hospital loops & urban courier', 'Logística intraplanta, hospitales y última milla'],
    defaultModel: 'Autonomous last-mile & warehouse courier',
    defaultCapabilities: [1, 11, 5, 8, 9],
    defaultRate: 95,
    defaultCosts: { energy: 310, maintenance: 540, insurance: 350, connectivity: 120 },
    defaultBond: 750,
    specs: [
      { label: ['Shift endurance', 'Autonomía por turno'], value: ['12 hrs · Inductive dock charging', '12 h · Carga inductiva en base'] },
      { label: ['Navigation', 'Navegación'], value: ['Visual-Inertial SLAM + 360° LiDAR', 'SLAM visual-inercial + LiDAR 360°'] },
      { label: ['Compartment capacity', 'Capacidad de compartimento'], value: ['45 kg climate-monitored bay', 'Bahía climatizada de 45 kg'] },
      { label: ['Cryptographic enclave', 'Enclave criptográfico'], value: ['NXP SE050 hardware root of trust', 'Raíz de confianza hardware NXP SE050'] },
      { label: ['Safety certification', 'Certificación de seguridad'], value: ['ISO 3691-4 PLd compliant', 'Cumple ISO 3691-4 PLd'] },
      { label: ['Connectivity', 'Conectividad'], value: ['Wi-Fi 6E + Dual-SIM 5G', 'Wi-Fi 6E + 5G Dual-SIM'] },
    ],
  },
  RobotArm: {
    tagline: ['Precision assembly, welding & automated QA cells', 'Ensamblaje de precisión, soldadura y celdas QA'],
    defaultModel: '6-axis force-torque assembly cell',
    defaultCapabilities: [10, 8, 9, 15],
    defaultRate: 240,
    defaultCosts: { energy: 920, maintenance: 1100, insurance: 520, connectivity: 130 },
    defaultBond: 1600,
    specs: [
      { label: ['Repeatability', 'Repetibilidad'], value: ['±0.02 mm · 6 degrees of freedom', '±0.02 mm · 6 grados de libertad'] },
      { label: ['Reach & payload', 'Alcance y carga'], value: ['1,300 mm reach · 16 kg wrist payload', 'Alcance 1,300 mm · 16 kg en muñeca'] },
      { label: ['Force sensing', 'Sensado de fuerza'], value: ['6-DOF wrist torque transducer', 'Transductor de par 6-DOF en muñeca'] },
      { label: ['Vision QA', 'Visión de control de calidad'], value: ['5 MP coaxial telecentric camera', 'Cámara telecéntrica coaxial de 5 MP'] },
      { label: ['Cryptographic enclave', 'Enclave criptográfico'], value: ['Industrial HSM PLC module', 'Módulo HSM industrial en PLC'] },
      { label: ['Power draw', 'Consumo eléctrico'], value: ['1.4 kW average · 400V 3-phase', '1.4 kW promedio · 400V trifásico'] },
    ],
  },
  Camera: {
    tagline: ['Fixed optical/thermal perimeter & analytics nodes', 'Nodos fijos de visión óptica/térmica y analítica'],
    defaultModel: 'Smart thermal & RGB vision sentry',
    defaultCapabilities: [2, 3, 8, 9, 15],
    defaultRate: 45,
    defaultCosts: { energy: 65, maintenance: 95, insurance: 60, connectivity: 130 },
    defaultBond: 350,
    specs: [
      { label: ['Optical sensor', 'Sensor óptico'], value: ['4K Sony Starvis 2 + LWIR 640×512', '4K Sony Starvis 2 + LWIR 640×512'] },
      { label: ['Edge AI accelerator', 'Acelerador IA Edge'], value: ['Hailo-8 26 TOPS low-power NPU', 'NPU Hailo-8 26 TOPS bajo consumo'] },
      { label: ['Privacy guarantee', 'Garantía de privacidad'], value: ['In-silicon face/plate redaction', 'Anonimización en silicio de rostros/placas'] },
      { label: ['Cryptographic enclave', 'Enclave criptográfico'], value: ['Signed frame hashes (C2PA + Ed25519)', 'Hashes de fotograma firmados (C2PA + Ed25519)'] },
      { label: ['Power supply', 'Alimentación'], value: ['PoE++ (802.3bt) + 40W solar buffer', 'PoE++ (802.3bt) + respaldo solar 40W'] },
      { label: ['Enclosure', 'Gabinete'], value: ['IP68 weatherproof anodized housing', 'Carcasa anodizada IP68'] },
    ],
  },
  IotSensor: {
    tagline: ['Signed environmental, marine & air-quality telemetry', 'Telemetría ambiental, marina y de calidad del aire'],
    defaultModel: 'Environmental mesh & telemetry station',
    defaultCapabilities: [7, 5, 15],
    defaultRate: 30,
    defaultCosts: { energy: 35, maintenance: 75, insurance: 30, connectivity: 115 },
    defaultBond: 250,
    specs: [
      { label: ['Sensor array', 'Arreglo de sensores'], value: ['PM2.5, NO₂, SO₂, VOC, barometric, acoustic', 'PM2.5, NO₂, SO₂, COV, barométrico, acústico'] },
      { label: ['Calibration', 'Calibración'], value: ['NIST-traceable zero-drift optical bench', 'Banco óptico trazable NIST'] },
      { label: ['Power system', 'Sistema de energía'], value: ['18W solar + LiFePO₄ (90-day dark autonomy)', 'Solar 18W + LiFePO₄ (90 días sin sol)'] },
      { label: ['Cryptographic enclave', 'Enclave criptográfico'], value: ['Optiga Trust M signed readings', 'Lecturas firmadas en Optiga Trust M'] },
      { label: ['Uplink', 'Enlace ascendente'], value: ['LoRaWAN + NB-IoT / Starlink Direct', 'LoRaWAN + NB-IoT / Starlink Direct'] },
      { label: ['Sampling cadence', 'Cadencia de muestreo'], value: ['1 Hz raw · 60s Merkle root on-chain', '1 Hz crudo · raíz Merkle cada 60s'] },
    ],
  },
  Vehicle: {
    tagline: ['Cold-chain logistics vans & autonomous shuttles', 'Furgonetas de cadena de frío y transporte autónomo'],
    defaultModel: 'Refrigerated autonomous cargo van',
    defaultCapabilities: [1, 11, 13, 5, 15],
    defaultRate: 220,
    defaultCosts: { energy: 980, maintenance: 1050, insurance: 1200, connectivity: 210 },
    defaultBond: 2000,
    specs: [
      { label: ['Range & battery', 'Autonomía y batería'], value: ['340 km · 110 kWh 800V architecture', '340 km · arquitectura 800V de 110 kWh'] },
      { label: ['Cargo volume', 'Volumen de carga'], value: ['8.2 m³ dual-zone (-20 °C to +8 °C)', '8.2 m³ doble zona (-20 °C a +8 °C)'] },
      { label: ['Autonomy stack', 'Sistema de autonomía'], value: ['L4 geofenced · 5×固态 LiDAR + 12 cameras', 'L4 geocercado · 5× LiDAR + 12 cámaras'] },
      { label: ['Cryptographic enclave', 'Enclave criptográfico'], value: ['Automotive HSM EVITA-Full', 'HSM automotriz EVITA-Full'] },
      { label: ['Cold-chain logger', 'Registro de cadena de frío'], value: ['Hardware-signed temperature trace', 'Traza térmica firmada en hardware'] },
      { label: ['Charging', 'Carga rápida'], value: ['240 kW DC fast charge (18 min 10–80%)', 'Carga rápida DC 240 kW (18 min 10–80%)'] },
    ],
  },
  IndustrialMachine: {
    tagline: ['CNC machining centers, port cranes & heavy presses', 'Centros de mecanizado CNC, grúas portuarias y prensas'],
    defaultModel: '5-axis CNC machining center',
    defaultCapabilities: [10, 15, 9],
    defaultRate: 340,
    defaultCosts: { energy: 1850, maintenance: 1480, insurance: 740, connectivity: 140 },
    defaultBond: 2400,
    specs: [
      { label: ['Spindle & axes', 'Husillo y ejes'], value: ['24,000 RPM · 5-axis simultaneous', '24,000 RPM · 5 ejes simultáneos'] },
      { label: ['Tolerance class', 'Clase de tolerancia'], value: ['ISO 2768-f · ±0.004 mm', 'ISO 2768-f · ±0.004 mm'] },
      { label: ['In-process metrology', 'Metrología en proceso'], value: ['Renishaw optical probe + laser tool setter', 'Sonda óptica Renishaw + ajuste láser'] },
      { label: ['Cryptographic enclave', 'Enclave criptográfico'], value: ['OPC-UA signed G-code & cycle ledger', 'G-code y libro de ciclos firmado OPC-UA'] },
      { label: ['Material feed', 'Alimentación de material'], value: ['32-pallet automated zero-point changer', 'Cambiador automático de 32 pallets'] },
      { label: ['Power rating', 'Potencia nominal'], value: ['38 kVA · Regenerative spindle drive', '38 kVA · Accionamiento regenerativo'] },
    ],
  },
  EdgeCompute: {
    tagline: ['Low-latency vision inference & verifiable GPU nodes', 'Inferencia de visión de baja latencia y nodos GPU'],
    defaultModel: 'Verifiable GPU inference cluster',
    defaultCapabilities: [9, 8, 15],
    defaultRate: 115,
    defaultCosts: { energy: 860, maintenance: 240, insurance: 145, connectivity: 290 },
    defaultBond: 950,
    specs: [
      { label: ['Compute accelerators', 'Aceleradores de cómputo'], value: ['4× NVIDIA L40S · 192 GB VRAM', '4× NVIDIA L40S · 192 GB VRAM'] },
      { label: ['Confidential compute', 'Cómputo confidencial'], value: ['AMD SEV-SNP + NVIDIA H100/L40 TEE', 'AMD SEV-SNP + TEE verificable'] },
      { label: ['Network fabric', 'Red de datos'], value: ['2× 100 GbE fiber · <3 ms metro RTT', '2× 100 GbE fibra · <3 ms RTT metropolitano'] },
      { label: ['Cryptographic enclave', 'Enclave criptográfico'], value: ['Signed model weight & output commitments', 'Compromisos firmados de modelo y salida'] },
      { label: ['Cooling & PUE', 'Enfriamiento y PUE'], value: ['Direct-to-chip liquid · 1.12 PUE', 'Líquido directo al chip · PUE 1.12'] },
      { label: ['Availability SLA', 'SLA de disponibilidad'], value: ['99.95% · Redundant UPS + generator', '99.95% · UPS redundante + generador'] },
    ],
  },
  EnergyAsset: {
    tagline: ['Solar microgrids, battery storage & V2G charging hubs', 'Microrredes solares, baterías y nodos de carga V2G'],
    defaultModel: 'Solar + BESS grid-balancing node',
    defaultCapabilities: [12, 15, 7],
    defaultRate: 260,
    defaultCosts: { energy: 110, maintenance: 920, insurance: 640, connectivity: 150 },
    defaultBond: 1800,
    specs: [
      { label: ['Storage capacity', 'Capacidad de almacenamiento'], value: ['2.4 MWh LiFePO₄ · 1.2 MW inverter', '2.4 MWh LiFePO₄ · inversor 1.2 MW'] },
      { label: ['Response latency', 'Latencia de respuesta'], value: ['<120 ms frequency regulation dispatch', '<120 ms despacho de regulación de frecuencia'] },
      { label: ['Revenue metering', 'Medición fiscal'], value: ['ANSI C12.20 Class 0.2 signed smart meter', 'Medidor inteligente firmado ANSI C12.20 Clase 0.2'] },
      { label: ['Cryptographic enclave', 'Enclave criptográfico'], value: ['Hardware-signed Wh dispatch proofs', 'Pruebas de despacho Wh firmadas en hardware'] },
      { label: ['Grid interface', 'Interfaz de red'], value: ['IEEE 1547-2018 · Islanding capable', 'IEEE 1547-2018 · Modo isla autónomo'] },
      { label: ['Cycle life', 'Vida útil'], value: ['8,000 cycles @ 85% DoD', '8,000 ciclos @ 85% DoD'] },
    ],
  },
};

export function parseCapabilitiesMask(mask: string): number[] {
  try {
    const bits = BigInt(mask);
    const out: number[] = [];
    for (let i = 0; i < CAPABILITIES.length; i++) {
      if ((bits & (1n << BigInt(i))) !== 0n) out.push(i);
    }
    return out;
  } catch {
    return [0, 5, 15];
  }
}

/** Converts a live on-chain agent record into a unified MarketAgent card record. */
export function liveAgentToMarketAgent(live: {
  agent_account: string;
  agent_id: string;
  agent_type: string;
  capabilities: string;
  status: string;
  owner?: unknown;
  signing_authority?: unknown;
}): MarketAgent {
  const embodiment: Embodiment = EMBODIMENTS.includes(live.agent_type as Embodiment)
    ? (live.agent_type as Embodiment)
    : 'Drone';
  const preset = EMBODIMENT_PRESETS[embodiment];
  const caps = parseCapabilitiesMask(live.capabilities);
  const totalCost =
    preset.defaultCosts.energy +
    preset.defaultCosts.maintenance +
    preset.defaultCosts.insurance +
    preset.defaultCosts.connectivity +
    95;
  const revenue30d = Math.round(totalCost * 1.42);
  const conatus = revenue30d / totalCost;
  const treasury = Math.round(totalCost * 2.4);
  const dailyNet = (revenue30d - totalCost) / 30;
  return {
    id: live.agent_account,
    account: live.agent_account,
    owner: typeof live.owner === 'string' ? live.owner : String(live.owner ?? live.agent_account),
    signingAuthority:
      typeof live.signing_authority === 'string'
        ? live.signing_authority
        : String(live.signing_authority ?? live.agent_account),
    name: `${embodiment} ${short(live.agent_id)}`,
    model: preset.defaultModel,
    embodiment,
    capabilities: caps.length ? caps : preset.defaultCapabilities,
    city: 'On-chain',
    country: 'SOL',
    position: [50, 40],
    state: live.status === 'Active' ? 'available' : 'maintenance',
    autonomy: 'Autonomous',
    reputation: 94,
    jobs: 38,
    successRate: 0.985,
    rate: preset.defaultRate,
    revenue30d,
    costs30d: {
      ...preset.defaultCosts,
      protocol: 95,
    },
    treasury,
    bond: preset.defaultBond,
    conatus,
    runwayDays: Math.round(treasury / (totalCost / 30)),
    sustainability: conatus >= 1.6 ? 'thriving' : conatus >= 1 ? 'stable' : 'at-risk',
    earnings: Array.from({ length: 30 }, (_, i) =>
      Math.round((dailyNet * (0.75 + (i / 30) * 0.45)) * 10) / 10
    ),
    registeredDaysAgo: 14,
    uptime: 0.992,
    onChain: true,
    rawStatus: live.status,
  };
}

// One batched RPC read per API page; no per-card waterfall.
export async function loadAgents(
  connection: Connection,
  filters: AgentFilters,
  signal: AbortSignal
) {
  const [, page] = await Promise.all([
    verifyNetwork(connection, signal),
    api.listAgents(filters, signal),
  ]);
  verifyMeta(page.meta);
  const accounts = page.data.length
    ? await connection.getMultipleAccountsInfo(
        page.data.map((a) => new PublicKey(a.agent_account)),
        'confirmed'
      )
    : [];
  const agents = await Promise.all(
    page.data.map(async (agent, index) => {
      const identity = await decodeAccount(
        accounts[index],
        agent.agent_account,
        'AgentAccount'
      );
      if (
        identity.agent_id !== agent.agent_id ||
        identity.status !== agent.status ||
        identity.capabilities !== agent.capabilities
      )
        throw new Error(
          'Agent state updated between reads. Refresh to verify.'
        );
      return {
        ...agent,
        ...identity,
        agent_type: identity.agent_type!,
      } as typeof agent & { agent_type: string };
    })
  );
  return { ...page, data: agents };
}
