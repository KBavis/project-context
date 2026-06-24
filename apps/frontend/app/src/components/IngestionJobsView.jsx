import { useEffect } from 'react';
import { useIngestionJobs, useDataSources } from '../contexts/index';
import '../styles/IngestionJobsView.css';

export default function IngestionJobsView() {
    const { ingestionJobs: jobs, loading, fetchIngestionJobs } = useIngestionJobs();
    const { dataSources } = useDataSources();

    useEffect(() => {
        fetchIngestionJobs();
    }, [fetchIngestionJobs]);

    const mapStatus = (status) => {
        if (!status) return 'pending';
        const s = status.toUpperCase();
        if (s === 'IN_PROGRESS') return 'running';
        if (s === 'SUCCESS') return 'completed';
        if (s === 'FAILED') return 'failed';
        return status.toLowerCase();
    };

    const getDataSourceName = (dsId) => {
        const ds = dataSources.find(d => d.id === dsId);
        return ds ? (ds.name || ds.url || dsId) : dsId;
    };


    return (
        <div className="jobs-container">
            <div className="jobs-header">
                <h2>All Ingestion Jobs</h2>
            </div>

            {jobs.length === 0 && !loading ? (
                <div className="jobs-empty">
                    <div className="empty-icon">⚙️</div>
                    <h3>No Ingestion Jobs</h3>
                    <p>Jobs will appear here once started from the Data Sources view</p>
                </div>
            ) : (
                <div className="jobs-list">
                    {[...jobs].sort((a, b) => {
                        const aTime = a.end_time || a.start_time || a.created_at;
                        const bTime = b.end_time || b.start_time || b.created_at;
                        return new Date(bTime) - new Date(aTime);
                    }).map((job) => {
                        const status = mapStatus(job.processing_status);
                        return (
                            <div key={job.id} className="job-card fade-in">
                                <div className="job-header">
                                    <div className="job-id">
                                        Job #{job.id}
                                    </div>
                                    <div className={`job-status status-${status}`}>
                                        {getStatusIcon(status)} {status}
                                    </div>
                                </div>

                                <div className="job-details">
                                    <div className="job-detail">
                                        <span className="detail-label">Data Source:</span>
                                        <span className="detail-value">{getDataSourceName(job.data_source_id)}</span>
                                    </div>

                                    {job.start_time && (
                                        <div className="job-detail">
                                            <span className="detail-label">Started:</span>
                                            <span className="detail-value">
                                                {new Date(job.start_time).toLocaleString()}
                                            </span>
                                        </div>
                                    )}

                                    {job.end_time && (
                                        <div className="job-detail">
                                            <span className="detail-label">Finished:</span>
                                            <span className="detail-value">
                                                {new Date(job.end_time).toLocaleString()}
                                            </span>
                                        </div>
                                    )}
                                </div>

                                {status === 'running' && (
                                    <div className="job-progress">
                                        <div className="progress-bar">
                                            <div className="progress-fill pulse"></div>
                                        </div>
                                    </div>
                                )}

                                {job.error && (
                                    <div className="job-error">
                                        <span className="error-text">{job.error}</span>
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}

function getStatusIcon(status) {
    const icons = {
        pending: '⏳',
        running: '⚙️',
        completed: '✅',
        failed: '❌',
    };
    return icons[status?.toLowerCase()] || '•';
}
