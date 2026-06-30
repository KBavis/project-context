BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

DROP TABLE IF EXISTS project_repository_changes CASCADE;
DROP TABLE IF EXISTS project_repository_file_history CASCADE;
DROP TABLE IF EXISTS project_repository_file_pr_diff CASCADE;
DROP TABLE IF EXISTS project_repo_summary CASCADE;
DROP TABLE IF EXISTS project_affected_file CASCADE;
DROP TABLE IF EXISTS project_file_diff CASCADE;

CREATE TABLE project_repo_summary (
    project_id UUID NOT NULL,
    data_source_id UUID NOT NULL,
    diff_sync_job_id UUID,
    file_count INTEGER NOT NULL DEFAULT 0,
    last_synced_time TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (project_id, data_source_id),
    CONSTRAINT fk_project_repo_summary_project_data FOREIGN KEY (project_id, data_source_id) REFERENCES project_data (project_id, data_source_id)
);

CREATE TABLE project_affected_file (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL,
    data_source_id UUID NOT NULL,
    file_path VARCHAR NOT NULL,
    change_type change_type_enum NOT NULL,
    diff_sync_job_id UUID,
    CONSTRAINT fk_project_affected_file_repo_summary FOREIGN KEY (project_id, data_source_id) REFERENCES project_repo_summary (project_id, data_source_id) DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_project_affected_file_diff_sync_job FOREIGN KEY (diff_sync_job_id) REFERENCES diff_sync_job (id),
    CONSTRAINT uq_project_affected_file_path UNIQUE (project_id, data_source_id, file_path)
);
CREATE INDEX ix_project_affected_file_project_id ON project_affected_file (project_id);
CREATE INDEX ix_project_affected_file_data_source_id ON project_affected_file (data_source_id);
CREATE INDEX ix_project_affected_file_diff_sync_job_id ON project_affected_file (diff_sync_job_id);

CREATE TABLE project_file_diff (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_history_id UUID NOT NULL,
    pull_request_id UUID NOT NULL,
    ordinal INTEGER NOT NULL,
    change_type change_type_enum NOT NULL,
    unified_diff TEXT,
    diff_hash VARCHAR(64) NOT NULL,
    diff_truncated BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT fk_project_file_diff_file_history FOREIGN KEY (file_history_id) REFERENCES project_affected_file (id) ON DELETE CASCADE,
    CONSTRAINT fk_project_file_diff_pull_request FOREIGN KEY (pull_request_id) REFERENCES pull_request (id) ON DELETE CASCADE,
    CONSTRAINT uq_project_file_diff_history_pr UNIQUE (file_history_id, pull_request_id)
);
CREATE INDEX ix_project_file_diff_file_history_id ON project_file_diff (file_history_id);
CREATE INDEX ix_project_file_diff_pull_request_id ON project_file_diff (pull_request_id);

COMMIT;
