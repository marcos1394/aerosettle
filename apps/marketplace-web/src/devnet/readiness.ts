import type { Verification } from '../config/verify.ts';

export interface StagingReadiness {
  WEB_AVAILABLE: boolean;
  RPC_VERIFIED: boolean;
  API_NOT_CONFIGURED: boolean;
  DEGRADED_READ_ONLY: boolean;
  READY_FOR_READ_ONLY_PREVIEW: boolean;
  READY_FOR_TRANSACTIONS: false;
}

export function stagingReadiness(verification: Verification): StagingReadiness {
  const rpcVerified = verification.status === 'DEGRADED_READ_ONLY' &&
    verification.reason === 'API_NOT_CONFIGURED' &&
    verification.provenance === 'LIVE_DEVNET_READ_ONLY';
  return {
    WEB_AVAILABLE: true,
    RPC_VERIFIED: rpcVerified,
    API_NOT_CONFIGURED: true,
    DEGRADED_READ_ONLY: rpcVerified,
    READY_FOR_READ_ONLY_PREVIEW: rpcVerified,
    READY_FOR_TRANSACTIONS: false,
  };
}
