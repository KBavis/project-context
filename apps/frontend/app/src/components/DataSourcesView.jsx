import { useState, useMemo } from 'react';
import { useDataSources, useIngestionJobs, useAlert, useProjects } from '../contexts/index';
import Button from './Button';
import Modal from './Modal';
import '../styles/DataSourcesView.css';
import '../styles/IngestionJobsView.css';

export default function DataSourcesView({ projectId }) {
    const { projects } = useProjects();
    const { dataSources, loading: dsLoading, error, deleteDataSource, createDataSource, updateDataSource, mcpConfigs, linkProjectToDataSource, unlinkProjectFromDataSource, linkMcpToDataSource } = useDataSources();
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

    // Drag over state for droppable area
    const [isDragOver, setIsDragOver] = useState(false);

    const closeConfirmModal = () => setConfirmModal(prev => ({ ...prev, isOpen: false }));
    const [isUnlinkDragOver, setIsUnlinkDragOver] = useState(false);

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
            await createDataSource(
                newDS.provider,
                {
                    type: newDS.type,
                    url: newDS.url,
                    name: newDS.name,
                    branch: newDS.branch,
                    scope_by_issues: newDS.scope_by_issues
                },
                newDS.projectIds
            );
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

    const renderDataSourcesGrid = () => {
        if (dsLoading && dataSources.length === 0) {
            return (
                <div className="data-sources-loading">
                    <div className="spinner spin"></div>
                    <p>Loading data sources...</p>
                </div>
            );
        }
        if (dataSources.length === 0) {
            return (
                <div className="data-sources-empty">
                    <div className="empty-icon">📁</div>
                    <h3>No Data Sources</h3>
                    <p>Add a data source to get started</p>
                </div>
            );
        }

        const handleDragStart = (e, ds) => {
            e.dataTransfer.setData('application/json', JSON.stringify(ds));
        };

        const handleDropLink = async (e) => {
            e.preventDefault();
            setIsDragOver(false);
            if (!projectId) return;
            try {
                const dsStr = e.dataTransfer.getData('application/json');
                if (dsStr) {
                    const ds = JSON.parse(dsStr);
                    if (!ds.linked_projects?.includes(projectId)) {
                        await linkProjectToDataSource(projectId, ds.id);
                        showAlert(`Linked data source to project successfully`, 'success');
                    }
                }
            } catch (err) {
                showAlert('Failed to link data source: ' + err.message, 'error');
            }
        };

        const handleDropUnlink = async (e) => {
            e.preventDefault();
            setIsUnlinkDragOver(false);
            if (!projectId) return;
            try {
                const dsStr = e.dataTransfer.getData('application/json');
                if (dsStr) {
                    const ds = JSON.parse(dsStr);
                    if (ds.linked_projects?.includes(projectId)) {
                        const displayName = ds.name || ds.config?.url || ds.url || 'this data source';
                        setConfirmModal({
                            isOpen: true,
                            title: 'Unlink Data Source',
                            message: `Are you sure you want to unlink "${displayName}" from this project? For repositories, this will permanently delete all associated project-scoped repository changes.`,
                            confirmLabel: 'Unlink',
                            onConfirm: async () => {
                                try {
                                    await unlinkProjectFromDataSource(projectId, ds.id);
                                    showAlert(`Unlinked data source from project successfully`, 'success');
                                } catch (err) {
                                    showAlert('Failed to unlink data source: ' + err.message, 'error');
                                }
                                closeConfirmModal();
                            }
                        });
                    }
                }
            } catch (err) {
                showAlert('Failed to process unlinking: ' + err.message, 'error');
            }
        };

        const handleDragOver = (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'link';
            setIsDragOver(true);
        };

        const handleDragLeave = (e) => {
            e.preventDefault();
            setIsDragOver(false);
        };

        const renderCard = (ds) => {
            const url = ds.config?.url || ds.url;
            const displayName = ds.name || url;
            return (
                <div
                    key={ds.id}
                    className="data-source-wrapper"
                    draggable={true}
                    onDragStart={(e) => handleDragStart(e, ds)}
                >
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
                                    {ds.branch && (
                                        <p className="data-source-provider">
                                            <span className="data-source-branch-badge">{ds.branch}</span>
                                        </p>
                                    )}
                                </div>
                                <p className="data-source-url" title={url}>{url}</p>

                                <div className="data-source-meta-row">
                                    <div className="meta-section">
                                        <div className="meta-section-label-row">
                                            <span className="meta-section-label">Projects</span>
                                            {ds.scope_by_issues && ds.type === 'REPOSITORY' && (
                                                <span className="scope-indicator-pill" title="Ingests repository changes grouped by project issues.">
                                                    <svg className="scope-icon" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                                                        <circle cx="12" cy="12" r="10"></circle>
                                                        <line x1="22" y1="12" x2="18" y2="12"></line>
                                                        <line x1="6" y1="12" x2="2" y2="12"></line>
                                                        <line x1="12" y1="6" x2="12" y2="2"></line>
                                                        <line x1="12" y1="22" x2="12" y2="18"></line>
                                                    </svg>
                                                    Scoped
                                                </span>
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
                                            {!projectId && (() => {
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

                                    {!projectId && (
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
                                    )}


                                </div>
                            </div>
                        </div>

                        <div className="data-source-actions-flat">
                            {ds.type !== 'ISSUE_TRACKER' && (
                                <button
                                    className={`flat-action ${activeJobView === ds.id ? 'active' : ''}`}
                                    onClick={() => {
                                        const isActive = activeJobView === ds.id;
                                        setActiveJobView(isActive ? null : ds.id);
                                    }}
                                >
                                    {activeJobView === ds.id ? 'Hide History' : 'View Latest Jobs'}
                                </button>
                            )}
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
                                        scope_by_issues: !!ds.scope_by_issues
                                    });
                                    setIsConfirmingEdit(false);
                                    setEditModalOpen(true);
                                }}
                            >
                                Edit
                            </button>
                            {ds.type !== 'ISSUE_TRACKER' && (
                                <button
                                    className="flat-action primary"
                                    onClick={() => handleRunIngestion(ds.id)}
                                    disabled={creatingJob}
                                >
                                    {creatingJob ? 'Starting...' : 'Run Ingestion'}
                                </button>
                            )}
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
                                                        <div className="mini-job-date">
                                                            <span>{new Date(job.start_time).toLocaleDateString()}</span>
                                                            <span className="mini-job-time">{new Date(job.start_time).toLocaleTimeString()}</span>
                                                        </div>
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
        };

        if (!projectId) {
            return (
                <div className="data-sources-grid">
                    {dataSources.map(renderCard)}
                </div>
            );
        }

        const linkedDS = dataSources.filter(ds => ds.linked_projects?.includes(projectId));
        const unlinkedDS = dataSources.filter(ds => !ds.linked_projects?.includes(projectId));

        return (
            <div className="data-sources-sections">

                <div
                    className={`ds-section fade-in ${isDragOver ? 'drag-over' : ''}`}
                    onDrop={handleDropLink}
                    onDragOver={handleDragOver}
                    onDragLeave={handleDragLeave}
                >
                    <div className="ds-section-header">
                        <span className="ds-section-label">🔗 Linked to {currentProject?.project_name || 'This Project'}</span>
                        <span className="ds-section-count">{linkedDS.length}</span>
                        <span className="drag-drop-tip" style={{ marginLeft: 'auto', fontSize: '0.75rem', color: 'var(--color-text-tertiary)', fontStyle: 'italic' }}>💡 Drag and drop Data Sources to link or unlink from Project</span>
                    </div>
                    {linkedDS.length > 0 ? (
                        <div className="data-sources-grid">
                            {linkedDS.map(renderCard)}
                        </div>
                    ) : (
                        <div style={{ padding: '40px', border: '2px dashed var(--color-border)', borderRadius: '12px', textAlign: 'center', color: 'var(--color-text-tertiary)', background: 'rgba(255, 255, 255, 0.02)' }}>
                            Drag and drop data sources here from the available sources below to link them to this project.
                        </div>
                    )}
                </div>

                {unlinkedDS.length > 0 && (
                    <div
                        className={`ds-section fade-in ${isUnlinkDragOver ? 'drag-over' : ''}`}
                        onDrop={handleDropUnlink}
                        onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; setIsUnlinkDragOver(true); }}
                        onDragLeave={(e) => { e.preventDefault(); setIsUnlinkDragOver(false); }}
                    >
                        <div className="ds-section-header">
                            <span className="ds-section-label other">📂 Other Available Sources</span>
                            <span className="ds-section-count">{unlinkedDS.length}</span>
                        </div>
                        <div className="data-sources-grid">
                            {unlinkedDS.map(renderCard)}
                        </div>
                    </div>
                )}
                {unlinkedDS.length === 0 && linkedDS.length > 0 && (
                    <div
                        className={`ds-section fade-in ${isUnlinkDragOver ? 'drag-over' : ''}`}
                        onDrop={handleDropUnlink}
                        onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; setIsUnlinkDragOver(true); }}
                        onDragLeave={(e) => { e.preventDefault(); setIsUnlinkDragOver(false); }}
                        style={{ minHeight: '150px' }}
                    >
                        <div className="ds-section-header">
                            <span className="ds-section-label other">📂 Other Available Sources</span>
                            <span className="ds-section-count">0</span>
                        </div>
                        <div style={{ padding: '40px', border: '2px dashed var(--color-border)', borderRadius: '12px', textAlign: 'center', color: 'var(--color-text-tertiary)', background: 'rgba(255, 255, 255, 0.02)' }}>
                            Drag and drop linked data sources here to unlink them from this project.
                        </div>
                    </div>
                )}
            </div>
        );
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
                                    <option value="Jira">Jira</option>
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
                                    <option value="ISSUE_TRACKER">Issue Tracker</option>
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
                            {newDS.type === 'REPOSITORY' && (
                                <div className="full-width fade-in" style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--spacing-2xl)', alignItems: 'flex-start' }}>
                                    <div className="form-field" style={{ flex: '1 1 250px', maxWidth: '320px' }}>
                                        <label className="input-label">Branch (optional)</label>
                                        <input
                                            className="input"
                                            type="text"
                                            value={newDS.branch}
                                            onChange={e => setNewDS({ ...newDS, branch: e.target.value })}
                                            placeholder="main"
                                        />

                                        <div style={{ marginTop: '16px' }}>
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
                                    </div>

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

            {renderDataSourcesGrid()}

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
                                    <input className="input" value={editingDS.name} onChange={(e) => setEditingDS({ ...editingDS, name: e.target.value })} />
                                </div>
                                <div className="form-field">
                                    <label className="input-label">URL</label>
                                    <input className="input" value={editingDS.url} onChange={(e) => setEditingDS({ ...editingDS, url: e.target.value })} />
                                </div>
                                {editingDS.type === 'REPOSITORY' && (
                                    <div className="full-width" style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--spacing-xl)', alignItems: 'flex-start', marginTop: 'var(--spacing-sm)' }}>
                                        <div className="form-field" style={{ flex: '1 1 200px', maxWidth: '250px' }}>
                                            <label className="input-label">Branch</label>
                                            <input className="input" value={editingDS.branch} onChange={(e) => setEditingDS({ ...editingDS, branch: e.target.value })} />
                                        </div>

                                    </div>
                                )}
                                {editingDS.type === 'REPOSITORY' && (
                                    <div className="form-field">
                                        <label className="input-label" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                            <input type="checkbox" checked={editingDS.scope_by_issues} onChange={(e) => setEditingDS({ ...editingDS, scope_by_issues: e.target.checked })} />
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
                                    <li style={{ marginBottom: '8px', wordBreak: 'break-all' }}><strong>URL:</strong> {editingDS.url}</li>
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

function getDataSourceIcon(provider, type) {
    const key = (provider || type || '').toString().toLowerCase();

    if (key.includes('github')) return (
        <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z" /></svg>
    );
    if (key.includes('bitbucket')) return (
        <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor"><path d="M.778 1.213a.768.768 0 00-.768.892l3.263 19.81c.084.5.515.868 1.022.873H19.95a.772.772 0 00.77-.646l3.27-20.03a.768.768 0 00-.768-.891zM14.52 15.53H9.522L8.17 8.466h7.561z" /></svg>
    );
    if (key.includes('jira')) return (
        <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor"><path d="M11.571 11.513H0a5.218 5.218 0 005.232 5.215h2.13v2.057A5.215 5.215 0 0012.575 24V12.518a1.005 1.005 0 00-1.005-1.005zm5.723-5.756H5.736a5.215 5.215 0 005.215 5.214h2.129v2.058a5.218 5.218 0 005.215 5.214V6.758a1.001 1.001 0 00-1.001-1.001zM23.013 0H11.455a5.215 5.215 0 005.215 5.215h2.129v2.057A5.215 5.215 0 0024.013 12.487V1.005A1.005 1.005 0 0023.013 0z" /></svg>
    );
    if (key.includes('confluence')) return (
        <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor"><path d="M.87 18.257c-.248.382-.53.875-.763 1.245a.764.764 0 00.255 1.04l4.965 3.054a.764.764 0 001.058-.26c.199-.332.488-.853.783-1.37C9.12 18.464 11.062 17.7 15.39 19.774l5.14 2.47a.764.764 0 001.004-.39l2.18-5.032a.764.764 0 00-.384-1.003c-1.2-.558-3.57-1.672-5.14-2.47-6.886-3.3-12.27-2.205-17.32 4.908zm22.26-12.514c.249-.382.53-.875.764-1.245a.764.764 0 00-.256-1.04L18.673.404a.764.764 0 00-1.058.26c-.199.332-.488.853-.783 1.37-1.953 3.502-3.895 4.266-8.223 2.192L3.47 1.756a.764.764 0 00-1.004.39L.286 7.178a.764.764 0 00.384 1.003c1.2.558 3.57 1.672 5.14 2.47 6.886 3.3 12.27 2.205 17.32-4.908z" /></svg>
    );

    return '📦';
}
