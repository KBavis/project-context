import { useState, useEffect, useMemo } from 'react';
import Modal from './Modal';
import Button from './Button';
import { useProjects, useConversations } from '../contexts/index';
import '../styles/CreateConversationModal.css';

// Whether the Azure endpoint is configured as a multi-vendor gateway (mirrors
// the backend AZURE_MULTI_VENDOR_GATEWAY flag). When off, Azure only offers
// OpenAI models; non-OpenAI vendors (Claude/Gemini) are hidden.
const VITE_AZURE_MULTI_VENDOR_GATEWAY = import.meta.env.VITE_AZURE_MULTI_VENDOR_GATEWAY === 'true';

// Azure sub-categories: vendor families available through the Azure gateway
const AZURE_VENDORS = {
    openai: {
        label: 'OpenAI',
        models: [
            { id: 'gpt-4o', label: 'GPT-4o', value: 'gpt-4o', hint: 'Fast, capable general-purpose model.' },
            { id: 'gpt-5.4', label: 'GPT-5.4 (Recommended)', value: 'gpt-5.4', hint: 'Recommended — the best balance of speed and intelligence. Fastest to respond for most questions.' },
        ],
        defaultModel: 'gpt-5.4',
    },
    // Non-OpenAI vendors are only reachable when Azure is a multi-vendor gateway.
    ...(VITE_AZURE_MULTI_VENDOR_GATEWAY
        ? {
            claude: {
                label: 'Claude',
                models: [
                    { id: 'claude-sonnet-4-5', label: 'Claude Sonnet 4.5', value: 'claude-sonnet-4-5', hint: 'Strong reasoning at moderate speed.' },
                    { id: 'claude-opus-4-6', label: 'Claude Opus 4.6 (Most intelligent, slower)', value: 'claude-opus-4-6', hint: 'Highest reasoning quality, but noticeably slower to respond — especially on deeper questions. Choose it when depth matters more than speed.' },
                ],
                defaultModel: 'claude-sonnet-4-5',
            },
        }
        : {}),
    // TODO: Re-enable Gemini in multi-vendor approach once its streaming is fixed.

};

const PROVIDERS = {
    azure: {
        label: 'Azure',
        apiValue: 'Azure',
        // Models are driven by the selected vendor sub-filter
        vendors: AZURE_VENDORS,
        defaultVendor: 'openai',
    },
    openai: {
        label: 'OpenAI (Direct)',
        apiValue: 'OpenAI',
        models: [
            { id: 'gpt-4o-mini', label: 'GPT-4o Mini (Cheapest)', value: 'gpt-4o-mini' },
            { id: 'gpt-4.1-mini', label: 'GPT-4.1 Mini (Balanced)', value: 'gpt-4.1-mini' },
            { id: 'gpt-4.1', label: 'GPT-4.1 (Most Capable)', value: 'gpt-4.1' },
        ],
        defaultModel: 'gpt-4.1-mini',
    },
    ollama: {
        label: 'Ollama (Local)',
        apiValue: 'Ollama',
        models: [
            { id: 'gpt-oss:latest', label: 'gpt-oss:latest', value: 'gpt-oss:latest' },
        ],
        defaultModel: 'gpt-oss:latest',
    },
};

export default function CreateConversationModal({ isOpen, onClose }) {
    const { projects, selectedProject } = useProjects();
    const { createConversation } = useConversations();
    const [selectedProjectId, setSelectedProjectId] = useState('');
    const [provider, setProvider] = useState('azure');
    const [azureVendor, setAzureVendor] = useState(PROVIDERS.azure.defaultVendor);
    const [model, setModel] = useState(AZURE_VENDORS[PROVIDERS.azure.defaultVendor].defaultModel);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');

    // Derive the visible model list based on provider (and vendor for Azure)
    const availableModels = useMemo(() => {
        const prov = PROVIDERS[provider];
        if (prov.vendors) {
            return prov.vendors[azureVendor].models;
        }
        return prov.models;
    }, [provider, azureVendor]);

    // Hint for the currently selected model (speed / intelligence tradeoff).
    const selectedModelHint = useMemo(
        () => availableModels.find((m) => m.value === model)?.hint,
        [availableModels, model]
    );

    // Pre-select project if one is already selected in the UI
    useEffect(() => {
        if (isOpen && selectedProject) {
            setSelectedProjectId(selectedProject.id);
        }
    }, [isOpen, selectedProject]);

    const handleProviderChange = (e) => {
        const newProvider = e.target.value;
        setProvider(newProvider);

        const prov = PROVIDERS[newProvider];
        if (prov.vendors) {
            // Azure — reset to default vendor & its default model
            const defaultVendor = prov.defaultVendor;
            setAzureVendor(defaultVendor);
            setModel(prov.vendors[defaultVendor].defaultModel);
        } else {
            setModel(prov.defaultModel);
        }
    };

    const handleVendorChange = (e) => {
        const newVendor = e.target.value;
        setAzureVendor(newVendor);
        setModel(AZURE_VENDORS[newVendor].defaultModel);
    };

    const handleSubmit = async (e) => {
        e.preventDefault();

        if (!selectedProjectId) {
            setError('Please select a project');
            return;
        }

        setLoading(true);
        setError('');

        try {
            await createConversation(selectedProjectId, model, PROVIDERS[provider].apiValue);
            onClose();
            setSelectedProjectId('');
        } catch (err) {
            setError(err.message || 'Failed to create conversation');
        } finally {
            setLoading(false);
        }
    };

    return (
        <Modal
            isOpen={isOpen}
            onClose={onClose}
            title="Create New Conversation"
            size="md"
            actions={
                <>
                    <Button type="button" variant="ghost" onClick={onClose}>
                        Cancel
                    </Button>
                    <Button form="create-conversation-form" type="submit" loading={loading}>
                        Create Conversation
                    </Button>
                </>
            }
        >
            <form id="create-conversation-form" onSubmit={handleSubmit} className="create-conversation-form">
                {!selectedProject && (
                    <div className="form-field">
                        <label className="input-label">
                            Select Project
                            <span className="input-required">*</span>
                        </label>
                        <select
                            value={selectedProjectId}
                            onChange={(e) => setSelectedProjectId(e.target.value)}
                            className="input"
                            required
                        >
                            <option value="">Choose a project...</option>
                            {projects.map((project) => (
                                <option key={project.id} value={project.id}>
                                    {project.project_name || project.name}
                                </option>
                            ))}
                        </select>
                    </div>
                )}

                <div className="form-field">
                    <label className="input-label">
                        LLM Provider
                        <span className="input-required">*</span>
                    </label>
                    <select
                        value={provider}
                        onChange={handleProviderChange}
                        className="input"
                        required
                    >
                        {Object.entries(PROVIDERS).map(([id, info]) => (
                            <option key={id} value={id}>
                                {info.label}
                            </option>
                        ))}
                    </select>
                </div>

                {/* Azure vendor sub-filter */}
                {provider === 'azure' && (
                    <div className="form-field">
                        <label className="input-label">
                            Model Family
                        </label>
                        <select
                            value={azureVendor}
                            onChange={handleVendorChange}
                            className="input"
                        >
                            {Object.entries(AZURE_VENDORS).map(([id, info]) => (
                                <option key={id} value={id}>
                                    {info.label}
                                </option>
                            ))}
                        </select>
                    </div>
                )}

                <div className="form-field">
                    <label className="input-label">
                        Model
                        <span className="input-required">*</span>
                    </label>
                    <select
                        value={model}
                        onChange={(e) => setModel(e.target.value)}
                        className="input"
                        required
                    >
                        {availableModels.map((m) => (
                            <option key={m.id} value={m.value}>
                                {m.label}
                            </option>
                        ))}
                    </select>
                    {selectedModelHint && (
                        <p className="field-hint">{selectedModelHint}</p>
                    )}
                    {provider === 'azure' && (
                        <p className="field-hint">
                            All models are routed through the Azure gateway. Use the Model Family filter to narrow by vendor.
                        </p>
                    )}
                    {provider === 'openai' && (
                        <p className="field-hint">
                            Direct OpenAI API access. Requires a valid <strong>OPENAI_API_KEY</strong>.
                        </p>
                    )}
                </div>

                {error && (
                    <div className="error-message">{error}</div>
                )}
            </form>
        </Modal>
    );
}
