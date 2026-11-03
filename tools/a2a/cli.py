"""Publish a pre-signed Agent Card or serve the public read-only catalog."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .catalog import CardCatalog, DiscoveryIdentitySource
from .cards import MAX_CARD_BYTES
from .service import serve


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("publish", "serve"))
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--rpc-url", required=True)
    parser.add_argument("--idl", type=Path, required=True)
    parser.add_argument("--network", required=True)
    parser.add_argument("--genesis-hash", required=True,
                        help="Expected Solana genesis hash; mismatches fail closed")
    parser.add_argument("--card", type=Path)
    parser.add_argument("--listen", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8089)
    args = parser.parse_args()
    source = DiscoveryIdentitySource(args.rpc_url, args.idl, args.network,
                                     args.genesis_hash)
    catalog = CardCatalog(args.db, source)
    try:
        if args.command == "publish":
            if args.card is None or args.card.stat().st_size > MAX_CARD_BYTES:
                parser.error("A bounded pre-signed --card file is required")
            print(json.dumps(catalog.publish(json.loads(args.card.read_text())), sort_keys=True))
        else:
            serve(catalog, args.listen, args.port)
    finally:
        catalog.close()


if __name__ == "__main__":
    main()
