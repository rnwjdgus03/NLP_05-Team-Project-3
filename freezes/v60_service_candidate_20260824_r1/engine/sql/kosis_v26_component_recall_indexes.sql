-- v26 structured Stage-A recall. Safe to execute repeatedly.
-- These indexes keep literal ITEM/OBJ lookup bounded without vectorizing the
-- 9.6M coordinate metadata rows.
CREATE INDEX IF NOT EXISTS idx_kosis_items_lower_name_pattern
    ON kosis_items (lower(item_name) text_pattern_ops, org_id, tbl_id);

CREATE INDEX IF NOT EXISTS idx_kosis_axis_values_lower_name_pattern
    ON kosis_axis_values (lower(value_name) text_pattern_ops, org_id, tbl_id);

CREATE INDEX IF NOT EXISTS idx_kosis_items_name_fts_simple
    ON kosis_items USING gin (to_tsvector('simple', COALESCE(item_name, '')));

CREATE INDEX IF NOT EXISTS idx_kosis_axis_values_name_fts_simple
    ON kosis_axis_values USING gin (to_tsvector('simple', COALESCE(value_name, '')));
