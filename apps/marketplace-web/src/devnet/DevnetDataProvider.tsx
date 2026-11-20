import { createContext, useCallback, useContext, useEffect, useRef, useState,
  type ReactNode } from 'react';
import { DEVNET_MANIFEST } from '../config/devnet-manifest.ts';
import { createRpc, verifyEnvironmentCore, type Verification } from '../config/verify.ts';
import { verifyDevnetManifest } from '../config/verify-devnet-manifest.ts';
import { VerificationSession } from '../config/session.ts';
import { fetchIndex, fetchReady, type Ready } from './index.ts';
import { parseCatalog, type Catalog } from './catalog.ts';

const RPC = createRpc(DEVNET_MANIFEST.rpc_endpoint);
const initial: Verification = { status: 'VERIFYING', reason: 'CHECKING_RPC',
  observedAt: '', provenance: 'UNVERIFIABLE' };
type State = { verification: Verification; catalog?: Catalog; ready?: Ready;
  reload: () => void; loading: boolean };
const Context = createContext<State | null>(null);
export function useDevnetData(): State {
  const value = useContext(Context);
  if (!value) throw Error('DevnetDataProvider required');
  return value;
}
export function DevnetDataProvider({ children }: { children: ReactNode }) {
  const [verification, setVerification] = useState<Verification>(initial);
  const [catalog, setCatalog] = useState<Catalog>();
  const [ready, setReady] = useState<Ready>();
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const session = useRef(new VerificationSession<{
    verification: Verification; catalog?: Catalog; ready?: Ready }>());
  const reload = useCallback(() => setRevision((value) => value + 1), []);
  useEffect(() => {
    void session.current.run(DEVNET_MANIFEST.manifest_sha256, async (signal) => {
      try {
        const response = await fetch('/idl/devnet-idl.json', { cache: 'no-store', signal });
        if (!response.ok) throw Error('IDL_UNAVAILABLE');
        let ready: Ready | undefined;
        const result = await verifyEnvironmentCore(DEVNET_MANIFEST, await response.text(),
          RPC, async () => {
            ready = await fetchReady(fetch, signal);
            return { status: ready.status === 'ready' ? 'ok' : ready.status,
              genesis: ready.genesis ?? '', program_id: ready.program_id ?? '',
              service: 'con59-pages-read-only' };
          }, signal, verifyDevnetManifest);
        if (result.status !== 'VERIFIED' || !ready) return { verification: result };
        try {
          return { verification: result, catalog: parseCatalog(await fetchIndex(ready, fetch, signal)), ready };
        } catch (cause) {
          const reason = cause instanceof Error ? cause.message : 'INDEX_UNAVAILABLE';
          return { verification: { ...result,
            status: reason.includes('PROVENANCE') || reason.includes('RECORD')
              ? 'NETWORK_MISMATCH' : 'DEGRADED_READ_ONLY', reason } as Verification };
        }
      } catch (cause) {
        return { verification: { ...initial, status: 'UNAVAILABLE',
          reason: cause instanceof Error ? cause.message : 'IDL_UNAVAILABLE',
          observedAt: new Date().toISOString() } as Verification };
      }
    }, (value) => {
      setVerification(value.verification);
      setCatalog(value.catalog);
      setReady(value.ready);
      setLoading(false);
    });
    return () => session.current.invalidate();
  }, [revision]);
  useEffect(() => {
    const interval = window.setInterval(reload, 120_000);
    return () => window.clearInterval(interval);
  }, [reload]);
  useEffect(() => {
    if (!catalog) return;
    const remaining = Date.parse(catalog.expiresAt) - Date.now();
    if (remaining <= 0) { setCatalog(undefined); setReady(undefined); reload(); return; }
    const timeout = window.setTimeout(() => {
      setCatalog(undefined); setReady(undefined); reload();
    }, remaining);
    return () => window.clearTimeout(timeout);
  }, [catalog, reload]);
  return <Context.Provider value={{ verification, catalog, ready, reload, loading }}>
    {children}
  </Context.Provider>;
}
