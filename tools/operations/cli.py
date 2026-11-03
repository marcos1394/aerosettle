"""CON-38 local operational CLI. No signing or transaction submission imports."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

from tools.economic_ledger.devnet_ingestion import ROOT
from .structured_logs import emit, new_trace_id
from .rpc_policy import ProviderController, monitored_client
from .service import (
    collect_ledger, evaluate_alerts, health, inspect_security,
    install_rules, load_config, operational_report, publish_rpc_summary,
    readiness,
)
from .store import OperationalStore


def run(argv: list[str] | None = None) -> tuple[dict, int]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("health", "readiness", "inspect",
                                           "metrics", "alerts", "incidents", "report"))
    parser.add_argument("--db", type=Path, default=ROOT / "target/con38/operations.sqlite")
    parser.add_argument("--ledger-db", type=Path,
                        default=ROOT / "target/con37/devnet-ledger.sqlite")
    parser.add_argument("--config", type=Path,
                        default=ROOT / "tools/operations/devnet.json")
    parser.add_argument("--window-seconds", type=int, default=300)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if not 60 <= args.window_seconds <= 86400:
        parser.error("window-seconds must be between 60 and 86400")
    trace = new_trace_id()
    if args.command == "health":
        result = health()
        emit("INFO", "devnet_operations", "health", trace_id=trace,
             status=result["status"])
        return result, 0
    config = load_config(args.config)
    store = OperationalStore(args.db)
    try:
        install_rules(store, config)
        store.prune_samples(int(time.time()) - config["sample_retention_seconds"])
        controller = ProviderController(store, provider_id=config["provider_id"],
            max_requests_per_minute=config["rpc"]["max_requests_per_minute"],
            max_concurrency=config["rpc"]["max_concurrency"],
            failure_threshold=config["rpc"]["failure_threshold"],
            cooldown_seconds=config["rpc"]["cooldown_seconds"])
        client = monitored_client(store, controller,
            timeout=config["rpc"]["timeout_seconds"],
            retry_budget=config["rpc"]["retry_budget"],
            min_interval=config["rpc"]["min_interval_seconds"])
        if args.command == "readiness":
            result = readiness(store, client, config, args.ledger_db)
            code = {"HEALTHY": 0, "DEGRADED": 1,
                    "NOT_READY": 2, "UNHEALTHY": 2}[result["status"]]
        elif args.command == "inspect":
            result = {"identity_checks": inspect_security(client, store, config),
                      "provider": controller.state()}
            code = 0 if all(item["status"] == "MATCH" for item in
                            result["identity_checks"].values()) else 2
        elif args.command == "metrics":
            result = {"ledger": collect_ledger(store, args.ledger_db, config=config),
                      "rpc": publish_rpc_summary(store, window_seconds=args.window_seconds)}
            code = 0
        elif args.command == "alerts":
            identity = inspect_security(client, store, config)
            ledger = collect_ledger(store, args.ledger_db, config=config)
            publish_rpc_summary(store, window_seconds=args.window_seconds)
            evaluated = evaluate_alerts(store)
            result = {"identity_checks": identity, "ledger": ledger["status"],
                      "evaluated": evaluated, "alerts": store.alerts()}
            code = 2 if any(row["state"] == "OPEN" and row["severity"] == "CRITICAL"
                            for row in result["alerts"]) else 0
        elif args.command == "incidents":
            result = {"alerts": store.alerts(), "events": store.incidents()}
            code = 0
        else:
            result = operational_report(store, args.ledger_db,
                                        window_seconds=args.window_seconds)
            code = 0
        emit("INFO" if code == 0 else "WARNING", "devnet_operations",
             args.command, trace_id=trace, status=result.get("status", "COMPLETE"),
             network=config["network"], genesis_hash=config["genesis_hash"],
             program_id=config["program_id"])
        return result, code
    finally:
        store.close()


def main() -> None:
    try:
        result, code = run()
        output = json.dumps(result, sort_keys=True, indent=2) + "\n"
        if "--output" in sys.argv:
            target = Path(sys.argv[sys.argv.index("--output") + 1])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(output)
        print(output, end="")
        raise SystemExit(code)
    except (ValueError, OSError, RuntimeError) as exc:
        # Only the exception type is exposed; untrusted RPC URLs/bodies may contain secrets.
        print(json.dumps({"status": "UNHEALTHY", "error_code": type(exc).__name__}),
              file=sys.stdout)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
