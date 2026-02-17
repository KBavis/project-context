import { useState } from 'react';
import { useDataSources, useIngestionJobs } from '../contexts/index';
import Button from './Button';
import '../styles/DataSourcesView.css';
import '../styles/IngestionJobsView.css';

export default function DataSourcesView({ projectId }) {
    const { dataSources, loading: dsLoading, error, deleteDataSource, createDataSource } = useDataSources();
    const { ingestionJobs, createIngestionJob } = useIngestionJobs();

    const [activeJobView, setActiveJobView] = useState(null); // dataSourceId
    const [creatingJob, setCreatingJob] = useState(false);
    const [showAddForm, setShowAddForm] = useState(false);
    const [newDS, setNewDS] = useState({ provider: 'github', url: '', name: '' });

    // Filter jobs for specific data source and limit to latest 3
    const getLatestJobsForDataSource = (dsId) => {
        return ingestionJobs
            .filter(job => job.data_source_id === dsId)
            .sort((a, b) => new Date(b.created_at || b.start_time) - new Date(a.created_at || a.start_time))
            .slice(0, 3);
    };

    const handleDelete = async (dataSourceId) => {
        if (!confirm('Are you sure you want to permanently delete this data source and all its associated data?')) {
            return;
        }
        try {
            await deleteDataSource(dataSourceId);
        } catch (err) {
            alert('Failed to delete data source');
        }
    };

    const handleRunIngestion = async (dsId) => {
        setCreatingJob(true);
        try {
            await createIngestionJob(dsId);
            setActiveJobView(dsId);
        } catch (err) {
            alert('Failed to start ingestion job: ' + err.message);
        } finally {
            setCreatingJob(false);
        }
    };

    const handleAddDataSource = async (e) => {
        e.preventDefault();
        try {
            await createDataSource(newDS.provider, { url: newDS.url, name: newDS.name });
            setShowAddForm(false);
            setNewDS({ provider: 'github', url: '', name: '' });
        } catch (err) {
            alert('Failed to add data source: ' + err.message);
        }
    };

    const mapStatus = (status) => {
        if (!status) return 'pending';
        const s = status.toUpperCase();
        if (s === 'IN_PROGRESS') return 'running';
        if (s === 'SUCCESS') return 'completed';
        if (s === 'FAILED') return 'failed';
        return status.toLowerCase();
    };

    if (!projectId) {
        return (
            <div className="data-sources-empty">
                <div className="empty-icon">📁</div>
                <h3>No Project Selected</h3>
                <p>Select a project to view its data sources</p>
            </div>
        );
    }

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
                                    <option value="github">GitHub</option>
                                    <option value="file">File Upload</option>
                                    <option value="web">Web Scraper</option>
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
                                            <h3 className="data-source-name">{displayName}</h3>
                                            <p className="data-source-provider">{ds.provider || ds.type}</p>
                                            <p className="data-source-url" title={url}>{url}</p>
                                        </div>
                                    </div>

                                    <div className="data-source-footer">
                                        <div className="data-source-actions-group">
                                            <Button
                                                size="xs"
                                                variant={activeJobView === ds.id ? "primary" : "ghost"}
                                                onClick={() => setActiveJobView(activeJobView === ds.id ? null : ds.id)}
                                            >
                                                {activeJobView === ds.id ? 'Hide History' : 'Latest Jobs'}
                                            </Button>
                                            <Button
                                                size="xs"
                                                variant="secondary"
                                                onClick={() => handleRunIngestion(ds.id)}
                                                loading={creatingJob}
                                            >
                                                ▶ Run Ingestion
                                            </Button>
                                        </div>
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
