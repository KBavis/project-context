import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { api } from '../services/api';
import { useProjects } from './ProjectContext';

const IngestionJobContext = createContext();

export function useIngestionJobs() {
    const context = useContext(IngestionJobContext);
    if (!context) {
        throw new Error('useIngestionJobs must be used within an IngestionJobProvider');
    }
    return context;
}

export function IngestionJobProvider({ children }) {
    const { selectedProject, startPolling } = useProjects();
    const [ingestionJobs, setIngestionJobs] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    const fetchIngestionJobs = useCallback(async (silent = false) => {
        if (!selectedProject) {
            setIngestionJobs([]);
            return;
        }
        if (!silent) setLoading(true);
        try {
            const data = await api.ingestion.list(selectedProject.id);
            setIngestionJobs(data);
        } catch (err) {
            if (!silent) setError(err.message);
        } finally {
            if (!silent) setLoading(false);
        }
    }, [selectedProject]);

    useEffect(() => {
        fetchIngestionJobs();
    }, [fetchIngestionJobs]);

    // Automatically poll if any jobs are currently running
    useEffect(() => {
        const isRunning = ingestionJobs.some(j => 
            j.processing_status === 'IN_PROGRESS' || j.processing_status === 'PENDING'
        );
        if (!isRunning) return;

        const interval = setInterval(() => fetchIngestionJobs(true), 5000);
        return () => clearInterval(interval);
    }, [ingestionJobs, fetchIngestionJobs]);

    const createIngestionJob = async (dataSourceId) => {
        try {
            const raw = await api.ingestion.create(dataSourceId);
            // Normalize response shape to match list endpoint format
            const job = {
                ...raw,
                id: raw.ingestion_job_id || raw.id,
                data_source_id: raw.data_source_id || dataSourceId,
                processing_status: raw.status?.value || raw.status || 'IN_PROGRESS',
            };
            setIngestionJobs(prev => [job, ...prev]);
            if (selectedProject) {
                startPolling(selectedProject.id);
            }
            return job;
        } catch (err) {
            console.error('Failed to create ingestion job:', err);
            throw err;
        }
    };

    const value = {
        ingestionJobs,
        loading,
        error,
        createIngestionJob,
        fetchIngestionJobs
    };

    return (
        <IngestionJobContext.Provider value={value}>
            {children}
        </IngestionJobContext.Provider>
    );
}
