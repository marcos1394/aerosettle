import type { Verification } from '../config/verify.ts';

export interface StagingReadiness {
  WEB_AVAILABLE: boolean;
  RPC_VERIFIED: boolean;
  API_VERIFIED: boolean;
  INDEX_FRESH: boolean;
  INDEX_STALE: boolean;
  API_UNAVAILABLE: boolean;
  DEGRADED_READ_ONLY: boolean;
  READY_FOR_READ_ONLY_PREVIEW: boolean;
  READY_FOR_TRANSACTIONS: false;
}

export function stagingReadiness(verification: Verification, indexFresh = false): StagingReadiness {
  const rpcVerified = verification.provenance === 'LIVE_DEVNET_READ_ONLY' &&
    (verification.status === 'VERIFIED' || verification.status === 'DEGRADED_READ_ONLY');
  const apiVerified = rpcVerified && verification.status === 'VERIFIED';
  return {
    WEB_AVAILABLE: true,
    RPC_VERIFIED: rpcVerified,
    API_VERIFIED: apiVerified,
    INDEX_FRESH: apiVerified && indexFresh,
    INDEX_STALE: rpcVerified && verification.reason === 'INDEX_STALE',
    API_UNAVAILABLE: rpcVerified && verification.reason === 'API_UNAVAILABLE',
    DEGRADED_READ_ONLY: rpcVerified && !(apiVerified && indexFresh),
    READY_FOR_READ_ONLY_PREVIEW: rpcVerified,
    READY_FOR_TRANSACTIONS: false,
  };
}
