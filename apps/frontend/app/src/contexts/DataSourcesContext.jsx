import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { api } from '../services/api';
import { useProjects } from './ProjectContext';

const DataSourcesContext = createContext();

export function useDataSources() {
    const context = useContext(DataSourcesContext);
    if (!context) {
        throw new Error('useDataSources must be used within a DataSourcesProvider');
    }
    return context;
}

export function DataSourcesProvider({ children }) {
    const { selectedProject } = useProjects();
    const [dataSources, setDataSources] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    const fetchDataSources = useCallback(async () => {
        setLoading(true);
        try {
            // Fetch all data sources globally instead of filtering by project
            const data = await api.dataSources.list();
            setDataSources(data);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchDataSources();
    }, [fetchDataSources]);

    const createDataSource = async (type, config, projectIds) => {
        const ids = Array.isArray(projectIds) ? projectIds : [selectedProject?.id].filter(Boolean);
        if (ids.length === 0) throw new Error('No projects specified');

        try {
            const ds = await api.dataSources.create(ids, type, config);
            setDataSources(prev => [...prev, ds]);
            return ds;
        } catch (err) {
            console.error('Failed to create data source:', err);
            throw err;
        }
    };

    const deleteDataSource = async (id) => {
        try {
            await api.dataSources.delete(id);
            setDataSources(prev => prev.filter(ds => ds.id !== id));
        } catch (err) {
            console.error('Failed to delete data source:', err);
            throw err;
        }
    };

    const value = {
        dataSources,
        loading,
        error,
        createDataSource,
        deleteDataSource,
        fetchDataSources
    };

    return (
        <DataSourcesContext.Provider value={value}>
            {children}
        </DataSourcesContext.Provider>
    );
}
