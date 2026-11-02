"""CON-37 read-only Devnet historical consumer gate; no transaction submission.

Usage: python3 -m tools.integration.devnet.verify_ingestion LEDGER.sqlite RESULT.json
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import sys

from tools.economic_ledger.devnet_ingestion import DevnetIngestor, Scope

ROOT = Path(__file__).resolve().parents[3]
CON36 = ROOT / "evidence/con36"
FROM_SLOT = 516889000
TO_SLOT = 517616000


def counts(db_path: Path) -> tuple[int, int, int]:
    with sqlite3.connect(db_path) as db:
        return (
            db.execute("SELECT count(*) FROM economic_movements").fetchone()[0],
            db.execute("SELECT count(*) FROM ingestion_effects").fetchone()[0],
            db.execute("SELECT count(*) FROM ingestion_observations").fetchone()[0],
        )


def verify(db_path: Path, output_path: Path) -> dict:
    if db_path.resolve() == output_path.resolve():
        raise ValueError("Ledger and evidence paths must differ")
    inventory = json.loads((CON36 / "scenario-plan.json").read_text())
    expected = json.loads((CON36 / "verified-matrix.json").read_text())
    scenarios = inventory["scenarios"]
    if len(scenarios) != 7 or len(expected["receipts"]) != 7:
        raise AssertionError("CON-36 historical fixture is incomplete")
    scopes = [Scope(s["work_order_pda"], FROM_SLOT, TO_SLOT) for s in scenarios]
    db_path.parent.mkdir(parents=True, exist_ok=True)

    consumer = DevnetIngestor(db_path)
    try:
        initial = [consumer.sync(scope, page_size=100, max_pages=2,
                                 max_signatures=50) for scope in scopes]
        if any(report["checkpoint"]["checkpoint_status"] != "READY" or
               report["metrics"]["reconciled"] != 1 or report["incidents"]
               for report in initial):
            raise AssertionError("First historical ingestion did not reconcile seven settlements")
        if counts(db_path)[:2] != (7, 14):
            raise AssertionError("First ingestion did not create seven movements and fourteen effects")
        repeated = consumer.sync(scopes[0], replay=True, page_size=100,
                                 max_pages=2, max_signatures=50)
        if repeated["metrics"]["reconciled"] != 1 or repeated["metrics"]["duplicates"] < 1:
            raise AssertionError("Immediate replay did not deduplicate")
    finally:
        consumer.close()

    def concurrent_resume(scope: Scope) -> dict:
        worker = DevnetIngestor(db_path)
        try:
            return worker.sync(scope, page_size=100,
                               max_pages=2, max_signatures=50)
        finally:
            worker.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(concurrent_resume, scopes[0]) for _ in range(2)]
        concurrent = [future.result() for future in futures]
    if any(row["checkpoint"]["checkpoint_status"] != "READY" or
           row["metrics"]["discovered"] != 0 or row["incidents"]
           for row in concurrent) or counts(db_path)[:2] != (7, 14):
        raise AssertionError("Concurrent consumers duplicated or lost an effect")

    restarted = DevnetIngestor(db_path)
    try:
        resumed = [restarted.sync(scope, page_size=100, max_pages=2,
                                  max_signatures=50) for scope in scopes]
        if any(report["metrics"]["discovered"] != 0 or
               report["checkpoint"]["checkpoint_status"] != "READY"
               for report in resumed):
            raise AssertionError("SQLite restart lost a checkpoint")
        reread = [restarted.sync(scope, replay=True, page_size=100,
                                 max_pages=2, max_signatures=50) for scope in scopes]
        if any(report["metrics"]["reconciled"] != 1 or
               report["metrics"]["duplicates"] < 1 or report["incidents"]
               for report in reread):
            raise AssertionError("Historical RPC reread changed a reconciled effect")
        if counts(db_path)[:2] != (7, 14):
            raise AssertionError("Replay after restart duplicated Economic Ledger rows")

        normalized = []
        for scenario, report, prior in zip(scenarios, reread, expected["receipts"], strict=True):
            observations = [o for o in report["observations"]
                            if o["processing_status"] == "RECONCILED"]
            effects = report["effects"]
            payout = next(e for e in effects if e["effect_kind"] == "operator_payout")
            refund = next(e for e in effects if e["effect_kind"] == "creator_refund")
            if (len(observations) != 1 or len(effects) != 2 or
                    observations[0]["signature"] != prior["transaction_signature"] or
                    observations[0]["slot"] != prior["slot"] or
                    observations[0]["evidence_hash"] != prior["evidence_hash"] or
                    payout["amount_base_units"] != prior["operator_payout"] or
                    refund["amount_base_units"] != prior["creator_refund"] or
                    not payout["movement_id"] or refund["movement_id"] is not None):
                raise AssertionError(f"CON-36 receipt mismatch: {scenario['scenario']}")
            movement = restarted.ledger.get_by_idempotency_key(prior["effect_id"])
            if not movement or movement.evidence_hash != prior["evidence_hash"] or \
                    movement.movement_id != payout["movement_id"] or \
                    movement.status.value != "RECONCILED":
                raise AssertionError("Existing ledger effect differs from CON-36 evidence")
            normalized.append({"scenario": scenario["scenario"],
                               "signature": prior["transaction_signature"],
                               "slot": prior["slot"], "effect_id": prior["effect_id"],
                               "evidence_hash": prior["evidence_hash"],
                               "operator_payout": payout["amount_base_units"],
                               "creator_refund": refund["amount_base_units"],
                               "operator_destination": payout["destination_account"],
                               "refund_destination": refund["destination_account"],
                               "status": movement.status.value,
                               "provenance": prior["provenance"]})
    finally:
        restarted.close()

    movement_count, effect_count, observation_count = counts(db_path)
    result = {"network": inventory["network"],
              "genesis_hash": inventory["genesis_hash"],
              "program_id": inventory["program_id"],
              "mint": inventory["mint_pubkey"],
              "scenario_count": len(scopes),
              "movement_count": movement_count,
              "effect_count": effect_count,
              "observation_count": observation_count,
              "immediate_replay_idempotent": True,
              "concurrent_replay_idempotent": True,
              "sqlite_restart_idempotent": True,
              "historical_rpc_reread_idempotent": True,
              "receipts": normalized}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    return result


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python3 -m tools.integration.devnet.verify_ingestion LEDGER.sqlite RESULT.json")
    result = verify(Path(sys.argv[1]), Path(sys.argv[2]))
    print(json.dumps({key: value for key, value in result.items() if key != "receipts"},
                     sort_keys=True))


if __name__ == "__main__":
    main()
