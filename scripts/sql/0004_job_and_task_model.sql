-- 0004_job_and_task_model.sql
-- Migration: Introduce unified Job orchestration model + rename legacy tables

BEGIN;

-- ═══════════════════════════════════════════════════════════════
-- 1. Create the `job` table (orchestration parent)
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS job (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES project(id),
    data_source_id UUID NOT NULL REFERENCES data_source(id),
    status VARCHAR(50) NOT NULL,
    start_time TIMESTAMP WITH TIME ZONE NOT NULL,
    end_time TIMESTAMP WITH TIME ZONE,
    total_duration INTEGER
);

CREATE INDEX IF NOT EXISTS ix_job_project_id ON job (project_id);
CREATE INDEX IF NOT EXISTS ix_job_data_source_id ON job (data_source_id);
CREATE INDEX IF NOT EXISTS ix_job_project_data_source ON job (project_id, data_source_id);

-- ═══════════════════════════════════════════════════════════════
-- 2. Rename `diff_sync_job` → `diff_task`
-- ═══════════════════════════════════════════════════════════════
ALTER TABLE IF EXISTS diff_sync_job RENAME TO diff_task;
ALTER INDEX IF EXISTS diff_sync_job_pkey RENAME TO diff_task_pkey;

-- ═══════════════════════════════════════════════════════════════
-- 3. Rename `ingestion_job` → `embed_task`
-- ═══════════════════════════════════════════════════════════════
ALTER TABLE IF EXISTS ingestion_job RENAME TO embed_task;
ALTER INDEX IF EXISTS ingestion_job_pkey RENAME TO embed_task_pkey;
ALTER INDEX IF EXISTS ix_ingestion_job_data_source_status RENAME TO ix_embed_task_data_source_status;

-- ═══════════════════════════════════════════════════════════════
-- 4. Add `job_id` FK to both task tables
-- ═══════════════════════════════════════════════════════════════
ALTER TABLE diff_task ADD COLUMN IF NOT EXISTS job_id UUID REFERENCES job(id);
CREATE INDEX IF NOT EXISTS ix_diff_task_job_id ON diff_task(job_id);

ALTER TABLE embed_task ADD COLUMN IF NOT EXISTS job_id UUID REFERENCES job(id);
CREATE INDEX IF NOT EXISTS ix_embed_task_job_id ON embed_task(job_id);

-- ═══════════════════════════════════════════════════════════════
-- 5. Rename diff_task.error_message → reason (if column exists)
-- ═══════════════════════════════════════════════════════════════
ALTER TABLE diff_task RENAME COLUMN error_message TO reason;

-- ═══════════════════════════════════════════════════════════════
-- 6. Add `reason` column to embed_task (if not exists)
-- ═══════════════════════════════════════════════════════════════
ALTER TABLE embed_task ADD COLUMN IF NOT EXISTS reason VARCHAR;

-- ═══════════════════════════════════════════════════════════════
-- 7. Add start_time index for efficient latest-job queries
-- ═══════════════════════════════════════════════════════════════
CREATE INDEX IF NOT EXISTS ix_job_start_time_desc ON job (start_time DESC);
CREATE INDEX IF NOT EXISTS ix_job_project_start_time ON job (project_id, start_time DESC);
CREATE INDEX IF NOT EXISTS ix_job_ds_start_time ON job (data_source_id, start_time DESC);

COMMIT;
