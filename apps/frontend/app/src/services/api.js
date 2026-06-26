// API Configuration
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';

// Helper function to handle API responses
async function handleResponse(response) {
    if (!response.ok) {
        const error = await response.json().catch(() => ({ message: 'An error occurred' }));
        throw new Error(error.detail || error.message || `HTTP ${response.status}`);
    }
    return response.json();
}

// API Service
export const api = {
    // Conversation endpoints
    conversations: {
        create: async (projectId, llModelName = null, llModelProvider = null) => {
            const providerMap = {
                openai: 'OpenAI',
                ollama: 'Ollama',
            };
            const normalizedProvider = llModelProvider
                ? (providerMap[llModelProvider] || llModelProvider)
                : llModelProvider;

            const response = await fetch(`${API_BASE_URL}/conversation/`, { // Fixed trailing slash/path
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    project_id: projectId,
                    ll_model_name: llModelName,
                    ll_model_provider: normalizedProvider,
                }),
            });
            return handleResponse(response);
        },

        get: async (conversationId) => {
            const response = await fetch(`${API_BASE_URL}/conversation/${conversationId}`);
            return handleResponse(response);
        },

        list: async () => {
            const response = await fetch(`${API_BASE_URL}/conversation/`); // Fixed path
            return handleResponse(response);
        },

        delete: async (conversationId) => {
            const response = await fetch(`${API_BASE_URL}/conversation/${conversationId}`, {
                method: 'DELETE',
            });
            return handleResponse(response);
        },
    },

    // Message endpoints
    messages: {
        send: async (conversationId, content) => {
            const response = await fetch(`${API_BASE_URL}/message/${conversationId}/agentic`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content }),
            });
            return response; // Return raw response for streaming
        },

        list: async (conversationId) => {
            const response = await fetch(`${API_BASE_URL}/message/${conversationId}`); // Fixed path from messages to message
            return handleResponse(response);
        },
    },


    // Project endpoints
    projects: {
        create: async (projectName, description = '', parentIssues = []) => {
            const response = await fetch(`${API_BASE_URL}/projects/`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: projectName,
                    description: description,
                    parent_issues: parentIssues,
                }),
            });
            return handleResponse(response);
        },

        get: async (projectId) => {
            // NOTE: Backend currently only has Create/List for projects. 
            // This might fail if endpoint doesn't exist.
            const response = await fetch(`${API_BASE_URL}/projects/${projectId}`);
            return handleResponse(response);
        },

        list: async () => {
            const response = await fetch(`${API_BASE_URL}/projects/`); // Fixed path
            return handleResponse(response);
        },

        delete: async (projectId) => {
            const response = await fetch(`${API_BASE_URL}/projects/${projectId}`, {
                method: 'DELETE',
            });
            return handleResponse(response);
        },

        linkDataSource: async (projectId, dataSourceId) => {
            const response = await fetch(`${API_BASE_URL}/projects/${projectId}/data-sources/${dataSourceId}`, {
                method: 'POST',
            });
            return handleResponse(response);
        },

        unlinkDataSource: async (projectId, dataSourceId) => {
            const response = await fetch(`${API_BASE_URL}/projects/${projectId}/data-sources/${dataSourceId}`, {
                method: 'DELETE',
            });
            return handleResponse(response);
        },
    },

    // Data Source endpoints
    dataSources: {
        getAll: async (projectId) => {
            if (projectId) {
                const response = await fetch(`${API_BASE_URL}/data/sources/${projectId}`); // Use project-specific list
                return handleResponse(response);
            }
            const response = await fetch(`${API_BASE_URL}/data/sources/`); // Use global list
            return handleResponse(response);
        },

        create: async (provider, config, projectIds) => {
            const response = await fetch(`${API_BASE_URL}/data/sources/`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    provider,
                    type: config.type,
                    url: config.url,
                    name: config.name,
                    branch: config.branch,
                    scope_by_issues: config.scope_by_issues,
                    project_ids: projectIds
                }),
            });
            return handleResponse(response);
        },

        delete: async (dataSourceId) => {
            const response = await fetch(`${API_BASE_URL}/data/sources/${dataSourceId}`, {
                method: 'DELETE',
            });
            return handleResponse(response);
        },

        linkMcp: async (dataSourceId, mcpConfigId) => {
            const response = await fetch(`${API_BASE_URL}/data/sources/${dataSourceId}/mcp/configs/${mcpConfigId}`, {
                method: 'POST',
            });
            return handleResponse(response);
        },
        update: async (dataSourceId, updates) => {
            const response = await fetch(`${API_BASE_URL}/data/sources/${dataSourceId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(updates),
            });
            return handleResponse(response);
        },
    },

    // MCP Configuration endpoints
    mcp: {
        getConfigs: async () => {
            const response = await fetch(`${API_BASE_URL}/mcp/configs/`);
            return handleResponse(response);
        },

        createConfig: async (config) => {
            const response = await fetch(`${API_BASE_URL}/mcp/configs/`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(config),
            });
            return handleResponse(response);
        },

        deleteConfig: async (configId) => {
            const response = await fetch(`${API_BASE_URL}/mcp/configs/${configId}`, {
                method: 'DELETE',
            });
            return handleResponse(response);
        },
    },

    // Ingestion Job endpoints
    ingestion: {
        create: async (dataSourceId) => {
            const url = `${API_BASE_URL}/ingestion/jobs/${dataSourceId}`;
            const response = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({}), // No body required by backend params
            });
            return handleResponse(response);
        },

        getStatus: async (jobId) => {
            // Backend currently doesn't have specific get-status endpoint, use list or assume missing
            const response = await fetch(`${API_BASE_URL}/ingestion/jobs/${jobId}`);
            return handleResponse(response);
        },

        list: async () => {
            // Backend has GET /ingestion/jobs/ (all)
            // Ignoring projectId for now as backend returns all
            const response = await fetch(`${API_BASE_URL}/ingestion/jobs/`, { cache: 'no-store' });
            return handleResponse(response);
        },
    },
    // Diff endpoints
    diff: {
        getSyncStatus: async (projectId) => {
            const response = await fetch(`${API_BASE_URL}/projects/${projectId}/sync-status`);
            const data = await handleResponse(response);
            return {
                ...data,
                is_initial_sync_complete: data.is_ready,
                status: data.overall_status
            };
        },
        getSyncJobs: async (projectId, dataSourceId) => {
            const response = await fetch(`${API_BASE_URL}/diff/sync/jobs/${projectId}/${dataSourceId}`);
            return handleResponse(response);
        },
        triggerSync: async (projectId, dataSourceId) => {
            const response = await fetch(`${API_BASE_URL}/diff/sync/${projectId}/${dataSourceId}`, {
                method: 'POST',
            });
            return handleResponse(response);
        }
    },
};

export default api;
