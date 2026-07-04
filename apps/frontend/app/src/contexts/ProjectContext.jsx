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
            setSelectedProject(prev => {
                if (prev) return prev;
                // Restore the last-selected project across reloads/navigation so a user's
                // conversations don't "disappear" when state resets to the first project.
                const storedId = localStorage.getItem('selectedProjectId');
                const restored = storedId ? data.find(p => p.id === storedId) : null;
                return restored || (data.length > 0 ? data[0] : null);
            });
        } catch (err) {
            setError(err.message);
            console.error('Failed to load projects:', err);
        } finally {
            setLoading(false);
        }
    }, []);

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

    const selectProject = useCallback((project) => {
        setSelectedProject(project);
    }, []);

    // Persist the active project so navigating away or reloading returns to the same
    // context (otherwise state resets to the first project and hides other projects' conversations).
    useEffect(() => {
        if (selectedProject?.id) {
            localStorage.setItem('selectedProjectId', selectedProject.id);
        }
    }, [selectedProject?.id]);

    useEffect(() => {
        if (!selectedProject) return;

        const checkInitialSync = async () => {
            try {
                const res = await api.diff.getSyncStatus(selectedProject.id);
                if (res.overall_status === 'in_progress') {
                    setSyncingProjects(prev => ({ ...prev, [selectedProject.id]: { isSyncing: true, ...res } }));
                } else {
                    setSyncingProjects(prev => ({ ...prev, [selectedProject.id]: { isSyncing: false, ...res } }));
                }
            } catch (e) {
                console.error('Failed to check sync status', e);
            }
        };
        
        checkInitialSync();
    }, [selectedProject?.id]);

    const startPolling = useCallback((projectId) => {
        setSyncingProjects(prev => ({ ...prev, [projectId]: { isSyncing: true } }));
        let intervalTime = 2000;
        let elapsed = 0;

        const poll = async () => {
            if (elapsed >= 300000) { // 5 minutes ceiling
                // Stop polling but reflect the real, current sync state (no stale message)
                try {
                    const finalRes = await api.diff.getSyncStatus(projectId);
                    setSyncingProjects(prev => ({ ...prev, [projectId]: { isSyncing: false, ...finalRes } }));
                } catch (e) {
                    setSyncingProjects(prev => ({ ...prev, [projectId]: { isSyncing: false } }));
                }
                return;
            }

            try {
                const statusRes = await api.diff.getSyncStatus(projectId);
                if (statusRes.is_ready) {
                    setSyncingProjects(prev => ({ ...prev, [projectId]: { isSyncing: false, ...statusRes } }));
                    return;
                } else if (statusRes.overall_status === 'failed') {
                    setSyncingProjects(prev => ({ ...prev, [projectId]: { isSyncing: false, ...statusRes } }));
                    return; // Stop polling on failure
                } else {
                    setSyncingProjects(prev => ({ ...prev, [projectId]: { isSyncing: true, ...statusRes } }));
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
