import { useEffect, useRef, useState } from 'react';
import { useWallet } from '@solana/wallet-adapter-react';
import { useI18n } from '../../app/i18n';
import { short } from '../../app/config';
export function WalletControl() {
  const {
    wallets,
    wallet,
    select,
    connect,
    disconnect,
    connected,
    connecting,
    disconnecting,
    publicKey,
  } = useWallet();
  const { t } = useI18n();
  const dialog = useRef<HTMLDialogElement>(null);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    if (open) dialog.current?.showModal();
    else dialog.current?.close();
  }, [open]);
  const label =
    connected && publicKey
      ? short(publicKey.toBase58())
      : connecting
        ? t('Connecting…')
        : wallet
          ? t('Connect wallet')
          : t('Choose wallet');
  async function act() {
    setError('');
    if (!wallet || connected) {
      setOpen(true);
      return;
    }
    try {
      await connect();
    } catch {
      setError('Wallet connection failed. Try again in your wallet.');
      setOpen(true);
    }
  }
  return (
    <div className="wallet-control">
      <button
        className="wallet-adapter-button wallet-adapter-button-trigger"
        disabled={connecting || disconnecting}
        onClick={() => void act()}
      >
        {label}
      </button>
      <dialog
        className="wallet-dialog"
        ref={dialog}
        onCancel={() => setOpen(false)}
        onClick={(e) => {
          if (e.target === dialog.current) setOpen(false);
        }}
        aria-label={t('Wallet connection')}
      >
        <div className="section-heading">
          <h2>{t(connected ? 'Connected wallet' : 'Choose wallet')}</h2>
          <button
            onClick={() => setOpen(false)}
            aria-label={t('Close wallet dialog')}
          >
            ×
          </button>
        </div>
        {error && <p role="alert">{t(error)}</p>}
        {connected && publicKey ? (
          <>
            <p className="address-full">{publicKey.toBase58()}</p>
            <button
              disabled={disconnecting}
              onClick={async () => {
                try {
                  await disconnect();
                  setOpen(false);
                } catch {
                  setError('Could not disconnect the wallet.');
                }
              }}
            >
              {t('Disconnect wallet')}
            </button>
          </>
        ) : (
          <>
            <p>
              {t(
                'Choose a wallet, then connect explicitly. No transaction is signed by connecting.'
              )}
            </p>
            <div className="wallet-options">
              {wallets
                .filter((w) => w.readyState !== 'Unsupported')
                .map(({ adapter, readyState }) => (
                  <button
                    key={adapter.name}
                    onClick={() => {
                      select(adapter.name);
                      setOpen(false);
                      setError('');
                    }}
                  >
                    <img src={adapter.icon} width="24" height="24" alt="" />
                    <span>
                      {adapter.name === 'AeroSettle Localnet Dev' ||
                      adapter.name === 'Conatus Localnet Dev'
                        ? 'Conatus Device Signer'
                        : adapter.name}
                    </span>
                    <small>{t(readyState)}</small>
                  </button>
                ))}
            </div>
          </>
        )}
      </dialog>
    </div>
  );
}
