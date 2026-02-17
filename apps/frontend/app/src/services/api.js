// API Configuration
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';

// Helper function to handle API responses
async function handleResponse(response) {
    if (!response.ok) {
        const error = await response.json().catch(() => ({ message: 'An error occurred' }));
        throw new Error(error.message || `HTTP ${response.status}`);
    }
    return response.json();
}

// API Service
export const api = {
    // Conversation endpoints
    conversations: {
        create: async (projectId, llModelName = null, llModelProvider = null) => {
            const response = await fetch(`${API_BASE_URL}/conversation/`, { // Fixed trailing slash/path
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    project_id: projectId,
                    ll_model_name: llModelName,
                    ll_model_provider: llModelProvider,
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
            const response = await fetch(`${API_BASE_URL}/message/${conversationId}`, {
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
        create: async (projectName, description = '') => {
            const response = await fetch(`${API_BASE_URL}/projects/`, { // Fixed path
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: projectName,
                    description: description,
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
    },

    // Data Source endpoints
    dataSources: {
        list: async (projectId) => {
            if (projectId) {
                const response = await fetch(`${API_BASE_URL}/data/sources/${projectId}`); // Use project-specific list
                return handleResponse(response);
            }
            const response = await fetch(`${API_BASE_URL}/data/sources/`); // Use global list
            return handleResponse(response);
        },

        create: async (projectId, dataSourceType, config) => {
            const response = await fetch(`${API_BASE_URL}/data/sources/`, { // Fixed path
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    provider: dataSourceType,
                    url: config.url || '',
                    name: config.name || '',
                    project_ids: [projectId]
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
    },

    // Ingestion Job endpoints
    ingestion: {
        create: async (projectId, dataSourceId = null) => {
            // Backend expects POST /ingestion/jobs/{data_source_id} or /{data_source_id}/{project_id}
            let url = `${API_BASE_URL}/ingestion/jobs/${dataSourceId}`;
            if (projectId) {
                url += `/${projectId}`;
            }
            const response = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({}), // No body required by backend params
            });
            return handleResponse(response); // Backend returns object directly
        },

        getStatus: async (jobId) => {
            // Backend currently doesn't have specific get-status endpoint, use list or assume missing
            const response = await fetch(`${API_BASE_URL}/ingestion/jobs/${jobId}`);
            return handleResponse(response);
        },

        list: async (projectId) => {
            // Backend has GET /ingestion/jobs/ (all)
            // Ignoring projectId for now as backend returns all
            const response = await fetch(`${API_BASE_URL}/ingestion/jobs/`);
            return handleResponse(response);
        },
    },
};
