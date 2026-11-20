import { DEVNET_MANIFEST } from '../config/devnet-manifest.ts';
import type { DevnetIndex, Row, SnapshotProvenance } from './index.ts';

const ADDRESS = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;
const ID = /^[a-f0-9]{64}$/;
export const CAPABILITY_NAMES = [
  ['Aerial mobility', 'Movilidad aérea'], ['Ground mobility', 'Movilidad terrestre'],
  ['RGB vision', 'Visión RGB'], ['Thermal vision', 'Visión térmica'],
  ['Multispectral vision', 'Visión multiespectral'], ['GPS', 'GPS'],
  ['RTK GPS', 'GPS RTK'], ['Environmental sensors', 'Sensores ambientales'],
  ['Object detection', 'Detección de objetos'], ['Edge inference', 'Inferencia en borde'],
  ['Physical manipulation', 'Manipulación física'], ['Transport', 'Transporte'],
  ['Energy supply', 'Suministro energético'], ['Cold chain', 'Cadena de frío'],
  ['Mapping', 'Cartografía'], ['Telemetry', 'Telemetría'],
] as const;
export type AgentStatus = 'Active' | 'OwnerSuspended' | 'AdminSuspended' | 'Revoked';
export type WorkOrderStatus = 'Draft' | 'Open' | 'Claimed' | 'Submitted' | 'Verified' |
  'Settled' | 'Cancelled' | 'Expired';
export type VerifiedAgent = { agent_account: string; agent_id: string; owner: string;
  signing_authority: string; protocol_config: string; capabilities: number;
  active: boolean; status: AgentStatus; provenance: 'ONCHAIN_VERIFIED' };
export type VerifiedWorkOrder = { work_order_account: string; work_order_id: string;
  creator: string; protocol_config: string; token_mint: string; token_program: string;
  required_capabilities: number; execution_deadline: number; is_open: boolean;
  status: WorkOrderStatus; provenance: 'ONCHAIN_VERIFIED' };
export type Catalog = { agents: VerifiedAgent[]; workorders: VerifiedWorkOrder[];
  provenance: SnapshotProvenance; snapshotSha: string; expiresAt: string };

function isAddress(value: unknown): value is string {
  return typeof value === 'string' && ADDRESS.test(value);
}
function isId(value: unknown): value is string {
  return typeof value === 'string' && ID.test(value);
}
function mask(value: unknown): number | null {
  if ((typeof value !== 'number' && typeof value !== 'string') ||
      !/^(0|[1-9][0-9]*)$/.test(String(value))) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed >= 0 && parsed <= 65535 ? parsed : null;
}
function timestamp(value: unknown): number | null {
  if ((typeof value !== 'number' && typeof value !== 'string') ||
      !/^(0|[1-9][0-9]*)$/.test(String(value))) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed >= 0 ? parsed : null;
}
export function parseAgent(row: Row): VerifiedAgent {
  const status = row.status;
  const capabilities = mask(row.capabilities);
  if (!isAddress(row.agent_account) || !isId(row.agent_id) ||
      !isAddress(row.owner) || !isAddress(row.signing_authority) ||
      !isAddress(row.protocol_config) || capabilities === null ||
      !['Active', 'OwnerSuspended', 'AdminSuspended', 'Revoked'].includes(String(status)) ||
      typeof row.active !== 'boolean') throw Error('AGENT_RECORD_INVALID');
  return { agent_account: row.agent_account, agent_id: row.agent_id,
    owner: row.owner, signing_authority: row.signing_authority,
    protocol_config: row.protocol_config, capabilities, active: row.active,
    status: status as AgentStatus, provenance: 'ONCHAIN_VERIFIED' };
}
export function parseWorkOrder(row: Row): VerifiedWorkOrder {
  const status = row.status;
  const required = mask(row.required_capabilities);
  const deadline = timestamp(row.execution_deadline);
  if (!isAddress(row.work_order_account) || !isId(row.work_order_id) ||
      !isAddress(row.creator) || !isAddress(row.protocol_config) ||
      row.token_mint !== DEVNET_MANIFEST.token_mint ||
      row.token_program !== DEVNET_MANIFEST.token_program ||
      required === null || deadline === null || typeof row.is_open !== 'boolean' ||
      !['Draft', 'Open', 'Claimed', 'Submitted', 'Verified', 'Settled',
        'Cancelled', 'Expired'].includes(String(status))) throw Error('WORKORDER_RECORD_INVALID');
  return { work_order_account: row.work_order_account, work_order_id: row.work_order_id,
    creator: row.creator, protocol_config: row.protocol_config,
    token_mint: row.token_mint, token_program: row.token_program,
    required_capabilities: required, execution_deadline: deadline,
    is_open: row.is_open, status: status as WorkOrderStatus, provenance: 'ONCHAIN_VERIFIED' };
}
export function parseCatalog(index: DevnetIndex): Catalog {
  const agents = index.agents.map(parseAgent);
  const workorders = index.workorders.map(parseWorkOrder);
  if (agents.length !== index.agentCount || workorders.length !== index.workorderCount ||
      new Set(agents.map((row) => row.agent_account)).size !== agents.length ||
      new Set(workorders.map((row) => row.work_order_account)).size !== workorders.length)
    throw Error('INDEX_RECORD_INVALID');
  return { agents, workorders, provenance: index.provenance,
    snapshotSha: index.snapshotSha, expiresAt: index.expiresAt };
}
export function capabilityBits(maskValue: number): number[] {
  return CAPABILITY_NAMES.map((_, index) => index).filter((index) =>
    (maskValue & (1 << index)) !== 0);
}
export function filterAgents(agents: VerifiedAgent[], search: string, status: string,
  capability: string, sort: string): VerifiedAgent[] {
  const q = search.trim().toLowerCase();
  const bit = capability === '' ? -1 : Number(capability);
  return agents.filter((agent) =>
    (!status || agent.status === status) &&
    (bit < 0 || capabilityBits(agent.capabilities).includes(bit)) &&
    (!q || [agent.agent_account, agent.agent_id, agent.owner,
      agent.signing_authority, agent.status].some((value) => value.toLowerCase().includes(q)))
  ).sort((a, b) => {
    if (sort === 'status') return a.status.localeCompare(b.status) || a.agent_account.localeCompare(b.agent_account);
    return sort === 'address-desc' ? b.agent_account.localeCompare(a.agent_account) :
      a.agent_account.localeCompare(b.agent_account);
  });
}
export function filterWorkOrders(orders: VerifiedWorkOrder[], search: string,
  status: string, capability: string, sort: string): VerifiedWorkOrder[] {
  const q = search.trim().toLowerCase();
  const bit = capability === '' ? -1 : Number(capability);
  return orders.filter((order) =>
    (!status || order.status === status) &&
    (bit < 0 || capabilityBits(order.required_capabilities).includes(bit)) &&
    (!q || [order.work_order_account, order.work_order_id, order.creator,
      order.status].some((value) => value.toLowerCase().includes(q)))
  ).sort((a, b) => {
    if (sort === 'deadline') return a.execution_deadline - b.execution_deadline ||
      a.work_order_account.localeCompare(b.work_order_account);
    if (sort === 'status') return a.status.localeCompare(b.status) ||
      a.work_order_account.localeCompare(b.work_order_account);
    return sort === 'address-desc' ? b.work_order_account.localeCompare(a.work_order_account) :
      a.work_order_account.localeCompare(b.work_order_account);
  });
}
export function shortAddress(value: string): string {
  return `${value.slice(0, 6)}…${value.slice(-6)}`;
}
export function explorerUrl(address: string): string {
  if (!isAddress(address)) throw Error('INVALID_PUBKEY');
  return `https://explorer.solana.com/address/${address}?cluster=devnet`;
}
