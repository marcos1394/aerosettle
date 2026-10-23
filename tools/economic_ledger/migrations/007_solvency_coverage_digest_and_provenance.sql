-- Migration 007: Solvency coverage canonical data digest, authority authentication, and persistent provenance.

ALTER TABLE solvency_coverage ADD COLUMN data_digest TEXT NOT NULL DEFAULT '';
ALTER TABLE solvency_coverage ADD COLUMN provenance_type TEXT NOT NULL DEFAULT 'HISTORICAL_UNVERIFIED';
ALTER TABLE solvency_coverage ADD COLUMN authority_pubkey TEXT;
ALTER TABLE solvency_coverage ADD COLUMN signature TEXT;
ALTER TABLE solvency_coverage ADD COLUMN expires_at INTEGER;

ALTER TABLE agent_solvency_assessments ADD COLUMN provenance_type TEXT NOT NULL DEFAULT 'HISTORICAL_UNVERIFIED';

-- Existing coverage records lacking a verified data_digest are marked HISTORICAL_UNVERIFIED.
-- They will be treated as invalid/pending in solvency assessments.
UPDATE solvency_coverage SET provenance_type = 'HISTORICAL_UNVERIFIED' WHERE data_digest = '' OR data_digest IS NULL;
