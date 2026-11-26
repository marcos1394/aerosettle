import { DEVNET_MANIFEST } from '../../config/devnet-manifest.ts';

export const WALLET_CAPABILITIES = Object.freeze({
  PUBLIC_READ: true,
  WALLET_CONNECT: true,
  WALLET_IDENTITY_VERIFIED: false, // Active chain is not proved by Wallet Standard.
  TRANSACTION_PREVIEW: true,
  TRANSACTION_SIGNING: false,
  TRANSACTION_SUBMISSION: false,
  FINANCIAL_AUTHORIZATION: false,
});

export type TransactionPreview = {
  status: 'INSUFFICIENT_DATA';
  network: 'solana:devnet';
  genesis_hash: string;
  program_id: string;
  token_mint: string;
  transaction_type: null;
  estimated_fee: null;
  requested_authority: null;
  recipient: null;
  risk_warnings: readonly string[];
};

export function informationalPreview(): TransactionPreview {
  return {
    status: 'INSUFFICIENT_DATA',
    network: DEVNET_MANIFEST.network as 'solana:devnet',
    genesis_hash: DEVNET_MANIFEST.genesis_hash,
    program_id: DEVNET_MANIFEST.program_id,
    token_mint: DEVNET_MANIFEST.token_mint,
    transaction_type: null,
    estimated_fee: null,
    requested_authority: null,
    recipient: null,
    risk_warnings: [
      'Active wallet network is not proved by Wallet Standard.',
      'No transaction instruction, fee quote, recipient or authority was supplied.',
      'Signing, submission and financial authorization are disabled in CON-54.',
    ],
  };
}
