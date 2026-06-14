import { useState, useMemo } from 'react';
import { useDataSources, useIngestionJobs, useAlert, useProjects } from '../contexts/index';
import Button from './Button';
import Modal from './Modal';
import api from '../services/api';
import '../styles/DataSourcesView.css';
import '../styles/IngestionJobsView.css';

export default function DataSourcesView({ projectId }) {
    const { projects } = useProjects();
    const { dataSources, loading: dsLoading, error, deleteDataSource, createDataSource, updateDataSource, mcpConfigs, linkProjectToDataSource, linkMcpToDataSource } = useDataSources();
    const { ingestionJobs, createIngestionJob } = useIngestionJobs();
    const { showAlert } = useAlert();

    const [activeJobView, setActiveJobView] = useState(null); // dataSourceId
    const [creatingJob, setCreatingJob] = useState(false);
    const [showAddForm, setShowAddForm] = useState(false);

    // Initialize with current project if available
    const [newDS, setNewDS] = useState({
        provider: 'GitHub',
        type: 'REPOSITORY',
        url: '',
        name: '',
        branch: '',
        scope_by_issues: false,
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

    const [editModalOpen, setEditModalOpen] = useState(false);
    const [editingDS, setEditingDS] = useState(null);
    const [isConfirmingEdit, setIsConfirmingEdit] = useState(false);

    const closeConfirmModal = () => setConfirmModal(prev => ({ ...prev, isOpen: false }));

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
            await createDataSource(newDS.provider, { type: newDS.type, url: newDS.url, name: newDS.name, branch: newDS.branch, scope_by_issues: newDS.scope_by_issues }, newDS.projectIds);
            setShowAddForm(false);
            setNewDS({
                provider: 'GitHub',
                type: 'REPOSITORY',
                url: '',
                name: '',
                branch: '',
                scope_by_issues: false,
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
                                <label className="input-label">Type</label>
                                <select
                                    className="input"
                                    value={newDS.type}
                                    onChange={e => setNewDS({ ...newDS, type: e.target.value })}
                                >
                                    <option value="REPOSITORY">Repository</option>
                                    <option value="DOCUMENTATION">Documentation</option>
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
                            {newDS.type === 'REPOSITORY' && (
                                <div className="form-field fade-in">
                                    <label className="input-label" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                        <input
                                            type="checkbox"
                                            checked={newDS.scope_by_issues}
                                            onChange={e => setNewDS({ ...newDS, scope_by_issues: e.target.checked })}
                                        />
                                        Scope by Issues
                                    </label>
                                    <p className="field-hint" style={{ marginTop: '4px' }}>Whether to scope ingestion to specific issues configured on the project.</p>
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

                                            <div className="data-source-meta-row">
                                                 <div className="meta-section">
                                                    <div className="meta-section-label-row">
                                                        <span className="meta-section-label">Projects</span>
                                                        {ds.scope_by_issues && ds.type === 'REPOSITORY' && (
                                                            <span className="scope-indicator" title="Ingestion is scoped to project issues">scoped</span>
                                                        )}
                                                    </div>
                                                    <div className="meta-section-tags">
                                                        {ds.linked_projects && ds.linked_projects.map(pId => {
                                                            const p = projects.find(proj => proj.id === pId);
                                                            return (
                                                                <span key={pId} className={`project-tag ${pId === projectId ? 'active' : ''}`}>
                                                                    {p?.project_name || p?.name || 'Unknown Project'}
                                                                </span>
                                                            );
                                                        })}
                                                        {(() => {
                                                            const unlinked = projects.filter(p => !ds.linked_projects?.includes(p.id));
                                                            if (unlinked.length > 0) {
                                                                return (
                                                                    <select
                                                                        className="link-selector projects-link-select"
                                                                        defaultValue=""
                                                                        onChange={async (e) => {
                                                                            const val = e.target.value;
                                                                            if (!val) return;
                                                                            try {
                                                                                await linkProjectToDataSource(val, ds.id);
                                                                                showAlert('Project linked successfully', 'success');
                                                                            } catch (err) {
                                                                                showAlert('Failed to link project: ' + err.message, 'error');
                                                                            }
                                                                            e.target.value = "";
                                                                        }}
                                                                    >
                                                                        <option value="" disabled>+ Link</option>
                                                                        {unlinked.map(p => (
                                                                            <option key={p.id} value={p.id}>
                                                                                {p.project_name || p.name}
                                                                            </option>
                                                                        ))}
                                                                    </select>
                                                                );
                                                            }
                                                            return null;
                                                        })()}
                                                    </div>
                                                </div>

                                                <div className="meta-section">
                                                    <span className="meta-section-label">MCP Server</span>
                                                    <div className="meta-section-tags">
                                                        {ds.mcp_configs && ds.mcp_configs.length > 0 ? (
                                                            ds.mcp_configs.map(mcp => (
                                                                <div key={mcp.id} className="mcp-badge linked" title={`Connected to MCP: ${mcp.name}`}>
                                                                    <span className="mcp-icon">⚡</span>
                                                                    <span className="mcp-name">{mcp.name}</span>
                                                                </div>
                                                            ))
                                                        ) : ds.mcp_config ? (
                                                            <div className="mcp-badge linked" title={`Connected to MCP: ${ds.mcp_config.name}`}>
                                                                <span className="mcp-icon">⚡</span>
                                                                <span className="mcp-name">{ds.mcp_config.name}</span>
                                                            </div>
                                                        ) : (
                                                            <div className="mcp-badge none" title="This data source is not currently linked to an MCP protocol server">
                                                                <span className="mcp-icon">⚙️</span>
                                                                <span>None</span>
                                                            </div>
                                                        )}

                                                        {(() => {
                                                            const linkedMcpIds = ds.mcp_configs ? ds.mcp_configs.map(mcp => mcp.id) : (ds.mcp_config ? [ds.mcp_config.id] : []);
                                                            const unlinked = mcpConfigs.filter(mcp => !linkedMcpIds.includes(mcp.id));
                                                            if (unlinked.length > 0) {
                                                                return (
                                                                    <select
                                                                        className="link-selector mcp-link-select"
                                                                        defaultValue=""
                                                                        onChange={async (e) => {
                                                                            const val = e.target.value;
                                                                            if (!val) return;
                                                                            try {
                                                                                await linkMcpToDataSource(ds.id, val);
                                                                                showAlert('MCP server linked successfully', 'success');
                                                                            } catch (err) {
                                                                                showAlert('Failed to link MCP server: ' + err.message, 'error');
                                                                            }
                                                                            e.target.value = "";
                                                                        }}
                                                                    >
                                                                        <option value="" disabled>+ Link</option>
                                                                        {unlinked.map(mcp => (
                                                                            <option key={mcp.id} value={mcp.id}>
                                                                                {mcp.name}
                                                                            </option>
                                                                        ))}
                                                                    </select>
                                                                );
                                                            }
                                                            return null;
                                                        })()}
                                                    </div>
                                                </div>
                                            </div>
                                        </div>
                                    </div>

                                    <div className="data-source-actions-flat">
                                        <button
                                            className={`flat-action ${activeJobView === ds.id ? 'active' : ''}`}
                                            onClick={() => {
                                                const isActive = activeJobView === ds.id;
                                                setActiveJobView(isActive ? null : ds.id);
                                            }}
                                        >
                                            {activeJobView === ds.id ? 'Hide History' : 'View Latest Jobs'}
                                        </button>
                                        <button
                                            className="flat-action"
                                            onClick={() => {
                                                setEditingDS({
                                                    id: ds.id,
                                                    provider: ds.provider,
                                                    type: ds.type,
                                                    url: ds.config?.url || ds.url,
                                                    name: ds.name,
                                                    branch: ds.branch || '',
                                                    scope_by_issues: !!ds.scope_by_issues,
                                                });
                                                setIsConfirmingEdit(false);
                                                setEditModalOpen(true);
                                            }}
                                        >
                                            Edit
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

            {/* Edit Data Source Modal */}
            <Modal
                isOpen={editModalOpen}
                onClose={() => { setEditModalOpen(false); setIsConfirmingEdit(false); }}
                title={isConfirmingEdit ? "Confirm Changes" : "Edit Data Source"}
                size="md"
                actions={
                    <>
                        <Button size="sm" variant="ghost" onClick={() => {
                            if (isConfirmingEdit) setIsConfirmingEdit(false);
                            else setEditModalOpen(false);
                        }}>
                            {isConfirmingEdit ? "Back" : "Cancel"}
                        </Button>
                        {!isConfirmingEdit ? (
                            <Button form="edit-datasource-form" type="submit">Save Changes</Button>
                        ) : (
                            <Button variant="primary" onClick={async () => {
                                try {
                                    await updateDataSource(editingDS.id, {
                                        name: editingDS.name,
                                        url: editingDS.url,
                                        branch: editingDS.branch || undefined,
                                        scope_by_issues: editingDS.scope_by_issues
                                    });
                                    showAlert('Data source updated', 'success');
                                    setEditModalOpen(false);
                                    setIsConfirmingEdit(false);
                                } catch (err) {
                                    showAlert('Failed to update data source: ' + err.message, 'error');
                                }
                            }}>Confirm Edit</Button>
                        )}
                    </>
                }
            >
                {editingDS && (
                    <form id="edit-datasource-form" onSubmit={(e) => {
                        e.preventDefault();
                        setIsConfirmingEdit(true);
                    }}>
                        {!isConfirmingEdit ? (
                            <div className="form-grid">
                                <div className="form-field">
                                    <label className="input-label">Name</label>
                                    <input className="input" value={editingDS.name} onChange={(e) => setEditingDS({...editingDS, name: e.target.value})} />
                                </div>
                                <div className="form-field">
                                    <label className="input-label">URL</label>
                                    <input className="input" value={editingDS.url} onChange={(e) => setEditingDS({...editingDS, url: e.target.value})} />
                                </div>
                                {editingDS.type === 'REPOSITORY' && (
                                    <div className="form-field">
                                        <label className="input-label">Branch</label>
                                        <input className="input" value={editingDS.branch} onChange={(e) => setEditingDS({...editingDS, branch: e.target.value})} />
                                    </div>
                                )}
                                {editingDS.type === 'REPOSITORY' && (
                                    <div className="form-field">
                                        <label className="input-label" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                            <input type="checkbox" checked={editingDS.scope_by_issues} onChange={(e) => setEditingDS({...editingDS, scope_by_issues: e.target.checked})} />
                                            Scope by Issues
                                        </label>
                                    </div>
                                )}
                            </div>
                        ) : (
                            <div className="confirmation-view" style={{ padding: '10px 0' }}>
                                <p style={{ marginBottom: '16px' }}>Please confirm the following updates to <strong>{editingDS.name}</strong>:</p>
                                <ul style={{ background: 'var(--surface-color)', padding: '16px 24px', borderRadius: '8px', border: '1px solid var(--border-color)', listStyle: 'none' }}>
                                    <li style={{ marginBottom: '8px' }}><strong>Name:</strong> {editingDS.name}</li>
                                    <li style={{ marginBottom: '8px' }}><strong>URL:</strong> {editingDS.url}</li>
                                    {editingDS.type === 'REPOSITORY' && (
                                        <>
                                            <li style={{ marginBottom: '8px' }}><strong>Branch:</strong> {editingDS.branch || '(default)'}</li>
                                            <li style={{ marginBottom: '8px' }}><strong>Scope by Issues:</strong> {editingDS.scope_by_issues ? 'Yes' : 'No'}</li>
                                        </>
                                    )}
                                </ul>
                            </div>
                        )}
                    </form>
                )}
            </Modal>

        </div>
    );
}

function getDataSourceIcon(type) {
    const key = (type || '').toString().toLowerCase();
    // Prefer a GitHub-specific icon when provider/type contains 'github'
    if (key.includes('github')) return '🐙';

    const icons = {
        file: '📄',
        web: '🌐',
        database: '🗄️',
    };
    return icons[key] || '📦';
}
