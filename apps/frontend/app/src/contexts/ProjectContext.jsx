import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { api } from '../services/api';
import { useAlert } from './AlertContext';

const ProjectContext = createContext();

export function useProjects() {
    const context = useContext(ProjectContext);
    if (!context) {
        throw new Error('useProjects must be used within a ProjectProvider');
    }
    return context;
}

export function ProjectProvider({ children }) {
    const [projects, setProjects] = useState([]);
    const [selectedProject, setSelectedProject] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [syncingProjects, setSyncingProjects] = useState({}); // projectId -> { isSyncing: boolean, error?: string }
    const { showAlert } = useAlert();

    const fetchProjects = useCallback(async () => {
        setLoading(true);
        try {
            const data = await api.projects.list();
            setProjects(data);
            if (data.length > 0 && !selectedProject) {
                setSelectedProject(data[0]);
            }
        } catch (err) {
            setError(err.message);
            console.error('Failed to load projects:', err);
        } finally {
            setLoading(false);
        }
    }, [selectedProject]);

    useEffect(() => {
        fetchProjects();
    }, [fetchProjects]);

    const createProject = async (name, description, parentIssues = []) => {
        try {
            const newProject = await api.projects.create(name, description, parentIssues);
            setProjects(prev => [...prev, newProject]);
            setSelectedProject(newProject);
            return newProject;
        } catch (err) {
            console.error('Failed to create project:', err);
            throw err;
        }
    };

    const selectProject = (project) => {
        setSelectedProject(project);
    };

    useEffect(() => {
        if (!selectedProject) return;

        const checkInitialSync = async () => {
            try {
                const res = await api.diff.getSyncStatus(selectedProject.id);
                if (!res.is_initial_sync_complete) {
                    setSyncingProjects(prev => ({ ...prev, [selectedProject.id]: { isSyncing: true, status: res.status } }));

                } else {
                    setSyncingProjects(prev => ({ ...prev, [selectedProject.id]: { isSyncing: false, status: res.status } }));
                }
            } catch (e) {
                console.error('Failed to check sync status', e);
            }
        };
        
        checkInitialSync();
    }, [selectedProject]);

    const startPolling = useCallback((projectId) => {
        setSyncingProjects(prev => ({ ...prev, [projectId]: { isSyncing: true } }));
        let intervalTime = 2000;
        let elapsed = 0;

        const poll = async () => {
            if (elapsed >= 300000) { // 5 minutes ceiling
                setSyncingProjects(prev => ({ 
                    ...prev, 
                    [projectId]: { 
                        isSyncing: false, 
                        error: 'Synchronization is taking longer than expected. Click to check state status again.' 
                    } 
                }));
                return;
            }

            try {
                const statusRes = await api.diff.getSyncStatus(projectId);
                if (statusRes.is_initial_sync_complete) {
                    setSyncingProjects(prev => ({ ...prev, [projectId]: { isSyncing: false, status: statusRes.status } }));
                    return;
                } else {
                    setSyncingProjects(prev => ({ ...prev, [projectId]: { isSyncing: true, status: statusRes.status } }));
                }
            } catch (err) {
                console.error(err);
            }

            if (intervalTime < 30000) {
                if (intervalTime === 2000) intervalTime = 5000;
                else if (intervalTime === 5000) intervalTime = 10000;
                else if (intervalTime === 10000) intervalTime = 30000;
            }

            elapsed += intervalTime;
            setTimeout(poll, intervalTime);
        };

        setTimeout(poll, intervalTime);
    }, []);

    const value = {
        projects,
        selectedProject,
        loading,
        error,
        fetchProjects,
        createProject,
        selectProject,
        syncingProjects,
        startPolling
    };

    return (
        <ProjectContext.Provider value={value}>
            {children}
        </ProjectContext.Provider>
    );
}
