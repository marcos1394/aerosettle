-- Migration 008: Persistent immutable evidence lineage for economic movements and agent costs.

ALTER TABLE economic_movements ADD COLUMN evidence_lineage TEXT NOT NULL DEFAULT 'HISTORICAL_UNVERIFIED';
ALTER TABLE agent_costs ADD COLUMN evidence_lineage TEXT NOT NULL DEFAULT 'HISTORICAL_UNVERIFIED';

UPDATE economic_movements
SET evidence_lineage = json_extract(metadata_json, '$.evidence_lineage')
WHERE metadata_json IS NOT NULL
  AND json_extract(metadata_json, '$.evidence_lineage') IN ('LIVE_RPC', 'EXTERNAL_ATTESTED', 'HISTORICAL_FIXTURE', 'SYNTHETIC_TEST', 'HISTORICAL_UNVERIFIED');

UPDATE agent_costs
SET evidence_lineage = json_extract(metadata_json, '$.evidence_lineage')
WHERE metadata_json IS NOT NULL
  AND json_extract(metadata_json, '$.evidence_lineage') IN ('LIVE_RPC', 'EXTERNAL_ATTESTED', 'HISTORICAL_FIXTURE', 'SYNTHETIC_TEST', 'HISTORICAL_UNVERIFIED');
