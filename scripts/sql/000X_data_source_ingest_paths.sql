-- Add ingest_paths column to data_source table
-- Optional list of repo-root-relative directory prefixes to scope ingestion.
-- Empty array (default) = ingest the entire repository (backward compatible).
ALTER TABLE data_source
    ADD COLUMN IF NOT EXISTS ingest_paths TEXT[] NOT NULL DEFAULT '{}';
