import { useState, useEffect } from 'react';
import { useDataSources, useAlert, useProjects, useIngestionJobs } from '../contexts/index';
import api from '../services/api';
import Button from './Button';
import Modal from './Modal';
import '../styles/DiffSyncView.css';

export default function DiffSyncView({ projectId }) {
    const { dataSources } = useDataSources();
    const { syncingProjects, startPolling } = useProjects();
    const { ingestionJobs } = useIngestionJobs();
    const { showAlert } = useAlert();

    const [diffSyncJobs, setDiffSyncJobs] = useState({});
    const [loadingJobs, setLoadingJobs] = useState(false);
    const [triggeringSync, setTriggeringSync] = useState(false);
    const [syncingProject, setSyncingProject] = useState(false);

    // Confirmation modal
    const [confirmModal, setConfirmModal] = useState({ isOpen: false, title: '', message: '', onConfirm: null, confirmLabel: 'Confirm' });
    const closeConfirmModal = () => setConfirmModal(prev => ({ ...prev, isOpen: false }));

    // Filter to only issue-scoped repos linked to this project
    const eligibleSources = dataSources.filter(
        ds => ds.linked_projects?.includes(projectId) && ds.type === 'REPOSITORY' && ds.scope_by_issues
    );

    const syncState = syncingProjects[projectId];

    const mapStatus = (status) => {
        if (!status) return 'pending';
        const s = status.toUpperCase();
        if (s === 'IN_PROGRESS' || s === 'RUNNING') return 'running';
        if (s === 'SUCCESS' || s === 'COMPLETED') return 'completed';
        if (s === 'FAILED') return 'failed';
        if (s === 'NOT_YET_SYNCED') return 'not-synced';
        return status.toLowerCase();
    };

    // Get latest ingestion job for a data source
    const getLatestIngestionJob = (dsId) => {
        return ingestionJobs
            .filter(job => job.data_source_id === dsId)
            .sort((a, b) => new Date(b.start_time || b.created_at) - new Date(a.start_time || a.created_at))[0] || null;
    };

    // Fetch diff sync jobs for all eligible sources
    const fetchAllJobs = async () => {
        if (!projectId || eligibleSources.length === 0) return;
        setLoadingJobs(true);
        try {
            const jobsByDs = {};
            for (const ds of eligibleSources) {
                const jobs = await api.diff.getSyncJobs(projectId, ds.id);
                jobsByDs[ds.id] = jobs;
            }
            setDiffSyncJobs(jobsByDs);
        } catch (err) {
            console.error('Failed to fetch diff sync jobs', err);
        } finally {
            setLoadingJobs(false);
        }
    };

    useEffect(() => {
        fetchAllJobs();
    }, [projectId, dataSources.length]);

    // Refetch jobs when polling finishes so we get the final status (SUCCESS or FAILED)
    useEffect(() => {
        if (syncState && !syncState.isSyncing) {
            fetchAllJobs();
        }
    }, [syncState?.isSyncing]);

    // ── Sync Project (full orchestrator) ──
    const handleSyncProject = () => {
        setConfirmModal({
            isOpen: true,
            title: 'Sync Project',
            message: `This will run a full Sync Project: Refresh Project Changes (diff-sync) for all ${eligibleSources.length} issue-scoped repo(s), then Refresh Data Source (ingestion) for all configured sources. This runs in the background.`,
            confirmLabel: 'Sync Project',
            onConfirm: async () => {
                setSyncingProject(true);
                closeConfirmModal();
                try {
                    await api.projects.sync(projectId);
                    startPolling(projectId);
                    showAlert('🚀 Sync Project triggered! All stages running in background.', 'success');
                    setTimeout(fetchAllJobs, 3000);
                } catch (err) {
                    showAlert('Failed to trigger Sync Project: ' + err.message, 'error');
                } finally {
                    setSyncingProject(false);
                }
            }
        });
    };

    const handleSyncAll = () => {
        setConfirmModal({
            isOpen: true,
            title: 'Refresh Project Changes',
            message: `This will trigger a Refresh Project Changes (diff-sync) for all ${eligibleSources.length} eligible data source(s). Each repository will be synced with the latest commits.`,
            confirmLabel: 'Refresh All',
            onConfirm: async () => {
                setTriggeringSync(true);
                closeConfirmModal();
                try {
                    for (const ds of eligibleSources) {
                        await api.diff.triggerSync(projectId, ds.id);
                    }
                    startPolling(projectId);
                    showAlert('🚀 Refresh Project Changes triggered!', 'success');
                    setTimeout(fetchAllJobs, 2000);
                } catch (err) {
                    showAlert('Failed to trigger sync: ' + err.message, 'error');
                } finally {
                    setTriggeringSync(false);
                }
            }
        });
    };

    const handleSyncSingle = (ds) => {
        setConfirmModal({
            isOpen: true,
            title: 'Refresh Project Changes',
            message: `Trigger a Refresh Project Changes for "${ds.name}"? This will fetch the latest commits and update the repository changes.`,
            confirmLabel: 'Start Sync',
            onConfirm: async () => {
                setTriggeringSync(true);
                closeConfirmModal();
                try {
                    await api.diff.triggerSync(projectId, ds.id);
                    startPolling(projectId);
                    showAlert(`🚀 Refresh Project Changes triggered for "${ds.name}"!`, 'success');
                    setTimeout(fetchAllJobs, 2000);
                } catch (err) {
                    showAlert('Failed to trigger sync: ' + err.message, 'error');
                } finally {
                    setTriggeringSync(false);
                }
            }
        });
    };

    if (eligibleSources.length === 0) {
        return (
            <div className="diff-sync-container">
                <div className="diff-sync-header">
                    <h2>Sync Project</h2>
                </div>
                <div className="diff-sync-empty">
                    <div className="empty-icon">🔄</div>
                    <h3>No Eligible Repositories</h3>
                    <p>Link an issue-scoped repository data source to this project to enable Sync Project.</p>
                </div>
            </div>
        );
    }

    return (
        <div className="diff-sync-container">
            <div className="diff-sync-header">
                <div>
                    <h2>Sync Project</h2>
                    <p className="diff-sync-subtitle">
                        Orchestrate Refresh Project Changes and Refresh Data Source across all configured sources.
                    </p>
                </div>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <Button 
                        size="sm" 
                        variant="primary"
                        onClick={handleSyncProject} 
                        disabled={syncingProject || triggeringSync}
                    >
                        {syncingProject ? 'Syncing...' : '🚀 Sync Project'}
                    </Button>
                    <Button 
                        size="sm" 
                        variant="secondary"
                        onClick={handleSyncAll} 
                        disabled={triggeringSync || syncingProject}
                    >
                        {triggeringSync ? 'Syncing...' : `Refresh Changes (${eligibleSources.length})`}
                    </Button>
                </div>
            </div>

            {syncState && syncState.sync_status && (
                <div className={`sync-status-banner status-${mapStatus(syncState.sync_status)}`}>
                    <span className="status-dot"></span>
                    <span>
                        {syncState.sync_status === 'in_progress' && 'Sync is currently in progress...'}
                        {syncState.sync_status === 'failed' && 'Last sync failed. Trigger a Sync Project to retry.'}
                        {syncState.sync_status === 'not_yet_synced' && 'This project has not yet been synced. Run Sync Project to initialize.'}
                        {syncState.sync_status === 'success' && 'All repositories are synced and up to date.'}
                    </span>
                </div>
            )}

            <h3 className="diff-sync-section-title" style={{ margin: '20px 0 12px', fontSize: '0.95rem', color: 'var(--color-text-secondary)', fontWeight: 500 }}>
                Refresh Project Changes
            </h3>

            <div className="diff-sync-sources">
                {eligibleSources.map(ds => {
                    const jobs = diffSyncJobs[ds.id] || [];
                    const latestIngestion = getLatestIngestionJob(ds.id);
                    const latestIngestionStatus = latestIngestion ? mapStatus(latestIngestion.processing_status) : null;

                    return (
                        <div key={ds.id} className="sync-source-card">
                            <div className="sync-source-header">
                                <div className="sync-source-info">
                                    <span className="sync-source-icon">🐙</span>
                                    <div>
                                        <h3>{ds.name}</h3>
                                        <p className="sync-source-url">{ds.config?.url || ds.url}</p>
                                    </div>
                                </div>
                                <Button 
                                    size="sm" 
                                    variant="secondary" 
                                    onClick={() => handleSyncSingle(ds)}
                                    disabled={triggeringSync || syncingProject}
                                >
                                    Sync
                                </Button>
                            </div>

                            {/* Per-source Refresh Data Source activity indicator */}
                            {latestIngestion && (
                                <div className="sync-source-activity" style={{
                                    padding: '8px 12px',
                                    margin: '0 16px 8px',
                                    borderRadius: '8px',
                                    background: 'var(--surface-color)',
                                    border: '1px solid var(--border-color)',
                                    fontSize: '0.8rem',
                                    display: 'flex',
                                    justifyContent: 'space-between',
                                    alignItems: 'center',
                                }}>
                                    <span style={{ color: 'var(--color-text-secondary)' }}>
                                        Refresh Data Source
                                    </span>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                        <span style={{ color: 'var(--color-text-tertiary)', fontSize: '0.75rem' }}>
                                            {new Date(latestIngestion.start_time).toLocaleString()}
                                        </span>
                                        <span className={`mini-job-status status-${latestIngestionStatus}`}>
                                            {latestIngestionStatus}
                                        </span>
                                    </div>
                                </div>
                            )}
                            {!latestIngestion && ds.scope_by_issues && (
                                <div style={{
                                    padding: '8px 12px',
                                    margin: '0 16px 8px',
                                    borderRadius: '8px',
                                    background: 'rgba(255, 193, 7, 0.06)',
                                    border: '1px solid rgba(255, 193, 7, 0.15)',
                                    fontSize: '0.8rem',
                                    color: 'var(--color-text-secondary)',
                                }}>
                                    ⚠️ Not yet synced — run Sync Project to initialize.
                                </div>
                            )}

                            <div className="sync-jobs-section">
                                <h4>Recent Refresh Project Changes</h4>
                                {loadingJobs ? (
                                    <p className="sync-jobs-loading">Loading...</p>
                                ) : jobs.length === 0 ? (
                                    <p className="sync-jobs-empty">No sync jobs found for this source.</p>
                                ) : (
                                    <div className="sync-jobs-list">
                                        {jobs.slice(0, 5).map(job => {
                                            const status = mapStatus(job.status);
                                            return (
                                                <div key={job.id} className="sync-job-row">
                                                    <div className="sync-job-info">
                                                        <span className="sync-job-id">#{job.id.substring(0, 8)}</span>
                                                        <span className="sync-job-date">
                                                            {new Date(job.start_time).toLocaleString()}
                                                        </span>
                                                    </div>
                                                    <div className={`sync-job-status status-${status}`}>
                                                        {status}
                                                    </div>
                                                </div>
                                            );
                                        })}
                                    </div>
                                )}
                            </div>
                        </div>
                    );
                })}
            </div>

            {/* Confirmation Modal */}
            <Modal
                isOpen={confirmModal.isOpen}
                onClose={closeConfirmModal}
                title={confirmModal.title}
                actions={
                    <>
                        <Button size="sm" variant="secondary" onClick={closeConfirmModal}>Cancel</Button>
                        <Button size="sm" variant="primary" onClick={confirmModal.onConfirm}>{confirmModal.confirmLabel}</Button>
                    </>
                }
            >
                <p>{confirmModal.message}</p>
            </Modal>
        </div>
    );
}
