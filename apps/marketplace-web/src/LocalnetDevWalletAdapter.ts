import { Buffer } from 'buffer';

import {
  BaseSignerWalletAdapter,
  WalletConnectionError,
  WalletNotConnectedError,
  WalletReadyState,
  WalletSignTransactionError,
  type WalletName,
} from '@solana/wallet-adapter-base';

import {
  PublicKey,
  Transaction,
  type VersionedTransaction,
} from '@solana/web3.js';

const GENESIS =
  'HP9XKTusRPGC78EFDpR9xdEq6simL2vqyDdrMvn6Vacg';

export class LocalnetDevWalletAdapter
  extends BaseSignerWalletAdapter {

  readonly name =
    'AeroSettle Localnet Dev' as WalletName<
      'AeroSettle Localnet Dev'
    >;

  readonly url = 'http://127.0.0.1:5173';

  readonly icon = `data:image/svg+xml,${encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">' +
    '<rect width="64" height="64" rx="16" fill="#111827"/>' +
    '<path d="M12 46 32 12 52 46H40L32 31 24 46Z" fill="#34e6bc"/>' +
    '</svg>'
  )}`;

  readonly supportedTransactionVersions = null;

  private key: PublicKey | null = null;
  private pending = false;

  get publicKey(): PublicKey | null {
    return this.key;
  }

  get connecting(): boolean {
    return this.pending;
  }

  get readyState(): WalletReadyState {
    return (
      import.meta.env.DEV &&
      window.location.hostname === '127.0.0.1'
    )
      ? WalletReadyState.Installed
      : WalletReadyState.Unsupported;
  }

  async connect(): Promise<void> {
    if (this.connected || this.pending) return;

    if (this.readyState !== WalletReadyState.Installed) {
      throw new WalletConnectionError(
        'Localnet Dev sólo está disponible en desarrollo'
      );
    }

    this.pending = true;

    try {
      const response = await fetch(
        '/dev-signer/public-key',
        { cache: 'no-store' }
      );

      if (!response.ok) {
        throw new Error(
          'Servicio Localnet Dev Signer no disponible'
        );
      }

      const info = await response.json();

      if (
        info.genesis !== GENESIS ||
        info.network !== 'localnet'
      ) {
        throw new Error(
          'La wallet de desarrollo pertenece a otra red'
        );
      }

      this.key = new PublicKey(info.publicKey);

      this.emit('connect', this.key);

    } catch (error) {
      throw new WalletConnectionError(
        error instanceof Error
          ? error.message
          : String(error)
      );

    } finally {
      this.pending = false;
    }
  }

  async disconnect(): Promise<void> {
    this.key = null;
    this.emit('disconnect');
  }

  async signTransaction<
    T extends Transaction | VersionedTransaction
  >(transaction: T): Promise<T> {

    if (!this.key) {
      throw new WalletNotConnectedError();
    }

    if (!(transaction instanceof Transaction)) {
      throw new WalletSignTransactionError(
        'El firmante local sólo admite transacciones legacy'
      );
    }

    if (!transaction.feePayer?.equals(this.key)) {
      throw new WalletSignTransactionError(
        'Fee payer diferente de la wallet conectada'
      );
    }

    const expectedMessage = Buffer.from(
      transaction.serializeMessage()
    ).toString('base64');

    const unsigned = Buffer.from(
      transaction.serialize({
        requireAllSignatures: false,
        verifySignatures: false,
      })
    ).toString('base64');

    const response = await fetch(
      '/dev-signer/sign',
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-AeroSettle-Dev-Signer': 'localnet-v1',
        },
        body: JSON.stringify({
          transaction: unsigned,
        }),
      }
    );

    const result = await response.json();

    if (!response.ok) {
      throw new WalletSignTransactionError(
        result.error ?? 'Firma local rechazada'
      );
    }

    const signed = Transaction.from(
      Buffer.from(
        result.signedTransaction,
        'base64'
      )
    );

    const actualMessage = Buffer.from(
      signed.serializeMessage()
    ).toString('base64');

    if (
      actualMessage !== expectedMessage ||
      !signed.feePayer?.equals(this.key) ||
      !signed.verifySignatures()
    ) {
      throw new WalletSignTransactionError(
        'La transacción firmada no coincide con la original'
      );
    }

    return signed as T;
  }
}
