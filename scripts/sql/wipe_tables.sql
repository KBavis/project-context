DELETE FROM file;
DELETE FROM file_collection;
DELETE FROM execution_token_usage;
DELETE FROM record_lock;
DELETE FROM data_source_mcp_config;
DELETE FROM data_chunks_docstore;
DELETE FROM project_data;
DELETE FROM message;
DELETE FROM conversation;
DELETE FROM project;
DELETE FROM chroma_collection;
DELETE FROM ingestion_job;
DELETE FROM data_source;
DELETE FROM mcp_config;

\echo ''
\echo '======================================================================='
\echo 'WARNING: Please remember to delete the Chroma Collection directly from Chroma!'
\echo '======================================================================='
\echo ''
