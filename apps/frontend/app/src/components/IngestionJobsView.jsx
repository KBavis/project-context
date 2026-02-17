import { useState, useEffect } from 'react';
import { useIngestionJobs } from '../contexts/IngestionJobContext';
import Button from './Button';
import '../styles/IngestionJobsView.css';

export default function IngestionJobsView({ projectId }) {
    const { ingestionJobs: jobs, loading, createIngestionJob, fetchIngestionJobs } = useIngestionJobs();
    const [creatingJob, setCreatingJob] = useState(false);

    useEffect(() => {
        if (projectId) {
            const interval = setInterval(fetchIngestionJobs, 5000); // Poll every 5 seconds
            return () => clearInterval(interval);
        }
    }, [projectId, fetchIngestionJobs]);

    const handleCreateJob = async () => {
        setCreatingJob(true);
        try {
            await createIngestionJob();
        } catch (err) {
            alert('Failed to create ingestion job: ' + err.message);
        } finally {
            setCreatingJob(false);
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

            {jobs.length === 0 && !loading ? (
                <div className="jobs-empty">
                    <div className="empty-icon">⚙️</div>
                    <h3>No Ingestion Jobs</h3>
                    <p>Click "Run Ingestion" to start processing your data sources</p>
                </div>
            ) : (
                <div className="jobs-list">
                    {jobs.map((job) => {
                        const status = mapStatus(job.processing_status);
                        return (
                            <div key={job.id} className="job-card fade-in">
                                <div className="job-header">
                                    <div className="job-id">
                                        Job #{job.id.substring(0, 8)}
                                    </div>
                                    <div className={`job-status status-${status}`}>
                                        {getStatusIcon(status)} {status}
                                    </div>
                                </div>

                                <div className="job-details">
                                    {job.data_source_id && (
                                        <div className="job-detail">
                                            <span className="detail-label">Data Source:</span>
                                            <span className="detail-value">{job.data_source_id.substring(0, 8)}...</span>
                                        </div>
                                    )}

                                    {job.start_time && (
                                        <div className="job-detail">
                                            <span className="detail-label">Created:</span>
                                            <span className="detail-value">
                                                {new Date(job.start_time).toLocaleString()}
                                            </span>
                                        </div>
                                    )}

                                    {job.end_time && (
                                        <div className="job-detail">
                                            <span className="detail-label">Completed:</span>
                                            <span className="detail-value">
                                                {new Date(job.end_time).toLocaleString()}
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

                                {status === 'running' && (
                                    <div className="job-progress">
                                        <div className="progress-bar">
                                            <div className="progress-fill pulse"></div>
                                        </div>
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
