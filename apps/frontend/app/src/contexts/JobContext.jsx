import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { api } from '../services/api';
import { useProjects } from './ProjectContext';

const JobContext = createContext();

export function useJobs() {
    const context = useContext(JobContext);
    if (!context) {
        throw new Error('useJobs must be used within an JobProvider');
    }
    return context;
}

export function JobProvider({ children }) {
    const { selectedProject, startPolling } = useProjects();
    const [jobs, setJobs] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    const fetchJobs = useCallback(async (silent = false) => {
        if (!selectedProject) {
            setJobs([]);
            return;
        }
        if (!silent) setLoading(true);
        try {
            const data = await api.jobs.listByProject(selectedProject.id);
            setJobs(data);
        } catch (err) {
            if (!silent) setError(err.message);
        } finally {
            if (!silent) setLoading(false);
        }
    }, [selectedProject]);

    useEffect(() => {
        fetchJobs();
    }, [fetchJobs]);

    // Automatically poll if any jobs are currently running
    useEffect(() => {
        const isRunning = jobs.some(j => {
            const status = j.status ? String(j.status).toUpperCase() : '';
            return status === 'IN_PROGRESS' || status === 'PENDING' || status === 'RUNNING';
        });
        if (!isRunning) return;

        const interval = setInterval(() => fetchJobs(true), 5000);
        return () => clearInterval(interval);
    }, [jobs, fetchJobs]);

    const createJob = async (dataSourceId = null) => {
        try {
            if (!selectedProject) throw new Error("No project selected");
            const raw = await api.jobs.create(selectedProject.id, dataSourceId);
            // The creation endpoint might just return { message, project_id } now,
            // we should just start polling project sync state and jobs.
            if (selectedProject) {
                startPolling(selectedProject.id);
            }
            setTimeout(() => fetchJobs(true), 1000);
            return raw;
        } catch (err) {
            console.error('Failed to create job:', err);
            throw err;
        }
    };

    const value = {
        jobs,
        loading,
        error,
        createJob,
        fetchJobs
    };

    return (
        <JobContext.Provider value={value}>
            {children}
        </JobContext.Provider>
    );
}
