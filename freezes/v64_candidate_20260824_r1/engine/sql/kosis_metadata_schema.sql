BEGIN;

SELECT pg_advisory_xact_lock(hashtext('kosis_metadata_snapshot'));

CREATE TABLE IF NOT EXISTS kosis_metadata_snapshots (
    snapshot_id UUID PRIMARY KEY,
    source_sqlite_sha256 CHAR(64) NOT NULL
        CHECK (source_sqlite_sha256 ~ '^[0-9a-f]{64}$'),
    semantic_tables_sha256 CHAR(64) NOT NULL
        CHECK (semantic_tables_sha256 ~ '^[0-9a-f]{64}$'),
    collected_at TIMESTAMPTZ NOT NULL,
    migrated_at TIMESTAMPTZ NOT NULL,
    row_counts JSONB NOT NULL DEFAULT '{}'::JSONB,
    parent_snapshot_id UUID,
    hydration_sha256 CHAR(64)
        CHECK (hydration_sha256 IS NULL OR hydration_sha256 ~ '^[0-9a-f]{64}$'),
    source_kind TEXT NOT NULL DEFAULT 'sqlite_import',
    is_active BOOLEAN NOT NULL DEFAULT FALSE
);

ALTER TABLE kosis_metadata_snapshots
    ADD COLUMN IF NOT EXISTS parent_snapshot_id UUID;
ALTER TABLE kosis_metadata_snapshots
    ADD COLUMN IF NOT EXISTS hydration_sha256 CHAR(64);
ALTER TABLE kosis_metadata_snapshots
    ADD COLUMN IF NOT EXISTS source_kind TEXT NOT NULL DEFAULT 'sqlite_import';

CREATE UNIQUE INDEX IF NOT EXISTS uq_kosis_metadata_snapshots_active
    ON kosis_metadata_snapshots (is_active) WHERE is_active;

CREATE TABLE IF NOT EXISTS kosis_tables (
    org_id TEXT NOT NULL,
    tbl_id TEXT NOT NULL,
    tbl_name TEXT NOT NULL DEFAULT '',
    category_path TEXT NOT NULL DEFAULT '',
    search_document TEXT NOT NULL DEFAULT '',
    unit_hints TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    metadata_version TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (org_id, tbl_id)
);

-- Immutable table labels for every metadata snapshot.  The normalized tables
-- below remain replaceable, while retrieval audit rows always reference this
-- snapshot-scoped catalog.
CREATE TABLE IF NOT EXISTS kosis_snapshot_tables (
    snapshot_id UUID NOT NULL,
    org_id TEXT NOT NULL,
    tbl_id TEXT NOT NULL,
    tbl_name TEXT NOT NULL DEFAULT '',
    category_path TEXT NOT NULL DEFAULT '',
    search_document TEXT NOT NULL DEFAULT '',
    unit_hints TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    metadata_version TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (snapshot_id, org_id, tbl_id),
    FOREIGN KEY (snapshot_id)
        REFERENCES kosis_metadata_snapshots (snapshot_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS kosis_items (
    org_id TEXT NOT NULL,
    tbl_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    item_name TEXT NOT NULL DEFAULT '',
    parent_item_id TEXT NOT NULL DEFAULT '',
    unit_id TEXT NOT NULL DEFAULT '',
    unit_name TEXT NOT NULL DEFAULT '',
    unit_eng_name TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (org_id, tbl_id, item_id),
    FOREIGN KEY (org_id, tbl_id)
        REFERENCES kosis_tables (org_id, tbl_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS kosis_axes (
    org_id TEXT NOT NULL,
    tbl_id TEXT NOT NULL,
    axis_id TEXT NOT NULL,
    axis_name TEXT NOT NULL DEFAULT '',
    axis_order INTEGER NOT NULL CHECK (axis_order > 0),
    PRIMARY KEY (org_id, tbl_id, axis_id),
    FOREIGN KEY (org_id, tbl_id)
        REFERENCES kosis_tables (org_id, tbl_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS kosis_axis_values (
    org_id TEXT NOT NULL,
    tbl_id TEXT NOT NULL,
    axis_id TEXT NOT NULL,
    value_id TEXT NOT NULL,
    value_name TEXT NOT NULL DEFAULT '',
    parent_value_id TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (org_id, tbl_id, axis_id, value_id),
    FOREIGN KEY (org_id, tbl_id, axis_id)
        REFERENCES kosis_axes (org_id, tbl_id, axis_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS kosis_periodicities (
    org_id TEXT NOT NULL,
    tbl_id TEXT NOT NULL,
    prd_se TEXT NOT NULL,
    range_text TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (org_id, tbl_id, prd_se),
    FOREIGN KEY (org_id, tbl_id)
        REFERENCES kosis_tables (org_id, tbl_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS retrieval_runs (
    run_id UUID PRIMARY KEY,
    snapshot_id UUID NOT NULL,
    query_id TEXT NOT NULL,
    query_json JSONB NOT NULL DEFAULT '{}'::JSONB,
    retrieval_config JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (run_id, query_id),
    UNIQUE (run_id, query_id, snapshot_id),
    FOREIGN KEY (snapshot_id)
        REFERENCES kosis_metadata_snapshots (snapshot_id) ON DELETE RESTRICT
);

-- Upgrade development databases created before retrieval snapshot pinning.
ALTER TABLE retrieval_runs ADD COLUMN IF NOT EXISTS snapshot_id UUID;
UPDATE retrieval_runs
SET snapshot_id = (
    SELECT snapshot_id FROM kosis_metadata_snapshots WHERE is_active
)
WHERE snapshot_id IS NULL;
ALTER TABLE retrieval_runs ALTER COLUMN snapshot_id SET NOT NULL;
ALTER TABLE retrieval_runs
    DROP CONSTRAINT IF EXISTS retrieval_runs_snapshot_id_fkey;
ALTER TABLE retrieval_runs
    DROP CONSTRAINT IF EXISTS fk_retrieval_runs_snapshot;
ALTER TABLE retrieval_runs
    ADD CONSTRAINT fk_retrieval_runs_snapshot
    FOREIGN KEY (snapshot_id)
    REFERENCES kosis_metadata_snapshots (snapshot_id) ON DELETE RESTRICT;

CREATE TABLE IF NOT EXISTS retrieval_candidates (
    run_id UUID NOT NULL,
    query_id TEXT NOT NULL,
    snapshot_id UUID NOT NULL,
    rank SMALLINT NOT NULL CHECK (rank BETWEEN 1 AND 3),
    org_id TEXT NOT NULL,
    tbl_id TEXT NOT NULL,
    lexical_rank INTEGER CHECK (lexical_rank IS NULL OR lexical_rank > 0),
    dense_rank INTEGER CHECK (dense_rank IS NULL OR dense_rank > 0),
    fusion_score DOUBLE PRECISION,
    reranker_score DOUBLE PRECISION NOT NULL,
    score_json JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (run_id, query_id, rank),
    UNIQUE (run_id, query_id, org_id, tbl_id),
    FOREIGN KEY (run_id, query_id)
        REFERENCES retrieval_runs (run_id, query_id) ON DELETE CASCADE
);

-- Idempotent upgrade for databases that predate immutable snapshot catalogs.
-- The active snapshot gets a complete catalog; historical candidate keys get
-- the best label still available, or a deliberately blank audit placeholder.
INSERT INTO kosis_snapshot_tables
    (snapshot_id,org_id,tbl_id,tbl_name,category_path,search_document,
     unit_hints,metadata_version,updated_at)
SELECT target_snapshot.snapshot_id, table_meta.org_id, table_meta.tbl_id,
       table_meta.tbl_name, table_meta.category_path, table_meta.search_document,
       table_meta.unit_hints, table_meta.metadata_version, table_meta.updated_at
FROM kosis_metadata_snapshots target_snapshot
JOIN kosis_metadata_snapshots active_snapshot
  ON active_snapshot.is_active
 AND active_snapshot.semantic_tables_sha256 = target_snapshot.semantic_tables_sha256
CROSS JOIN kosis_tables table_meta
ON CONFLICT (snapshot_id,org_id,tbl_id) DO NOTHING;

INSERT INTO kosis_snapshot_tables
    (snapshot_id,org_id,tbl_id,tbl_name,category_path,search_document,
     unit_hints,metadata_version,updated_at)
SELECT DISTINCT retrieval_run.snapshot_id, candidate.org_id, candidate.tbl_id,
       COALESCE(table_meta.tbl_name, ''), COALESCE(table_meta.category_path, ''),
       COALESCE(table_meta.search_document, ''),
       COALESCE(table_meta.unit_hints, ARRAY[]::TEXT[]),
       COALESCE(table_meta.metadata_version, ''),
       COALESCE(table_meta.updated_at, retrieval_run.created_at)
FROM retrieval_candidates candidate
JOIN retrieval_runs retrieval_run
  ON retrieval_run.run_id = candidate.run_id
 AND retrieval_run.query_id = candidate.query_id
LEFT JOIN kosis_tables table_meta USING (org_id, tbl_id)
ON CONFLICT (snapshot_id,org_id,tbl_id) DO NOTHING;

-- Remove the dependent FK before rebuilding its referenced uniqueness.  This
-- ordering makes the migration safe to run repeatedly on an already-upgraded DB.
ALTER TABLE retrieval_candidates
    DROP CONSTRAINT IF EXISTS fk_retrieval_candidates_run_snapshot;
ALTER TABLE retrieval_runs
    DROP CONSTRAINT IF EXISTS uq_retrieval_runs_snapshot_identity;
ALTER TABLE retrieval_runs
    ADD CONSTRAINT uq_retrieval_runs_snapshot_identity
    UNIQUE (run_id, query_id, snapshot_id);

ALTER TABLE retrieval_candidates ADD COLUMN IF NOT EXISTS snapshot_id UUID;
UPDATE retrieval_candidates candidate
SET snapshot_id = retrieval_run.snapshot_id
FROM retrieval_runs retrieval_run
WHERE candidate.run_id = retrieval_run.run_id
  AND candidate.query_id = retrieval_run.query_id
  AND candidate.snapshot_id IS NULL;
ALTER TABLE retrieval_candidates ALTER COLUMN snapshot_id SET NOT NULL;

ALTER TABLE retrieval_candidates
    DROP CONSTRAINT IF EXISTS retrieval_candidates_org_id_tbl_id_fkey;
ALTER TABLE retrieval_candidates
    DROP CONSTRAINT IF EXISTS fk_retrieval_candidates_table;
ALTER TABLE retrieval_candidates
    DROP CONSTRAINT IF EXISTS fk_retrieval_candidates_run_snapshot;
ALTER TABLE retrieval_candidates
    DROP CONSTRAINT IF EXISTS fk_retrieval_candidates_snapshot_table;
ALTER TABLE retrieval_candidates
    ADD CONSTRAINT fk_retrieval_candidates_run_snapshot
    FOREIGN KEY (run_id, query_id, snapshot_id)
    REFERENCES retrieval_runs (run_id, query_id, snapshot_id) ON DELETE CASCADE;
ALTER TABLE retrieval_candidates
    ADD CONSTRAINT fk_retrieval_candidates_snapshot_table
    FOREIGN KEY (snapshot_id, org_id, tbl_id)
    REFERENCES kosis_snapshot_tables (snapshot_id, org_id, tbl_id)
    ON DELETE RESTRICT;

CREATE INDEX IF NOT EXISTS idx_kosis_tables_name
    ON kosis_tables (tbl_name);
CREATE INDEX IF NOT EXISTS idx_kosis_tables_category
    ON kosis_tables (category_path);
CREATE INDEX IF NOT EXISTS idx_kosis_tables_search_document_fts
    ON kosis_tables USING GIN (to_tsvector('simple', search_document));
CREATE INDEX IF NOT EXISTS idx_kosis_items_table_name
    ON kosis_items (org_id, tbl_id, item_name);
CREATE INDEX IF NOT EXISTS idx_kosis_items_name_prefix
    ON kosis_items (lower(item_name) text_pattern_ops, org_id, tbl_id);
CREATE INDEX IF NOT EXISTS idx_kosis_items_name_fts
    ON kosis_items USING GIN (to_tsvector('simple', COALESCE(item_name, '')));
CREATE INDEX IF NOT EXISTS idx_kosis_axes_table_order
    ON kosis_axes (org_id, tbl_id, axis_order, axis_id);
CREATE INDEX IF NOT EXISTS idx_kosis_axis_values_table_name
    ON kosis_axis_values (org_id, tbl_id, value_name);
CREATE INDEX IF NOT EXISTS idx_kosis_periodicities_table
    ON kosis_periodicities (org_id, tbl_id, prd_se);
CREATE INDEX IF NOT EXISTS idx_retrieval_runs_query_created
    ON retrieval_runs (query_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_retrieval_candidates_query_rank
    ON retrieval_candidates (query_id, rank);
CREATE INDEX IF NOT EXISTS idx_kosis_snapshot_tables_name
    ON kosis_snapshot_tables (snapshot_id, tbl_name);
CREATE INDEX IF NOT EXISTS idx_kosis_snapshot_tables_search_document_fts
    ON kosis_snapshot_tables USING GIN
    (to_tsvector('simple', search_document));
CREATE INDEX IF NOT EXISTS idx_kosis_metadata_snapshots_migrated
    ON kosis_metadata_snapshots (migrated_at DESC);

COMMIT;
