import type { Environment } from './schema.ts';

export const CAPABILITIES = Object.freeze({
  LOCALNET: Object.freeze({ read_public_data: true, connect_wallet: true,
    prepare_transaction: true, simulate_transaction: true,
    request_signature: true, send_transaction: true }),
  DEVNET: Object.freeze({ read_public_data: true, connect_wallet: false,
    prepare_transaction: false, simulate_transaction: false,
    request_signature: false, send_transaction: false }),
  MAINNET: Object.freeze({ read_public_data: false, connect_wallet: false,
    prepare_transaction: false, simulate_transaction: false,
    request_signature: false, send_transaction: false }),
});

export function requireCapability(environment: Environment, name: keyof typeof CAPABILITIES.DEVNET): void {
  if (!CAPABILITIES[environment][name]) throw new Error('CAPABILITY_DISABLED');
}
