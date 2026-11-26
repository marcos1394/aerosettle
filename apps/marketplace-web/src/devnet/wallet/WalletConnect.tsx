import { useEffect, useRef, useState } from 'react';
import { useCopy } from '../i18n.tsx';
import { informationalPreview } from './permissions.ts';
import { useWalletIdentity } from './WalletIdentity.tsx';

function short(address: string) { return `${address.slice(0, 5)}…${address.slice(-5)}`; }
const stateLabels = {
  DISCONNECTED: ['Disconnected', 'Desconectada'], DISCOVERING: ['Discovering', 'Buscando'],
  CONNECTING: ['Connecting', 'Conectando'], CONNECTED: ['Connected', 'Conectada'],
  UNSUPPORTED: ['Unsupported', 'No compatible'], WRONG_NETWORK: ['Wrong network', 'Red incompatible'],
  ACCOUNT_CHANGED: ['Select account again', 'Selecciona la cuenta de nuevo'],
  DISCONNECTING: ['Disconnecting', 'Desconectando'], ERROR: ['Connection error', 'Error de conexión'],
} as const;
const warningTranslations = [
  'Wallet Standard no prueba la red activa de la wallet.',
  'No se proporcionaron instrucciones, tarifa, destinatario ni autoridad.',
  'La firma, el envío y la autorización financiera están deshabilitados en CON-54.',
];

export function WalletConnect() {
  const c = useCopy();
  const { session, snapshot } = useWalletIdentity();
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (open && !dialog.current?.open) dialog.current?.showModal();
    if (!open && dialog.current?.open) dialog.current.close();
    return () => dialog.current?.close();
  }, [open]);
  const close = () => { setOpen(false); trigger.current?.focus(); };
  const preview = informationalPreview();
  return <div className="devnet-wallet-control">
    <button ref={trigger} type="button" className="devnet-wallet-trigger" aria-haspopup="dialog"
      onClick={() => setOpen(true)}>
      {snapshot.address ? short(snapshot.address) : c('Connect Wallet', 'Conectar wallet')}
    </button>
    <dialog ref={dialog} className="devnet-wallet-dialog" aria-label={c('Wallet identity', 'Identidad de wallet')}
      onCancel={(event) => { event.preventDefault(); close(); }}
      onClick={(event) => { if (event.target === dialog.current) close(); }}>
      <div className="devnet-wallet-panel">
        <div className="devnet-wallet-heading"><h2>{c('Wallet identity', 'Identidad de wallet')}</h2>
          <button type="button" onClick={close} aria-label={c('Close wallet dialog', 'Cerrar diálogo de wallet')}>×</button></div>
        <p>{c('Connecting shares a public account only. It never grants permission to move funds.',
          'Conectar comparte solo una cuenta pública. Nunca concede permiso para mover fondos.')}</p>
        <p className="devnet-wallet-state" role="status">{c('Status', 'Estado')}: {c(stateLabels[snapshot.status][0], stateLabels[snapshot.status][1])}</p>
        {snapshot.error && <p role="alert">{c('Wallet action did not complete safely. Check the wallet and network, then try again.',
          'La acción no se completó de forma segura. Revisa la wallet y la red antes de reintentar.')}</p>}
        {snapshot.address && <div className="devnet-wallet-address">
          <strong>{c('Public address', 'Dirección pública')}</strong><code>{snapshot.address}</code>
          <button type="button" onClick={async () => {
            try { await navigator.clipboard.writeText(snapshot.address!); setCopied(true); }
            catch { setCopied(false); }
          }}>{copied ? c('Copied', 'Copiada') : c('Copy address', 'Copiar dirección')}</button>
        </div>}
        {snapshot.accounts.length > 1 && !snapshot.address && <fieldset>
          <legend>{c('Select authorized account', 'Selecciona una cuenta autorizada')}</legend>
          {snapshot.accounts.map((account) => <button type="button" key={account.address}
            onClick={() => session.selectAccount(account.address)}>{account.label ?? short(account.address)}</button>)}
        </fieldset>}
        {!snapshot.address && <div className="devnet-wallet-options">
          <h3>{c('Available Wallet Standard apps', 'Apps Wallet Standard disponibles')}</h3>
          {snapshot.wallets.length === 0 && <p>{c('No compatible wallet announced itself in this browser. Install Phantom or Solflare, then reopen this panel.',
            'Ninguna wallet compatible se anunció en este navegador. Instala Phantom o Solflare y vuelve a abrir este panel.')}</p>}
          {snapshot.wallets.map((wallet) => <button type="button" key={wallet.id}
            disabled={!wallet.supported || snapshot.status === 'CONNECTING' || snapshot.status === 'DISCONNECTING'}
            onClick={() => void session.connect(wallet.id)}>
            <span>{wallet.name}</span><small>{wallet.supported ? c('Connect with consent', 'Conectar con permiso') : wallet.reason}</small>
          </button>)}
        </div>}
        {snapshot.walletId && <button type="button" className="devnet-wallet-disconnect"
          disabled={snapshot.status === 'DISCONNECTING'} onClick={() => void session.disconnect()}>
          {c('Disconnect', 'Desconectar')}</button>}
        <div className="devnet-wallet-policy">
          <strong>{c('Network evidence', 'Evidencia de red')}: {snapshot.networkStatus}</strong>
          <p>{c('Wallet Standard can announce Devnet support but cannot prove the active network. No transactions are prepared or signed.',
            'Wallet Standard puede anunciar compatibilidad con Devnet, pero no prueba la red activa. No se preparan ni firman transacciones.')}</p>
          <details><summary>{c('Informational transaction preview', 'Previsualización informativa de transacción')}</summary>
            <dl><dt>{c('Network', 'Red')}</dt><dd>{preview.network}</dd><dt>Program ID</dt><dd>{preview.program_id}</dd>
              <dt>{c('Test mint', 'Mint de prueba')}</dt><dd>{preview.token_mint}</dd>
              <dt>{c('Transaction type', 'Tipo de transacción')}</dt><dd>{preview.transaction_type ?? 'INSUFFICIENT_DATA'}</dd>
              <dt>{c('Estimated fee', 'Tarifa estimada')}</dt><dd>{preview.estimated_fee ?? 'INSUFFICIENT_DATA'}</dd>
              <dt>{c('Requested authority', 'Autoridad solicitada')}</dt><dd>{preview.requested_authority ?? 'INSUFFICIENT_DATA'}</dd>
              <dt>{c('Recipient', 'Destinatario')}</dt><dd>{preview.recipient ?? 'INSUFFICIENT_DATA'}</dd></dl>
            <ul>{preview.risk_warnings.map((warning, index) => <li key={warning}>{c(warning, warningTranslations[index] ?? warning)}</li>)}</ul>
          </details>
          <small>{c('Wallet names are announced by extensions and are not independently authenticated by this site.',
            'Los nombres de wallets son anunciados por extensiones y este sitio no los autentica de forma independiente.')}</small>
        </div>
      </div>
    </dialog>
  </div>;
}
