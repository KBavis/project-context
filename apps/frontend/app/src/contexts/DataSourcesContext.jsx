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
        if (!selectedProject) {
            setDataSources([]);
            return;
        }
        setLoading(true);
        try {
            const data = await api.dataSources.list(selectedProject.id);
            setDataSources(data);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, [selectedProject]);

    useEffect(() => {
        fetchDataSources();
    }, [fetchDataSources]);

    const createDataSource = async (type, config) => {
        if (!selectedProject) throw new Error('No project selected');
        try {
            const ds = await api.dataSources.create(selectedProject.id, type, config);
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
