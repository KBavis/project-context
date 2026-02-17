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
    const { selectedProject } = useProjects();
    const [ingestionJobs, setIngestionJobs] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    const fetchIngestionJobs = useCallback(async () => {
        if (!selectedProject) {
            setIngestionJobs([]);
            return;
        }
        setLoading(true);
        try {
            const data = await api.ingestion.list(selectedProject.id);
            setIngestionJobs(data);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, [selectedProject]);

    useEffect(() => {
        fetchIngestionJobs();
    }, [fetchIngestionJobs]);

    const createIngestionJob = async (dataSourceId) => {
        if (!selectedProject) throw new Error('No project selected');
        try {
            const job = await api.ingestion.create(selectedProject.id, dataSourceId);
            setIngestionJobs(prev => [...prev, job]);
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
