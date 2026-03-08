import { useState, useMemo } from 'react';
import { useDataSources, useIngestionJobs, useAlert, useProjects } from '../contexts/index';
import Button from './Button';
import Modal from './Modal';
import '../styles/DataSourcesView.css';
import '../styles/IngestionJobsView.css';

export default function DataSourcesView({ projectId }) {
    const { projects } = useProjects();
    const { dataSources, loading: dsLoading, error, deleteDataSource, createDataSource } = useDataSources();
    const { ingestionJobs, createIngestionJob } = useIngestionJobs();
    const { showAlert } = useAlert();

    const [activeJobView, setActiveJobView] = useState(null); // dataSourceId
    const [creatingJob, setCreatingJob] = useState(false);
    const [showAddForm, setShowAddForm] = useState(false);

    // Initialize with current project if available
    const [newDS, setNewDS] = useState({
        provider: 'GitHub',
        url: '',
        name: '',
        branch: '',
        projectIds: projectId ? [projectId] : []
    });

    const currentProject = useMemo(() =>
        projects.find(p => p.id === projectId),
        [projects, projectId]
    );

    // Confirmation Modal state
    const [confirmModal, setConfirmModal] = useState({
        isOpen: false,
        title: '',
        message: '',
        onConfirm: null,
        confirmLabel: 'Confirm'
    });

    const closeConfirmModal = () => setConfirmModal(prev => ({ ...prev, isOpen: false }));

    // Filter jobs for specific data source and limit to latest 3
    const getLatestJobsForDataSource = (dsId) => {
        return ingestionJobs
            .filter(job => job.data_source_id === dsId)
            .sort((a, b) => new Date(b.created_at || b.start_time) - new Date(a.created_at || a.start_time))
            .slice(0, 3);
    };

    const handleDelete = (dataSourceId) => {
        const ds = dataSources.find(d => d.id === dataSourceId);
        const displayName = ds?.name || ds?.config?.url || ds?.url || 'this data source';

        setConfirmModal({
            isOpen: true,
            title: 'Delete Data Source',
            message: `Are you sure you want to permanently delete "${displayName}" and all its associated data? This action cannot be undone.`,
            confirmLabel: 'Delete',
            onConfirm: async () => {
                try {
                    await deleteDataSource(dataSourceId);
                    showAlert('Data source deleted successfully', 'success');
                } catch (err) {
                    showAlert('Failed to delete data source: ' + err.message, 'error');
                }
                closeConfirmModal();
            }
        });
    };

    const handleRunIngestion = (dsId) => {
        const ds = dataSources.find(d => d.id === dsId);
        const displayName = ds?.name || ds?.config?.url || ds?.url || 'this data source';

        setConfirmModal({
            isOpen: true,
            title: 'Run Ingestion',
            message: `You are about to start a new ingestion job for "${displayName}". This will retrieve and process the latest data from the source.`,
            confirmLabel: 'Start Ingestion',
            onConfirm: async () => {
                setCreatingJob(true);
                try {
                    await createIngestionJob(dsId);
                    setActiveJobView(dsId);
                    showAlert('🚀 Ingestion job successfully triggered!', 'success');
                } catch (err) {
                    showAlert('Failed to start ingestion job: ' + err.message, 'error');
                } finally {
                    setCreatingJob(false);
                }
                closeConfirmModal();
            }
        });
    };

    const handleAddDataSource = async (e) => {
        e.preventDefault();
        try {
            await createDataSource(newDS.provider, { url: newDS.url, name: newDS.name, branch: newDS.branch }, newDS.projectIds);
            setShowAddForm(false);
            setNewDS({
                provider: 'GitHub',
                url: '',
                name: '',
                branch: '',
                projectIds: projectId ? [projectId] : []
            });
            showAlert('Data source added successfully', 'success');
        } catch (err) {
            showAlert('Failed to add data source: ' + err.message, 'error');
        }
    };

    const mapStatus = (status) => {
        if (!status) return 'pending';
        const s = status.toUpperCase();
        if (s === 'IN_PROGRESS' || s === 'RUNNING') return 'running';
        if (s === 'SUCCESS' || s === 'COMPLETED') return 'completed';
        if (s === 'FAILED') return 'failed';
        return status.toLowerCase();
    };

    return (
        <div className="data-sources-container">
            <div className="data-sources-header">
                <h2>Data Sources</h2>
                <Button size="sm" onClick={() => setShowAddForm(!showAddForm)}>
                    {showAddForm ? 'Cancel' : '+ Add Data Source'}
                </Button>
            </div>

            {showAddForm && (
                <div className="add-datasource-card fade-in">
                    <form onSubmit={handleAddDataSource}>
                        <div className="form-grid">
                            <div className="form-field">
                                <label className="input-label">Provider</label>
                                <select
                                    className="input"
                                    value={newDS.provider}
                                    onChange={e => setNewDS({ ...newDS, provider: e.target.value })}
                                >
                                    <option value="GitHub">GitHub</option>
                                    <option value="BitBucket">BitBucket</option>
                                    <option value="Confluence">Confluence</option>
                                </select>
                            </div>
                            <div className="form-field">
                                <label className="input-label">Name</label>
                                <input
                                    className="input"
                                    type="text"
                                    value={newDS.name}
                                    onChange={e => setNewDS({ ...newDS, name: e.target.value })}
                                    placeholder="Source Name (e.g. My Repo)"
                                    required
                                />
                            </div>
                            <div className="form-field">
                                <label className="input-label">URL / Path</label>
                                <input
                                    className="input"
                                    type="text"
                                    value={newDS.url}
                                    onChange={e => setNewDS({ ...newDS, url: e.target.value })}
                                    placeholder="https://github.com/user/repo"
                                    required
                                />
                            </div>
                            {newDS.provider === 'GitHub' && (
                                <div className="form-field fade-in">
                                    <label className="input-label">Branch (optional)</label>
                                    <input
                                        className="input"
                                        type="text"
                                        value={newDS.branch}
                                        onChange={e => setNewDS({ ...newDS, branch: e.target.value })}
                                        placeholder="main"
                                    />
                                </div>
                            )}
                            <div className="form-field projects-field">
                                <label className="input-label">Target Projects</label>
                                <div className="project-selector-container">
                                    {projects.map(p => {
                                        const isSelected = newDS.projectIds.includes(p.id);
                                        return (
                                            <div
                                                key={p.id}
                                                className={`project-option ${isSelected ? 'selected' : ''}`}
                                                onClick={() => {
                                                    const values = isSelected
                                                        ? newDS.projectIds.filter(id => id !== p.id)
                                                        : [...newDS.projectIds, p.id];
                                                    setNewDS({ ...newDS, projectIds: values });
                                                }}
                                            >
                                                <input
                                                    type="checkbox"
                                                    checked={isSelected}
                                                    onChange={() => { }} // Handled by div onClick
                                                />
                                                <span className="project-option-name" title={p.project_name || p.name}>
                                                    {p.project_name || p.name}
                                                </span>
                                            </div>
                                        );
                                    })}
                                </div>
                                <p className="field-hint">Select one or more projects to link this source to.</p>
                            </div>
                            <div className="form-actions-inline">
                                <Button type="submit" size="sm">Create Source</Button>
                            </div>
                        </div>
                    </form>
                </div>
            )}

            {error && <div className="error-message">{error}</div>}

            {dsLoading && dataSources.length === 0 ? (
                <div className="data-sources-loading">
                    <div className="spinner spin"></div>
                    <p>Loading data sources...</p>
                </div>
            ) : dataSources.length === 0 ? (
                <div className="data-sources-empty">
                    <div className="empty-icon">📁</div>
                    <h3>No Data Sources</h3>
                    <p>Add a data source to get started</p>
                </div>
            ) : (
                <div className="data-sources-grid">
                    {dataSources.map((ds) => {
                        const url = ds.config?.url || ds.url;
                        const displayName = ds.name || url;
                        return (
                            <div key={ds.id} className="data-source-wrapper">
                                <div className={`data-source-card fade-in ${activeJobView === ds.id ? 'active' : ''}`}>
                                    <button
                                        className="delete-icon-button"
                                        onClick={() => handleDelete(ds.id)}
                                        title="Delete Data Source"
                                    >
                                        🗑️
                                    </button>

                                    <div className="data-source-main">
                                        <div className="data-source-icon">
                                            {getDataSourceIcon(ds.provider || ds.type)}
                                        </div>

                                        <div className="data-source-content">
                                            <div className="data-source-title-row">
                                                <h3 className="data-source-name">{displayName}</h3>
                                                <p className="data-source-provider">
                                                    {ds.provider || ds.type}
                                                    {ds.branch && <span className="data-source-branch-badge">{ds.branch}</span>}
                                                </p>
                                            </div>
                                            <p className="data-source-url" title={url}>{url}</p>

                                            {ds.linked_projects && ds.linked_projects.length > 0 && (
                                                <div className="data-source-projects">
                                                    {ds.linked_projects.map(pId => {
                                                        const p = projects.find(proj => proj.id === pId);
                                                        return (
                                                            <span key={pId} className={`project-tag ${pId === projectId ? 'active' : ''}`}>
                                                                {p?.project_name || p?.name || 'Unknown Project'}
                                                            </span>
                                                        );
                                                    })}
                                                </div>
                                            )}
                                        </div>
                                    </div>

                                    <div className="data-source-actions-flat">
                                        <button
                                            className={`flat-action ${activeJobView === ds.id ? 'active' : ''}`}
                                            onClick={() => setActiveJobView(activeJobView === ds.id ? null : ds.id)}
                                        >
                                            {activeJobView === ds.id ? 'Hide History' : 'View Latest Jobs'}
                                        </button>
                                        <button
                                            className="flat-action primary"
                                            onClick={() => handleRunIngestion(ds.id)}
                                            disabled={creatingJob}
                                        >
                                            {creatingJob ? 'Starting...' : 'Run Ingestion'}
                                        </button>
                                    </div>

                                    {activeJobView === ds.id && (
                                        <div className="data-source-jobs-mini fade-in">
                                            <div className="mini-jobs-header">
                                                <span>Latest Activity</span>
                                                {getLatestJobsForDataSource(ds.id).length > 0 && <span className="jobs-count">{getLatestJobsForDataSource(ds.id).length}/3</span>}
                                            </div>
                                            {getLatestJobsForDataSource(ds.id).length === 0 ? (
                                                <p className="no-jobs-text">No jobs found.</p>
                                            ) : (
                                                <div className="mini-jobs-list">
                                                    {getLatestJobsForDataSource(ds.id).map(job => {
                                                        const status = mapStatus(job.processing_status);
                                                        return (
                                                            <div key={job.id} className="mini-job-item">
                                                                <div className="mini-job-info">
                                                                    <span className="mini-job-id">#{job.id.substring(0, 8)}</span>
                                                                    <span className="mini-job-date">
                                                                        {new Date(job.start_time).toLocaleDateString()}
                                                                    </span>
                                                                </div>
                                                                <div className={`mini-job-status status-${status}`}>
                                                                    {status}
                                                                </div>
                                                            </div>
                                                        );
                                                    })}
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}

            {/* Confirmation Modal */}
            <Modal
                isOpen={confirmModal.isOpen}
                onClose={closeConfirmModal}
                title={confirmModal.title}
                actions={
                    <>
                        <Button size="sm" variant="secondary" onClick={closeConfirmModal}>Cancel</Button>
                        <Button
                            size="sm"
                            variant={confirmModal.confirmLabel === 'Delete' ? 'danger' : 'primary'}
                            onClick={confirmModal.onConfirm}
                        >
                            {confirmModal.confirmLabel}
                        </Button>
                    </>
                }
            >
                <p>{confirmModal.message}</p>
            </Modal>
        </div>
    );
}

function getDataSourceIcon(type) {
    const icons = {
        github: '🔗',
        file: '📄',
        web: '🌐',
        database: '🗄️',
    };
    return icons[type?.toLowerCase()] || '📦';
}
