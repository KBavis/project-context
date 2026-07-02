import { useEffect, useState, useMemo } from 'react';
import { useJobs, useDataSources } from '../contexts/index';
import '../styles/IngestionJobsView.css';

export default function JobsView() {
    const { jobs, loading, fetchJobs } = useJobs();
    const { dataSources } = useDataSources();

    const [statusFilter, setStatusFilter] = useState('all');
    const [dataSourceFilter, setDataSourceFilter] = useState('all');
    const [dateFilter, setDateFilter] = useState('');
    const [timeRangeFilter, setTimeRangeFilter] = useState('all');
    const [expandedJobs, setExpandedJobs] = useState(new Set());

    const toggleExpand = (jobId) => {
        setExpandedJobs(prev => {
            const next = new Set(prev);
            if (next.has(jobId)) next.delete(jobId);
            else next.add(jobId);
            return next;
        });
    };

    useEffect(() => {
        fetchJobs();
    }, [fetchJobs]);

    const mapStatus = (status) => {
        if (!status) return 'pending';
        const s = status.toUpperCase();
        if (s === 'IN_PROGRESS') return 'running';
        if (s === 'SUCCESS') return 'completed';
        if (s === 'FAILED') return 'failed';
        return status.toLowerCase();
    };

    const getDataSourceName = (dsId) => {
        if (!dsId) return 'Entire Project';
        const ds = dataSources.find(d => d.id === dsId);
        return ds ? (ds.name || ds.url || dsId) : dsId;
    };

    const getDataSourceProvider = (dsId) => {
        if (!dsId) return 'PROJECT';
        const ds = dataSources.find(d => d.id === dsId);
        return ds ? (ds.provider || ds.type) : 'UNKNOWN';
    };

    const handleResetFilters = () => {
        setDataSourceFilter('all');
        setDateFilter('');
        setTimeRangeFilter('all');
        setStatusFilter('all');
    };


    const filteredJobs = useMemo(() => {
        return [...jobs].sort((a, b) => {
            const aTime = a.end_time || a.start_time || a.created_at;
            const bTime = b.end_time || b.start_time || b.created_at;
            return new Date(bTime) - new Date(aTime);
        }).filter(job => {
            const status = mapStatus(job.status);
            if (statusFilter !== 'all' && status !== statusFilter) return false;
            
            if (dataSourceFilter !== 'all') {
                if (dataSourceFilter === 'project' && job.data_source_id) return false;
                if (dataSourceFilter !== 'project' && job.data_source_id !== dataSourceFilter) return false;
            }

            const jobStartTime = job.start_time || job.created_at;
            const jobDateObj = new Date(jobStartTime);

            if (dateFilter) {
                const tzDate = new Date(jobDateObj.getTime() - (jobDateObj.getTimezoneOffset() * 60000)).toISOString().split('T')[0];
                if (tzDate !== dateFilter) return false;
            }

            if (timeRangeFilter !== 'all') {
                const now = new Date();
                const diffMs = now - jobDateObj;
                const diffHours = diffMs / (1000 * 60 * 60);
                
                if (timeRangeFilter === 'last_hour' && diffHours > 1) return false;
                if (timeRangeFilter === 'last_24h' && diffHours > 24) return false;
                if (timeRangeFilter === 'last_7d' && diffHours > 168) return false;
            }

            return true;
        });
    }, [jobs, statusFilter, dataSourceFilter, dateFilter, timeRangeFilter]);

    return (
        <div className="jobs-container">
            <div className="jobs-header-section">
                <div className="jobs-header">
                    <h2>Job History</h2>
                </div>
                <div className="jobs-filters-group">
                    <div className="filter-item">
                        <label className="filter-label">Target</label>
                        <select 
                            className="jobs-filter-select" 
                            value={dataSourceFilter}
                            onChange={(e) => setDataSourceFilter(e.target.value)}
                        >
                            <option value="all">All Targets</option>
                            <option value="project">Entire Project</option>
                            {dataSources.map(ds => (
                                <option key={ds.id} value={ds.id}>{ds.name || ds.url || ds.id}</option>
                            ))}
                        </select>
                    </div>

                    <div className="filter-item">
                        <label className="filter-label">Date</label>
                        <input 
                            type="date" 
                            className="jobs-filter-input date-input" 
                            value={dateFilter}
                            onChange={(e) => setDateFilter(e.target.value)}
                        />
                    </div>

                    <div className="filter-item">
                        <label className="filter-label">Time Range</label>
                        <select 
                            className="jobs-filter-select" 
                            value={timeRangeFilter}
                            onChange={(e) => setTimeRangeFilter(e.target.value)}
                        >
                            <option value="all">Any Time</option>
                            <option value="last_hour">Last Hour</option>
                            <option value="last_24h">Last 24 Hours</option>
                            <option value="last_7d">Last 7 Days</option>
                        </select>
                    </div>

                    <div className="filter-item">
                        <label className="filter-label">Status</label>
                        <select 
                            className="jobs-filter-select status-select" 
                            value={statusFilter}
                            onChange={(e) => setStatusFilter(e.target.value)}
                        >
                            <option value="all">All Statuses</option>
                            <option value="running">Running</option>
                            <option value="completed">Completed</option>
                            <option value="failed">Failed</option>
                            <option value="pending">Pending</option>
                        </select>
                    </div>

                    <div className="filter-item">
                        <label className="filter-label" style={{visibility: 'hidden'}}>Reset</label>
                        <button 
                            className="jobs-reset-btn" 
                            onClick={handleResetFilters}
                            title="Reset all filters"
                        >
                            ↺ Reset
                        </button>
                    </div>
                </div>
            </div>

            {jobs.length === 0 && !loading ? (
                <div className="jobs-empty">
                    <div className="empty-icon">⚙️</div>
                    <h3>No Job History</h3>
                    <p>Job runs will appear here once triggered from the Data Sources view or via Sync Project</p>
                </div>
            ) : (
                <div className="jobs-list">
                    {filteredJobs.length === 0 ? (
                        <div className="jobs-no-results">No jobs match your filters.</div>
                    ) : (
                        filteredJobs.map((job) => {
                            const status = mapStatus(job.status);
                            return (
                                <div key={job.id} className="job-list-item fade-in">
                                    <div className="job-list-info">
                                        <div className="job-list-primary">
                                            <span className="job-list-id">#{job.id.substring(0, 8)}</span>
                                            <span className="job-list-ds-icon" style={{display: 'flex', alignItems: 'center'}}>
                                                {getDataSourceIcon(getDataSourceProvider(job.data_source_id))}
                                            </span>
                                            <span className="job-list-ds" title={getDataSourceName(job.data_source_id)}>
                                                {getDataSourceName(job.data_source_id)}
                                            </span>
                                        </div>
                                        <div className="job-list-date">
                                            <span>{new Date(job.start_time || job.created_at).toLocaleDateString()}</span>
                                            <span className="job-list-time">{new Date(job.start_time || job.created_at).toLocaleTimeString()}</span>
                                        </div>
                                    </div>
                                    <div className="job-list-right">
                                        {job.error && (
                                            <span className="job-list-error-indicator" title={job.error}>⚠️</span>
                                        )}
                                        <div className={`job-list-status status-${status}`}>
                                            {status}
                                        </div>
                                        <button 
                                            className="expand-job-btn" 
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                toggleExpand(job.id);
                                            }}
                                            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-text-tertiary)' }}
                                        >
                                            {expandedJobs.has(job.id) ? '▼' : '▶'}
                                        </button>
                                    </div>
                                    {status === 'running' && (
                                        <div className="job-progress-bar-thin">
                                            <div className="progress-fill pulse"></div>
                                        </div>
                                    )}
                                    
                                    {expandedJobs.has(job.id) && (
                                        <div className="job-nested-tasks" style={{ padding: '10px 16px', background: 'rgba(0,0,0,0.2)', borderTop: '1px solid var(--border-color)', fontSize: '0.85rem' }}>
                                            {job.diff_tasks?.length > 0 && (
                                                <div style={{ marginBottom: '8px' }}>
                                                    <strong>Diff Tasks</strong>
                                                    <ul style={{ paddingLeft: '20px', marginTop: '4px' }}>
                                                        {job.diff_tasks.map(t => (
                                                            <li key={t.id}>
                                                                <span className={`status-${mapStatus(t.status)}`} style={{ marginRight: '6px' }}>●</span>
                                                                {t.status} - {t.duration ? `${t.duration.toFixed(2)}s` : '...'}
                                                                {t.reason && <span style={{ color: 'red', marginLeft: '6px' }}>({t.reason})</span>}
                                                            </li>
                                                        ))}
                                                    </ul>
                                                </div>
                                            )}
                                            {job.embed_tasks?.length > 0 && (
                                                <div>
                                                    <strong>Embed Tasks</strong>
                                                    <ul style={{ paddingLeft: '20px', marginTop: '4px' }}>
                                                        {job.embed_tasks.map(t => (
                                                            <li key={t.id}>
                                                                <span className={`status-${mapStatus(t.processing_status)}`} style={{ marginRight: '6px' }}>●</span>
                                                                {t.processing_status} - {t.duration ? `${t.duration.toFixed(2)}s` : '...'}
                                                                {t.reason && <span style={{ color: 'red', marginLeft: '6px' }}>({t.reason})</span>}
                                                            </li>
                                                        ))}
                                                    </ul>
                                                </div>
                                            )}
                                            {!(job.diff_tasks?.length) && !(job.embed_tasks?.length) && (
                                                <div style={{ color: 'var(--color-text-tertiary)' }}>No sub-tasks executed for this job.</div>
                                            )}
                                        </div>
                                    )}
                                </div>
                            );
                        })
                    )}
                </div>
            )}
        </div>
    );
}

function getDataSourceIcon(provider, type) {
    const key = (provider || type || '').toString().toLowerCase();

    if (key.includes('github')) return (
        <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z" /></svg>
    );
    if (key.includes('bitbucket')) return (
        <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M.778 1.213a.768.768 0 00-.768.892l3.263 19.81c.084.5.515.868 1.022.873H19.95a.772.772 0 00.77-.646l3.27-20.03a.768.768 0 00-.768-.891zM14.52 15.53H9.522L8.17 8.466h7.561z" /></svg>
    );
    if (key.includes('jira')) return (
        <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M11.571 11.513H0a5.218 5.218 0 005.232 5.215h2.13v2.057A5.215 5.215 0 0012.575 24V12.518a1.005 1.005 0 00-1.005-1.005zm5.723-5.756H5.736a5.215 5.215 0 005.215 5.214h2.129v2.058a5.218 5.218 0 005.215 5.214V6.758a1.001 1.001 0 00-1.001-1.001zM23.013 0H11.455a5.215 5.215 0 005.215 5.215h2.129v2.057A5.215 5.215 0 0024.013 12.487V1.005A1.005 1.005 0 0023.013 0z" /></svg>
    );
    if (key.includes('confluence')) return (
        <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M.87 18.257c-.248.382-.53.875-.763 1.245a.764.764 0 00.255 1.04l4.965 3.054a.764.764 0 001.058-.26c.199-.332.488-.853.783-1.37C9.12 18.464 11.062 17.7 15.39 19.774l5.14 2.47a.764.764 0 001.004-.39l2.18-5.032a.764.764 0 00-.384-1.003c-1.2-.558-3.57-1.672-5.14-2.47-6.886-3.3-12.27-2.205-17.32 4.908zm22.26-12.514c.249-.382.53-.875.764-1.245a.764.764 0 00-.256-1.04L18.673.404a.764.764 0 00-1.058.26c-.199.332-.488.853-.783 1.37-1.953 3.502-3.895 4.266-8.223 2.192L3.47 1.756a.764.764 0 00-1.004.39L.286 7.178a.764.764 0 00.384 1.003c1.2.558 3.57 1.672 5.14 2.47 6.886 3.3 12.27 2.205 17.32-4.908z" /></svg>
    );

    if (key === 'project') return (
        <span style={{fontSize: '16px'}}>📁</span>
    );

    return <span style={{fontSize: '16px'}}>📦</span>;
}
