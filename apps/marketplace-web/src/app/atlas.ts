/**
 * Conatus Network Atlas
 * ---------------------
 * A deterministic, curated snapshot of the Conatus agent economy. It powers the
 * product surfaces whose on-chain counterparts are not shipped yet (agent
 * treasuries, reputation, runway, economy analytics, fleet views…), so the app
 * can express the full product while the protocol catches up.
 *
 * Live on-chain records are always preferred where they exist; the Atlas is
 * merged next to them. It can be switched off from Settings (persisted in
 * localStorage) or globally with `VITE_CONATUS_SNAPSHOT=off`.
 */
import { useSyncExternalStore } from 'react';

// ───────────────────────────── Types ─────────────────────────────

export type Embodiment =
  | 'Drone'
  | 'Ugv'
  | 'Amr'
  | 'RobotArm'
  | 'Camera'
  | 'IotSensor'
  | 'Vehicle'
  | 'IndustrialMachine'
  | 'EdgeCompute'
  | 'EnergyAsset';

export type OperationalState = 'working' | 'available' | 'charging' | 'maintenance';
export type Sustainability = 'thriving' | 'stable' | 'at-risk';
export type Stage = 'Draft' | 'Open' | 'Claimed' | 'Submitted' | 'Verified' | 'Settled';

export interface CostBreakdown {
  energy: number;
  maintenance: number;
  insurance: number;
  connectivity: number;
  protocol: number;
}

export interface AtlasAgent {
  /** URL-safe identifier, used in routes: /app/agents/:id */
  id: string;
  /** Pseudo on-chain account (base58). */
  account: string;
  owner: string;
  signingAuthority: string;
  name: string;
  model: string;
  embodiment: Embodiment;
  /** Indexes into CAPABILITIES (config.ts). */
  capabilities: number[];
  city: string;
  country: string;
  /** Normalised map position, 0–100 on both axes (equirectangular). */
  position: [number, number];
  state: OperationalState;
  autonomy: 'Autonomous' | 'Supervised';
  reputation: number; // 0–100
  jobs: number;
  successRate: number; // 0–1
  /** Price in USDC per standard job. */
  rate: number;
  revenue30d: number;
  costs30d: CostBreakdown;
  treasury: number;
  bond: number;
  /** revenue / costs over 30 days. ≥1 means the agent sustains itself. */
  conatus: number;
  runwayDays: number;
  sustainability: Sustainability;
  /** 30 daily net earnings points (oldest → newest). */
  earnings: number[];
  registeredDaysAgo: number;
  uptime: number; // 0–1
}

export interface AtlasMission {
  id: string;
  account: string;
  title: string;
  category: MissionCategory;
  city: string;
  country: string;
  position: [number, number];
  reward: number;
  capabilities: number[];
  status: Stage;
  evidence: string[];
  /** Hours until execution deadline (negative = elapsed). */
  deadlineHours: number;
  createdHoursAgo: number;
  matches: number;
  requester: string;
  agentId?: string;
  summary: string;
}

export type MissionCategory =
  | 'Inspection'
  | 'Mapping'
  | 'Delivery'
  | 'Manufacturing'
  | 'Monitoring'
  | 'Energy'
  | 'Compute'
  | 'Agriculture'
  | 'Logistics';

export type EventKind =
  | 'settled'
  | 'verified'
  | 'submitted'
  | 'claimed'
  | 'created'
  | 'registered'
  | 'expense'
  | 'bond';

export interface AtlasEvent {
  id: string;
  kind: EventKind;
  minutesAgo: number;
  agentId?: string;
  missionId?: string;
  amount?: number;
  /** For expense events: what the agent paid for. */
  detail?: keyof CostBreakdown;
  signature: string;
}

// ───────────────────────────── Seeded randomness ─────────────────────────────

function mulberry32(seed: number) {
  return () => {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const rand = mulberry32(20261017);
const between = (min: number, max: number) => min + rand() * (max - min);
const pick = <T,>(items: readonly T[]) => items[Math.floor(rand() * items.length)];
const ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
function address(length = 44) {
  let out = '';
  for (let i = 0; i < length; i++) out += ALPHABET[Math.floor(rand() * ALPHABET.length)];
  return out;
}
const round = (n: number, step = 1) => Math.round(n / step) * step;
/** lon/lat → 0–100 map coordinates. */
const project = (lon: number, lat: number): [number, number] => [
  ((lon + 180) / 360) * 100,
  ((90 - lat) / 180) * 100,
];

// ───────────────────────────── Agents ─────────────────────────────

type AgentSeed = [
  name: string,
  embodiment: Embodiment,
  model: string,
  capabilities: number[],
  city: string,
  country: string,
  lon: number,
  lat: number,
  baseRevenue: number,
];

const AGENT_SEEDS: AgentSeed[] = [
  ['Kestrel-7', 'Drone', 'RTK survey quadrotor', [0, 2, 5, 6, 14, 15], 'Monterrey', 'MX', -100.3, 25.7, 4200],
  ['Halcyon-3', 'Drone', 'Thermal inspection hexacopter', [0, 3, 5, 8, 15], 'Houston', 'US', -95.4, 29.8, 5100],
  ['Atlas Courier 12', 'Amr', 'Last-mile delivery robot', [1, 11, 5, 8, 9], 'Madrid', 'ES', -3.7, 40.4, 2600],
  ['Mantis R2', 'RobotArm', '6-axis assembly cell', [10, 8, 9, 15], 'Guadalajara', 'MX', -103.3, 20.7, 6800],
  ['Sentinel Grid 04', 'IotSensor', 'Environmental mesh node', [7, 15, 9], 'Rotterdam', 'NL', 4.5, 51.9, 640],
  ['Boreal-9', 'Ugv', 'All-terrain inspection rover', [1, 3, 6, 8, 15], 'Calgary', 'CA', -114.1, 51.0, 3900],
  ['Lumen Array 2', 'EnergyAsset', 'Solar + storage microgrid', [12, 15, 7], 'Atacama', 'CL', -69.2, -24.5, 7400],
  ['Ferro Press 11', 'IndustrialMachine', '5-axis CNC machining center', [10, 15, 9], 'Stuttgart', 'DE', 9.2, 48.8, 9100],
  ['Orbis Edge 5', 'EdgeCompute', 'GPU inference node', [9, 8, 15], 'Singapore', 'SG', 103.8, 1.35, 3300],
  ['Polar Cart 6', 'Vehicle', 'Refrigerated autonomous van', [1, 11, 13, 5, 15], 'Lyon', 'FR', 4.8, 45.8, 5600],
  ['Vigil Cam 21', 'Camera', 'Urban vision node', [2, 8, 9, 15], 'Seoul', 'KR', 127.0, 37.6, 980],
  ['Swift Wing 2', 'Drone', 'Fixed-wing mapping VTOL', [0, 4, 6, 14, 15], 'Nairobi', 'KE', 36.8, -1.3, 3600],
  ['Tessera Bot', 'Amr', 'Warehouse picking robot', [1, 10, 8, 11], 'Osaka', 'JP', 135.5, 34.7, 3100],
  ['AgriScan 8', 'Drone', 'Multispectral crop scout', [0, 4, 6, 7, 14], 'Córdoba', 'AR', -64.2, -31.4, 2900],
  ['Harbor Lift 3', 'IndustrialMachine', 'Retrofitted port crane', [10, 11, 15], 'Valencia', 'ES', -0.4, 39.5, 8300],
  ['Delta Rover 1', 'Ugv', 'Solar-farm cleaning rover', [1, 10, 12, 5], 'Phoenix', 'US', -112.1, 33.4, 2100],
  ['Nimbus Station', 'IotSensor', 'Weather & air-quality station', [7, 5, 15], 'Bogotá', 'CO', -74.1, 4.7, 520],
  ['Cirrus Relay 4', 'Drone', 'Medical supply drone', [0, 11, 13, 5], 'Kigali', 'RW', 30.1, -1.95, 3800],
  ['Weld Vector 7', 'RobotArm', 'Collaborative welding cobot', [10, 3, 8, 15], 'Detroit', 'US', -83.0, 42.3, 6100],
  ['Grid Pulse 2', 'EnergyAsset', 'Bidirectional EV charging hub', [12, 15], 'Oslo', 'NO', 10.75, 59.9, 4700],
  ['Quarry Eye', 'Camera', 'Thermal perimeter camera', [3, 8, 15], 'Antofagasta', 'CL', -70.4, -23.6, 760],
  ['Wayfinder 3', 'Vehicle', 'Autonomous campus shuttle', [1, 11, 5, 6, 8], 'Austin', 'US', -97.7, 30.3, 4400],
  ['Cortex Node 9', 'EdgeCompute', 'Vision model edge cluster', [9, 8], 'Frankfurt', 'DE', 8.7, 50.1, 2800],
  ['Tidal Probe 2', 'IotSensor', 'Marine water-quality buoy', [7, 5, 15], 'Lisbon', 'PT', -9.1, 38.7, 450],
];

const COST_PROFILE: Record<Embodiment, CostBreakdown> = {
  Drone: { energy: 0.14, maintenance: 0.3, insurance: 0.26, connectivity: 0.06, protocol: 0.04 },
  Ugv: { energy: 0.18, maintenance: 0.32, insurance: 0.2, connectivity: 0.05, protocol: 0.04 },
  Amr: { energy: 0.16, maintenance: 0.28, insurance: 0.18, connectivity: 0.06, protocol: 0.04 },
  RobotArm: { energy: 0.22, maintenance: 0.26, insurance: 0.12, connectivity: 0.03, protocol: 0.04 },
  Camera: { energy: 0.08, maintenance: 0.12, insurance: 0.08, connectivity: 0.16, protocol: 0.04 },
  IotSensor: { energy: 0.06, maintenance: 0.14, insurance: 0.05, connectivity: 0.22, protocol: 0.04 },
  Vehicle: { energy: 0.24, maintenance: 0.26, insurance: 0.3, connectivity: 0.05, protocol: 0.04 },
  IndustrialMachine: { energy: 0.3, maintenance: 0.24, insurance: 0.12, connectivity: 0.02, protocol: 0.04 },
  EdgeCompute: { energy: 0.36, maintenance: 0.1, insurance: 0.06, connectivity: 0.12, protocol: 0.04 },
  EnergyAsset: { energy: 0.02, maintenance: 0.2, insurance: 0.14, connectivity: 0.03, protocol: 0.04 },
};

const STATES: OperationalState[] = ['working', 'working', 'working', 'available', 'available', 'charging', 'maintenance'];
// A few agents intentionally struggle: the survival mechanic needs to be visible.
const STRUGGLING = new Set(['Sentinel Grid 04', 'Delta Rover 1', 'Tidal Probe 2', 'Cortex Node 9']);

const slug = (value: string) =>
  value
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '');

export const AGENTS: AtlasAgent[] = AGENT_SEEDS.map(
  ([name, embodiment, model, capabilities, city, country, lon, lat, base]) => {
    const struggling = STRUGGLING.has(name);
    const revenue30d = round(base * between(0.85, 1.25), 1);
    const profile = COST_PROFILE[embodiment];
    const pressure = struggling ? between(1.6, 2.1) : between(0.75, 1.15);
    const costs30d = Object.fromEntries(
      Object.entries(profile).map(([key, share]) => [key, round(revenue30d * share * pressure, 1)])
    ) as unknown as CostBreakdown;
    const totalCost = Object.values(costs30d).reduce((a, b) => a + b, 0);
    const conatus = revenue30d / totalCost;
    const treasury = round(totalCost * (struggling ? between(0.3, 0.9) : between(1.6, 5.2)), 1);
    const runwayDays = Math.max(1, Math.round(treasury / (totalCost / 30)));
    const dailyNet = (revenue30d - totalCost) / 30;
    const earnings = Array.from({ length: 30 }, (_, i) =>
      round(dailyNet * (0.55 + (i / 30) * 0.6) + (revenue30d / 30) * between(-0.35, 0.35), 0.1)
    );
    const jobs = Math.round(between(40, 1400) * (base > 3000 ? 0.5 : 1.3));
    return {
      id: slug(name),
      account: address(),
      owner: address(),
      signingAuthority: address(),
      name,
      model,
      embodiment,
      capabilities,
      city,
      country,
      position: project(lon, lat),
      state: struggling && rand() > 0.5 ? 'maintenance' : pick(STATES),
      autonomy: rand() > 0.28 ? 'Autonomous' : 'Supervised',
      reputation: Math.round(struggling ? between(62, 78) : between(81, 99)),
      jobs,
      successRate: struggling ? between(0.86, 0.93) : between(0.95, 0.997),
      rate: round(base / between(18, 34), 0.5),
      revenue30d,
      costs30d,
      treasury,
      bond: round(between(250, 2500), 50),
      conatus,
      runwayDays,
      sustainability: conatus >= 1.6 ? 'thriving' : conatus >= 1 ? 'stable' : 'at-risk',
      earnings,
      registeredDaysAgo: Math.round(between(12, 420)),
      uptime: struggling ? between(0.88, 0.95) : between(0.965, 0.999),
    };
  }
);

export const agentById = (id: string) => AGENTS.find((agent) => agent.id === id);
export const totalCosts = (agent: AtlasAgent) =>
  Object.values(agent.costs30d).reduce((a, b) => a + b, 0);

// ───────────────────────────── Missions ─────────────────────────────

type MissionSeed = [
  title: string,
  category: MissionCategory,
  city: string,
  country: string,
  lon: number,
  lat: number,
  reward: number,
  capabilities: number[],
  status: Stage,
  evidence: string[],
  summary: string,
  agent?: string,
];

const MISSION_SEEDS: MissionSeed[] = [
  ['Thermal inspection · 48 MW solar park', 'Inspection', 'Hermosillo', 'MX', -110.9, 29.1, 1850, [0, 3, 6], 'Open', ['Radiometric imagery', 'Flight log', 'Hotspot report'], 'Identify defective strings and hotspots across 120,000 panels.'],
  ['Bridge deck survey · Span 14', 'Inspection', 'Houston', 'US', -95.4, 29.8, 2400, [0, 2, 6, 14], 'Claimed', ['Orthomosaic', 'Crack map', 'RTK log'], 'Sub-centimetre deck imagery for structural review.', 'halcyon-3'],
  ['Cold-chain vaccine run', 'Delivery', 'Kigali', 'RW', 30.1, -1.95, 620, [0, 11, 13], 'Submitted', ['Temperature trace', 'GPS track', 'Recipient signature'], 'Deliver 40 vials to three rural clinics under 8 °C.', 'cirrus-relay-4'],
  ['Corn canopy NDVI · 900 ha', 'Agriculture', 'Córdoba', 'AR', -64.2, -31.4, 1300, [0, 4, 14], 'Verified', ['NDVI raster', 'Prescription map'], 'Variable-rate fertiliser prescription for the next pass.', 'agriscan-8'],
  ['Pipeline right-of-way patrol', 'Monitoring', 'Calgary', 'CA', -114.1, 51.0, 2100, [1, 3, 8], 'Open', ['Thermal video', 'Anomaly report'], 'Detect leaks and encroachments along 32 km of pipeline.'],
  ['Precision bracket batch · 500 units', 'Manufacturing', 'Stuttgart', 'DE', 9.2, 48.8, 4800, [10, 15], 'Settled', ['CMM report', 'Machine telemetry'], 'Aluminium brackets to ISO 2768-f tolerances.', 'ferro-press-11'],
  ['Air-quality grid · Q4 dataset', 'Monitoring', 'Rotterdam', 'NL', 4.5, 51.9, 380, [7, 15], 'Settled', ['Signed sensor feed', 'Calibration proof'], 'Hourly PM2.5 / NO₂ readings across the port district.', 'sentinel-grid-04'],
  ['Container yard re-stacking', 'Logistics', 'Valencia', 'ES', -0.4, 39.5, 3600, [10, 11], 'Claimed', ['Move ledger', 'Yard telemetry'], 'Re-sequence 1,200 TEU before vessel arrival.', 'harbor-lift-3'],
  ['Grocery last-mile · Chamberí', 'Delivery', 'Madrid', 'ES', -3.7, 40.4, 210, [1, 11, 5], 'Settled', ['Proof of delivery', 'GPS track'], '28 doorstep deliveries within a 2-hour window.', 'atlas-courier-12'],
  ['Peak shaving · evening window', 'Energy', 'Oslo', 'NO', 10.75, 59.9, 940, [12], 'Verified', ['Metered dispatch', 'Grid signal'], 'Dispatch 1.2 MWh to relieve the local substation.', 'grid-pulse-2'],
  ['Retail footfall analytics', 'Compute', 'Seoul', 'KR', 127.0, 37.6, 290, [2, 8, 9], 'Submitted', ['Anonymised counts', 'Model hash'], 'Privacy-preserving visitor counts for 6 storefronts.', 'vigil-cam-21'],
  ['Wildlife corridor mapping', 'Mapping', 'Nairobi', 'KE', 36.8, -1.3, 1700, [0, 4, 14], 'Open', ['Orthomosaic', 'Species heatmap'], 'Map 60 km² of corridor for a conservation trust.'],
  ['Weld seam batch · chassis line', 'Manufacturing', 'Detroit', 'US', -83.0, 42.3, 3900, [10, 8], 'Claimed', ['Seam imagery', 'Current trace'], '340 MIG seams with automated visual QA.', 'weld-vector-7'],
  ['Mine perimeter watch · night shift', 'Monitoring', 'Antofagasta', 'CL', -70.4, -23.6, 450, [3, 8], 'Open', ['Thermal clips', 'Event log'], 'Continuous thermal intrusion detection, 22:00–06:00.'],
  ['Pick & pack sprint · 2,000 SKUs', 'Logistics', 'Osaka', 'JP', 135.5, 34.7, 1600, [1, 10, 11], 'Verified', ['WMS export', 'Pick log'], 'Fulfil a flash-sale backlog before 08:00 JST.', 'tessera-bot'],
  ['Panel cleaning · Block C', 'Energy', 'Phoenix', 'US', -112.1, 33.4, 520, [1, 12], 'Open', ['Before/after imagery', 'Yield delta'], 'Waterless cleaning of 4,800 panels.'],
  ['Campus shuttle · conference week', 'Logistics', 'Austin', 'US', -97.7, 30.3, 2900, [1, 11, 8], 'Claimed', ['Ride ledger', 'Safety log'], 'Loop service across 9 stops for 5 days.', 'wayfinder-3'],
  ['Defect model inference · 1M frames', 'Compute', 'Frankfurt', 'DE', 8.7, 50.1, 1100, [9, 8], 'Open', ['Result manifest', 'Model hash'], 'Run a customer-supplied defect model over line footage.'],
  ['Coastal water sampling', 'Monitoring', 'Lisbon', 'PT', -9.1, 38.7, 340, [7, 5], 'Draft', ['Signed sensor feed'], 'Salinity and turbidity sampling at 12 points.'],
  ['Fresh produce relay · overnight', 'Delivery', 'Lyon', 'FR', 4.8, 45.8, 1250, [1, 11, 13], 'Settled', ['Temperature trace', 'Proof of delivery'], 'Overnight cold-chain relay to 14 restaurants.', 'polar-cart-6'],
  ['Substation thermal sweep', 'Inspection', 'Monterrey', 'MX', -100.3, 25.7, 1450, [0, 3, 8], 'Submitted', ['Radiometric imagery', 'Hotspot report'], 'Find overheating connectors before summer peak.', 'kestrel-7'],
  ['Micro-assembly · sensor boards', 'Manufacturing', 'Guadalajara', 'MX', -103.3, 20.7, 5200, [10, 8, 9], 'Open', ['Vision QA log', 'Cycle telemetry'], '3,000 boards, pick-and-place with in-line inspection.'],
  ['Wind farm blade inspection', 'Inspection', 'Aarhus', 'DK', 10.2, 56.2, 3300, [0, 2, 3, 6], 'Open', ['Blade imagery', 'Damage report'], 'Close-range imagery of 18 turbines.'],
  ['Flood-risk terrain model', 'Mapping', 'Bogotá', 'CO', -74.1, 4.7, 2200, [0, 6, 14], 'Draft', ['DEM', 'Ground control log'], 'High-resolution DEM of a 14 km river basin.'],
  ['Microgrid balancing · weekend', 'Energy', 'Atacama', 'CL', -69.2, -24.5, 1800, [12, 15], 'Settled', ['Metered dispatch'], 'Stabilise a mining camp microgrid for 48 hours.', 'lumen-array-2'],
  ['Hospital supply loop', 'Delivery', 'Singapore', 'SG', 103.8, 1.35, 780, [1, 11], 'Open', ['Proof of delivery', 'Access log'], 'Intra-campus delivery of lab samples, 24/7.'],
];

export const MISSIONS: AtlasMission[] = MISSION_SEEDS.map(
  ([title, category, city, country, lon, lat, reward, capabilities, status, evidence, summary, agentId], i) => ({
    id: `m-${(4100 + i * 7).toString(36)}`,
    account: address(),
    title,
    category,
    city,
    country,
    position: project(lon, lat),
    reward,
    capabilities,
    status,
    evidence,
    summary,
    agentId,
    requester: address(),
    deadlineHours:
      status === 'Settled' || status === 'Verified'
        ? -Math.round(between(4, 160))
        : Math.round(between(6, 240)),
    createdHoursAgo: Math.round(between(1, 300)),
    matches: AGENTS.filter((agent) => capabilities.every((c) => agent.capabilities.includes(c))).length,
  })
);

export const missionById = (id: string) => MISSIONS.find((mission) => mission.id === id);
export const MISSION_CATEGORIES: MissionCategory[] = [
  'Inspection',
  'Mapping',
  'Delivery',
  'Manufacturing',
  'Monitoring',
  'Energy',
  'Compute',
  'Agriculture',
  'Logistics',
];

// ───────────────────────────── Events ─────────────────────────────

export const EVENTS: AtlasEvent[] = (() => {
  const events: AtlasEvent[] = [];
  let minutes = 1;
  const kinds: EventKind[] = ['settled', 'verified', 'submitted', 'claimed', 'created', 'expense', 'expense', 'settled', 'registered', 'bond'];
  for (let i = 0; i < 64; i++) {
    const kind = pick(kinds);
    const agent = pick(AGENTS);
    const mission = pick(MISSIONS);
    const costKeys: (keyof CostBreakdown)[] = ['energy', 'maintenance', 'insurance', 'connectivity'];
    events.push({
      id: `e-${i}`,
      kind,
      minutesAgo: minutes,
      agentId: kind === 'created' ? undefined : agent.id,
      missionId: ['settled', 'verified', 'submitted', 'claimed', 'created'].includes(kind) ? mission.id : undefined,
      amount:
        kind === 'expense'
          ? round(between(4, 180), 0.01)
          : kind === 'bond'
            ? round(between(250, 1500), 50)
            : ['settled', 'created'].includes(kind)
              ? mission.reward
              : undefined,
      detail: kind === 'expense' ? pick(costKeys) : undefined,
      signature: address(88),
    });
    minutes += Math.round(between(1, 26));
  }
  return events;
})();

// ───────────────────────────── Network series ─────────────────────────────

/** 90 days of settled volume (USDC), oldest → newest. */
export const VOLUME_SERIES: number[] = Array.from({ length: 90 }, (_, i) => {
  const trend = 18000 + i * i * 7.2 + i * 260;
  const weekly = Math.sin((i / 7) * Math.PI * 2) * 2600;
  return round(trend + weekly + between(-2400, 2400), 10);
});
/** 90 days of active agents. */
export const AGENT_SERIES: number[] = Array.from({ length: 90 }, (_, i) =>
  Math.round(410 + i * 9.4 + Math.sin(i / 5) * 14 + between(-8, 8))
);

/** Network-wide scale; the Atlas agents are a representative sample of it. */
export const NETWORK = {
  agents: AGENT_SERIES[AGENT_SERIES.length - 1],
  operators: 318,
  countries: 41,
  missionsCompleted: 182_406,
  volume30d: VOLUME_SERIES.slice(-30).reduce((a, b) => a + b, 0),
  volumeAllTime: 14_870_000 + VOLUME_SERIES.reduce((a, b) => a + b, 0),
  avgSettlementSeconds: 2.4,
  selfSustainingShare: AGENTS.filter((a) => a.conatus >= 1).length / AGENTS.length,
  bonded: AGENTS.reduce((a, b) => a + b.bond, 0) * 48,
  verificationRate: 0.987,
};

/** Demand (open mission value share) vs supply (agent share) per capability index. */
export const CAPABILITY_MARKET = Array.from({ length: 16 }, (_, index) => {
  const demand = MISSIONS.filter((m) => m.capabilities.includes(index)).reduce((a, m) => a + m.reward, 0);
  const supply = AGENTS.filter((a) => a.capabilities.includes(index)).length;
  return { index, demand, supply };
});

// ───────────────────────────── Snapshot preference ─────────────────────────────

const STORAGE_KEY = 'conatus.snapshot';
const listeners = new Set<() => void>();
const envDisabled = import.meta.env.VITE_CONATUS_SNAPSHOT === 'off';
function readSnapshot() {
  if (envDisabled) return false;
  try {
    return localStorage.getItem(STORAGE_KEY) !== 'off';
  } catch {
    return true;
  }
}
let snapshotEnabled = readSnapshot();
export function setSnapshotEnabled(value: boolean) {
  snapshotEnabled = value && !envDisabled;
  try {
    localStorage.setItem(STORAGE_KEY, value ? 'on' : 'off');
  } catch {
    /* Preference stays for the session. */
  }
  listeners.forEach((listener) => listener());
}
/** Whether Atlas data should be merged into product surfaces. */
export function useSnapshot(): [boolean, (value: boolean) => void] {
  const value = useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => snapshotEnabled
  );
  return [value, setSnapshotEnabled];
}
export const snapshotLocked = envDisabled;

// ───────────────────────────── Formatting ─────────────────────────────

const intl = (locale: string) => (locale === 'es' ? 'es-MX' : 'en-US');

/** Settlement asset symbol shown across the product. */
export const SETTLEMENT_SYMBOL = 'USDC';

export function usd(value: number, locale = 'en', compact = false) {
  return new Intl.NumberFormat(intl(locale), {
    style: 'currency',
    currency: 'USD',
    notation: compact ? 'compact' : 'standard',
    maximumFractionDigits: compact ? 1 : value < 100 ? 2 : 0,
  }).format(value);
}
export function num(value: number, locale = 'en', compact = false) {
  return new Intl.NumberFormat(intl(locale), {
    notation: compact ? 'compact' : 'standard',
    maximumFractionDigits: compact ? 1 : 0,
  }).format(value);
}
export function pct(value: number, locale = 'en', digits = 0) {
  return new Intl.NumberFormat(intl(locale), {
    style: 'percent',
    maximumFractionDigits: digits,
  }).format(value);
}
export function ago(minutes: number, locale = 'en') {
  const rtf = new Intl.RelativeTimeFormat(intl(locale), { numeric: 'auto', style: 'short' });
  if (minutes < 60) return rtf.format(-Math.max(1, Math.round(minutes)), 'minute');
  if (minutes < 60 * 24) return rtf.format(-Math.round(minutes / 60), 'hour');
  return rtf.format(-Math.round(minutes / 1440), 'day');
}
export function inHours(hours: number, locale = 'en') {
  const rtf = new Intl.RelativeTimeFormat(intl(locale), { numeric: 'auto', style: 'short' });
  if (Math.abs(hours) < 48) return rtf.format(Math.round(hours), 'hour');
  return rtf.format(Math.round(hours / 24), 'day');
}
