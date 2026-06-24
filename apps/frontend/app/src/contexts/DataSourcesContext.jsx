import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import api from '../services/api';
import { useProjects } from './ProjectContext';

const DataSourcesContext = createContext();

export const useDataSources = () => {
    const context = useContext(DataSourcesContext);
    if (!context) {
        throw new Error('useDataSources must be used within a DataSourcesProvider');
    }
    return context;
};

export const DataSourcesProvider = ({ children }) => {
    const [dataSources, setDataSources] = useState([]);
    const [mcpConfigs, setMcpConfigs] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const { startPolling } = useProjects();

    const fetchData = useCallback(async () => {
        setLoading(true);
        try {
            const [dsData, mcpData] = await Promise.all([
                api.dataSources.getAll(),
                api.mcp.getConfigs()
            ]);
            setDataSources(dsData);
            setMcpConfigs(mcpData);
            setError(null);
        } catch (err) {
            setError('Failed to fetch data sources');
            console.error(err);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchData();
    }, [fetchData]);

    const deleteDataSource = async (id) => {
        try {
            await api.dataSources.delete(id);
            setDataSources(prev => prev.filter(ds => ds.id !== id));
        } catch (err) {
            throw err;
        }
    };


    const createDataSource = async (provider, config, projectIds) => {
        try {
            const newDataSource = await api.dataSources.create(provider, config, projectIds);
            setDataSources(prev => [...prev, newDataSource]);
            return newDataSource;
        } catch (err) {
            throw err;
        }
    };

    const createMcpConfig = async (config) => {
        try {
            const newConfig = await api.mcp.createConfig(config);
            setMcpConfigs(prev => [...prev, newConfig]);
            return newConfig;
        } catch (err) {
            throw err;
        }
    };

    const deleteMcpConfig = async (id) => {
        try {
            await api.mcp.deleteConfig(id);
            setMcpConfigs(prev => prev.filter(c => c.id !== id));
        } catch (err) {
            throw err;
        }
    };

    const linkProjectToDataSource = async (projectId, dataSourceId) => {
        try {
            await api.projects.linkDataSource(projectId, dataSourceId);
            await fetchData();
            startPolling(projectId);
        } catch (err) {
            throw err;
        }
    };

    const unlinkProjectFromDataSource = async (projectId, dataSourceId) => {
        try {
            await api.projects.unlinkDataSource(projectId, dataSourceId);
            await fetchData();
            startPolling(projectId);
        } catch (err) {
            throw err;
        }
    };

    const linkMcpToDataSource = async (dataSourceId, mcpConfigId) => {
        try {
            await api.dataSources.linkMcp(dataSourceId, mcpConfigId);
            await fetchData();
        } catch (err) {
            throw err;
        }
    };

    const updateDataSource = async (id, updates) => {
        try {
            const updated = await api.dataSources.update(id, updates);
            setDataSources(prev => prev.map(ds => ds.id === updated.id ? updated : ds));
            return updated;
        } catch (err) {
            throw err;
        }
    };

    return (
        <DataSourcesContext.Provider value={{ 
            dataSources, 
            mcpConfigs, 
            loading, 
            error, 
            fetchData, 
            deleteDataSource, 
            createDataSource,
            updateDataSource,
            createMcpConfig,
            deleteMcpConfig,
            linkProjectToDataSource,
            unlinkProjectFromDataSource,
            linkMcpToDataSource
        }}>
            {children}
        </DataSourcesContext.Provider>
    );
};
