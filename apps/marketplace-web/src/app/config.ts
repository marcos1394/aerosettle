import { PublicKey } from '@solana/web3.js';
import { SETTLEMENT_SYMBOL } from './atlas';
export { LOCALNET_GENESIS, PROGRAM_ID } from '@aerosettle/transaction-sdk';
export const RPC = 'http://127.0.0.1:8899';
export const MINT = new PublicKey(
  'HTHpns7gqLAhSBhAzqxhYdyHv9HeXkkRW6aHQfdUjL1G'
);
export const VERIFIER = new PublicKey(
  'DmWQhuVujHrJb4jFzo62UnCT3mwnx9GFtVdo8VUu82Wu'
);
export const TOKEN_PROGRAM = new PublicKey(
  'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
);
export const STAGES = [
  'Draft',
  'Open',
  'Claimed',
  'Submitted',
  'Verified',
  'Settled',
] as const;
export const CAPABILITIES = [
  'Movilidad aérea',
  'Movilidad terrestre',
  'Visión RGB',
  'Visión térmica',
  'Visión multiespectral',
  'GPS',
  'RTK GPS',
  'Sensores ambientales',
  'Detección de objetos',
  'Inferencia Edge',
  'Manipulación física',
  'Transporte',
  'Suministro energético',
  'Cadena de frío',
  'Cartografía',
  'Telemetría',
];
export function capabilities(mask: string) {
  const bits = BigInt(mask);
  const names = CAPABILITIES.filter(
    (_, i) => (bits & (1n << BigInt(i))) !== 0n
  );
  if (bits >> 16n) names.push(`extra:${bits >> 16n}`);
  return names;
}
export const short = (value: string) =>
  value.length > 22 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value;
export function field(value: unknown): string {
  if (
    value === null ||
    value === undefined ||
    value === '' ||
    value === '11111111111111111111111111111111' ||
    (typeof value === 'string' && /^0{64}$/.test(value))
  )
    return 'No registrado';
  return typeof value === 'string' ||
    typeof value === 'number' ||
    typeof value === 'boolean'
    ? String(value)
    : 'No disponible';
}
export function date(value: unknown, locale: string = 'en'): string {
  const number = Number(value);
  return Number.isFinite(number) && number > 0
    ? new Date(number * 1000).toLocaleString(
        locale === 'es' ? 'es-MX' : 'en-US'
      )
    : 'No registrado';
}
export function amount(
  order: Record<string, unknown>,
  locale: string = 'en'
): string {
  if (
    typeof order.total_amount !== 'string' ||
    !/^\d+$/.test(order.total_amount)
  )
    return 'No disponible';
  if (order.token_mint !== MINT.toBase58())
    return `${order.total_amount} ${locale === 'es' ? 'unidades base' : 'base units'}`;
  const value = BigInt(order.total_amount);
  const fraction = (value % 1_000_000n)
    .toString()
    .padStart(6, '0')
    .replace(/0+$/, '');
  return `${value / 1_000_000n}${fraction ? `.${fraction}` : ''} ${SETTLEMENT_SYMBOL}`;
}

export function time(value: string | undefined, locale: string = 'en'): string {
  return value
    ? new Intl.DateTimeFormat(locale === 'es' ? 'es-MX' : 'en-US', {
        hour: 'numeric',
        minute: '2-digit',
        second: '2-digit',
      }).format(new Date(value))
    : '—';
}
