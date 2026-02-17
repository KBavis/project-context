import { useState, useEffect } from 'react';
import { api } from '../services/api';
import Button from './Button';
import './IngestionJobsView.css';

export default function IngestionJobsView({ projectId }) {
    const [jobs, setJobs] = useState([]);
    const [loading, setLoading] = useState(false);
    const [creatingJob, setCreatingJob] = useState(false);

    useEffect(() => {
        if (projectId) {
            loadJobs();
            const interval = setInterval(loadJobs, 5000); // Poll every 5 seconds
            return () => clearInterval(interval);
        }
    }, [projectId]);

    const loadJobs = async () => {
        try {
            const data = await api.ingestion.list(projectId);
            const mappedJobs = data.map(job => ({
                ...job,
                status: mapStatus(job.processing_status),
                created_at: job.start_time,
                completed_at: job.end_time
            }));
            setJobs(mappedJobs);
        } catch (err) {
            console.error('Failed to load jobs:', err);
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

    const handleCreateJob = async () => {
        setCreatingJob(true);
        try {
            await api.ingestion.create(projectId);
            await loadJobs();
        } catch (err) {
            alert('Failed to create ingestion job: ' + err.message);
        } finally {
            setCreatingJob(false);
        }
    };

    if (!projectId) {
        return (
            <div className="jobs-empty">
                <div className="empty-icon">⚙️</div>
                <h3>No Project Selected</h3>
                <p>Select a project to view its ingestion jobs</p>
            </div>
        );
    }

    return (
        <div className="jobs-container">
            <div className="jobs-header">
                <h2>Ingestion Jobs</h2>
                <Button
                    size="sm"
                    onClick={handleCreateJob}
                    loading={creatingJob}
                    icon="▶"
                >
                    Run Ingestion
                </Button>
            </div>

            {jobs.length === 0 ? (
                <div className="jobs-empty">
                    <div className="empty-icon">⚙️</div>
                    <h3>No Ingestion Jobs</h3>
                    <p>Click "Run Ingestion" to start processing your data sources</p>
                </div>
            ) : (
                <div className="jobs-list">
                    {jobs.map((job) => (
                        <div key={job.id} className="job-card fade-in">
                            <div className="job-header">
                                <div className="job-id">
                                    Job #{job.id.substring(0, 8)}
                                </div>
                                <div className={`job-status status-${job.status}`}>
                                    {getStatusIcon(job.status)} {job.status}
                                </div>
                            </div>

                            <div className="job-details">
                                {job.data_source_id && (
                                    <div className="job-detail">
                                        <span className="detail-label">Data Source:</span>
                                        <span className="detail-value">{job.data_source_id.substring(0, 8)}...</span>
                                    </div>
                                )}

                                {job.created_at && (
                                    <div className="job-detail">
                                        <span className="detail-label">Created:</span>
                                        <span className="detail-value">
                                            {new Date(job.created_at).toLocaleString()}
                                        </span>
                                    </div>
                                )}

                                {job.completed_at && (
                                    <div className="job-detail">
                                        <span className="detail-label">Completed:</span>
                                        <span className="detail-value">
                                            {new Date(job.completed_at).toLocaleString()}
                                        </span>
                                    </div>
                                )}

                                {job.error && (
                                    <div className="job-error">
                                        <span className="detail-label">Error:</span>
                                        <span className="error-text">{job.error}</span>
                                    </div>
                                )}
                            </div>

                            {job.status === 'running' && (
                                <div className="job-progress">
                                    <div className="progress-bar">
                                        <div className="progress-fill pulse"></div>
                                    </div>
                                </div>
                            )}
                        </div>
                    ))}
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
