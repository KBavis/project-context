import { useState, useEffect } from 'react';
import { useDataSources, useAlert, useProjects } from '../contexts/index';
import api from '../services/api';
import Button from './Button';
import Modal from './Modal';
import '../styles/DiffSyncView.css';

export default function DiffSyncView({ projectId }) {
    const { dataSources } = useDataSources();
    const { syncingProjects } = useProjects();
    const { showAlert } = useAlert();

    const [diffSyncJobs, setDiffSyncJobs] = useState({});
    const [loadingJobs, setLoadingJobs] = useState(false);
    const [triggeringSync, setTriggeringSync] = useState(false);

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
        return status.toLowerCase();
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

    const handleSyncAll = () => {
        setConfirmModal({
            isOpen: true,
            title: 'Sync All Repositories',
            message: `This will trigger a Diff Sync for all ${eligibleSources.length} eligible data source(s). Each repository will be synced with the latest commits.`,
            confirmLabel: 'Sync All',
            onConfirm: async () => {
                setTriggeringSync(true);
                closeConfirmModal();
                try {
                    for (const ds of eligibleSources) {
                        await api.diff.triggerSync(projectId, ds.id);
                    }
                    showAlert('🚀 Project-wide Diff Sync triggered!', 'success');
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
            title: 'Sync Repository',
            message: `Trigger a Diff Sync for "${ds.name}"? This will fetch the latest commits and update the repository changes.`,
            confirmLabel: 'Start Sync',
            onConfirm: async () => {
                setTriggeringSync(true);
                closeConfirmModal();
                try {
                    await api.diff.triggerSync(projectId, ds.id);
                    showAlert(`🚀 Diff Sync triggered for "${ds.name}"!`, 'success');
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
                    <h2>Repository Sync</h2>
                </div>
                <div className="diff-sync-empty">
                    <div className="empty-icon">🔄</div>
                    <h3>No Eligible Repositories</h3>
                    <p>Link an issue-scoped repository data source to this project to enable Diff Sync.</p>
                </div>
            </div>
        );
    }

    return (
        <div className="diff-sync-container">
            <div className="diff-sync-header">
                <div>
                    <h2>Repository Sync</h2>
                    <p className="diff-sync-subtitle">
                        Sync repository changes for this project's issue-scoped data sources.
                    </p>
                </div>
                <Button 
                    size="sm" 
                    onClick={handleSyncAll} 
                    disabled={triggeringSync}
                >
                    {triggeringSync ? 'Syncing...' : `Sync All (${eligibleSources.length})`}
                </Button>
            </div>

            {syncState && (
                <div className={`sync-status-banner status-${mapStatus(syncState.status)}`}>
                    <span className="status-dot"></span>
                    <span>
                        {syncState.status === 'in_progress' && 'Sync is currently in progress...'}
                        {syncState.status === 'failed' && 'Last sync failed. Please trigger a new sync.'}
                        {syncState.status === 'success' && 'All repositories are synced and up to date.'}
                    </span>
                </div>
            )}

            <div className="diff-sync-sources">
                {eligibleSources.map(ds => {
                    const jobs = diffSyncJobs[ds.id] || [];
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
                                    disabled={triggeringSync}
                                >
                                    Sync
                                </Button>
                            </div>

                            <div className="sync-jobs-section">
                                <h4>Recent Jobs</h4>
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
