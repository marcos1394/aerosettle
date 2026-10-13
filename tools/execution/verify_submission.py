#!/usr/bin/env python3
"""AeroSettle: auditoría independiente de Submitted en Localnet."""
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / 'tools/execution'))
import submission_gate as gate

ORDER = os.environ.get(
    'ORDER',
    'EnkZQWDqF5HeFeusZ7xnj7tngVN9xASofmKvXtDLeqbx'
)
PROGRAM = gate.PROGRAM
AGENT = gate.AGENT
DEVICE = gate.DEVICE

EXPECTED_MANIFEST = (
    'b52dd8991db1559e368ca002f829678ace3471ecbb74419d9b67dbf3f2e54e75'
)
EXPECTED_RECEIPT = (
    '990ad257d8ecbaa32a797b220c428ae305c6cdefa724b3448bafc4580c54944e'
)


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def canonical_hash(obj):
    data = json.dumps(
        obj,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':')
    ).encode('utf-8')
    return hashlib.sha256(data).hexdigest()


def main():
    require(
        gate.rpc('getGenesisHash') == gate.GENESIS,
        'Genesis distinto'
    )

    directory = ROOT / '.aerosettle-local/evidence'

    manifest = json.loads(
        (directory / f'{ORDER}.demo-manifest.json').read_text()
    )
    receipt = json.loads(
        (directory / f'{ORDER}.demo-receipt.json').read_text()
    )

    manifest_hash = canonical_hash(manifest)
    receipt_hash = canonical_hash(receipt)

    require(
        manifest_hash == EXPECTED_MANIFEST,
        'Manifest SHA-256 no coincide'
    )
    require(
        receipt_hash == EXPECTED_RECEIPT,
        'Receipt SHA-256 no coincide'
    )
    require(
        receipt.get('evidence_manifest_sha256') == manifest_hash,
        'Recibo no enlaza manifiesto'
    )
    require(
        manifest.get('execution_mode') == 'SYNTHETIC_INTEGRATION_TEST',
        'No es fixture sintético'
    )
    require(
        manifest.get('is_physical_execution') is False,
        'Etiqueta de evidencia inesperada'
    )
    require(
        manifest.get('work_order') == ORDER
        and receipt.get('work_order') == ORDER,
        'Expediente de otra WorkOrder'
    )
    require(
        manifest.get('agent_account') == AGENT
        and receipt.get('agent_account') == AGENT,
        'Agente diferente'
    )

    idl_raw = json.loads(
        (
            ROOT / 'target/idl/aerosettle.discovery.json'
        ).read_text()
    )

    require(
        idl_raw.get('address') == PROGRAM,
        'IDL de otro programa'
    )

    idl = gate.d.Idl(idl_raw)
    raw_order = gate.get_account(ORDER)
    raw_agent = gate.get_account(AGENT)

    require(
        raw_order['owner'] == PROGRAM
        and raw_agent['owner'] == PROGRAM,
        'Owner de cuenta inválido'
    )

    order = idl.decode_account(
        'WorkOrderAccount',
        gate.d.parse_rpc_account(raw_order, PROGRAM)
    )
    agent = idl.decode_account(
        'AgentAccount',
        gate.d.parse_rpc_account(raw_agent, PROGRAM)
    )

    print('=== POST-SUBMISSION AUDIT ===')
    print('WorkOrder:', ORDER)
    print('On-chain status:', order.get('status'))
    print('Execution signer:', order.get('execution_signer'))
    print('Provided evidence:', order.get('provided_evidence'))
    print('Execution sequence:', order.get('execution_sequence'))
    print(
        'Agent next sequence:',
        agent.get('next_signature_sequence')
    )
    print('Manifest hash:', manifest_hash)
    print('Receipt hash:', receipt_hash)

    require(
        order.get('status') == 'Submitted',
        'La orden no está Submitted'
    )
    require(
        order.get('claimed_agent') == AGENT,
        'claimed_agent incorrecto'
    )
    require(
        order.get('execution_signer') == DEVICE,
        'Signer no coincide'
    )
    require(
        agent.get('signing_authority') == DEVICE,
        'Autoridad cambió'
    )
    require(
        int(order.get('provided_evidence')) == 71,
        'Máscara de evidencia distinta'
    )
    require(
        int(order.get('execution_sequence'))
        == int(receipt['signature_sequence']),
        'Secuencia de ejecución distinta del recibo'
    )
    require(
        int(agent.get('next_signature_sequence'))
        == int(receipt['signature_sequence']) + 1,
        'No se incrementó next_signature_sequence'
    )
    require(
        str(order.get('evidence_manifest_hash')).lower()
        == manifest_hash,
        'Hash de manifiesto on-chain distinto'
    )
    require(
        str(order.get('execution_receipt_hash')).lower()
        == receipt_hash,
        'Hash de recibo on-chain distinto'
    )
    require(
        int(order.get('execution_started_at'))
        == int(receipt['execution_started_at']),
        'Execution started_at distinto'
    )
    require(
        int(order.get('execution_ended_at'))
        == int(receipt['execution_ended_at']),
        'Execution ended_at distinto'
    )

    print(
        '✅ Submitted, secuencia e integridad '
        'criptográfica verificadas'
    )
    print('Transacciones enviadas por el auditor: 0')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('❌', exc, file=sys.stderr)
        raise SystemExit(1)
