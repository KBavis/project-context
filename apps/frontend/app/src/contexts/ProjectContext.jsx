import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { api } from '../services/api';

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

    const createProject = async (name, description) => {
        try {
            const newProject = await api.projects.create(name, description);
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

    const value = {
        projects,
        selectedProject,
        loading,
        error,
        fetchProjects,
        createProject,
        selectProject
    };

    return (
        <ProjectContext.Provider value={value}>
            {children}
        </ProjectContext.Provider>
    );
}
