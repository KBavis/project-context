import { useState, useEffect } from 'react';
import Modal from './Modal';
import Button from './Button';
import { useProjects, useConversations } from '../contexts/index';
import '../styles/CreateConversationModal.css';

const PROVIDERS = {
    openai: {
        label: 'OpenAI',
        apiValue: 'OpenAI',
        models: [
            { id: 'gpt-4o-mini', label: 'GPT-4o Mini (Cheapest)', value: 'gpt-4o-mini' },
            { id: 'gpt-4.1-mini', label: 'More Intelligent Mode (Balanced) - gpt-4.1-mini', value: 'gpt-4.1-mini' },
            { id: 'gpt-4.1', label: 'Most Intelligent Mode (Higher Cost) - gpt-4.1', value: 'gpt-4.1' }
        ],
        defaultModel: 'gpt-4.1-mini'
    },
    ollama: {
        label: 'Ollama (Local)',
        apiValue: 'Ollama',
        models: [
            { id: 'gpt-oss:latest', label: 'gpt-oss:latest', value: 'gpt-oss:latest' }
        ],
        defaultModel: 'gpt-oss:latest'
    }
};

export default function CreateConversationModal({ isOpen, onClose }) {
    const { projects, selectedProject } = useProjects();
    const { createConversation } = useConversations();
    const [selectedProjectId, setSelectedProjectId] = useState('');
    const [provider, setProvider] = useState('openai');
    const [model, setModel] = useState(PROVIDERS.openai.defaultModel);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');

    // Pre-select project if one is already selected in the UI
    useEffect(() => {
        if (isOpen && selectedProject) {
            setSelectedProjectId(selectedProject.id);
        }
    }, [isOpen, selectedProject]);

    const handleProviderChange = (e) => {
        const newProvider = e.target.value;
        setProvider(newProvider);
        setModel(PROVIDERS[newProvider].defaultModel);
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
            // We don't reset everything if the user might want to create another one with same settings?
            // But usually closing modal resets state.
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
                        {PROVIDERS[provider].models.map((m) => (
                            <option key={m.id} value={m.value}>
                                {m.label}
                            </option>
                        ))}
                    </select>
                    {provider === 'openai' && (
                        <p className="field-hint">
                            Choose <strong>gpt-4.1-mini</strong> for a stronger balanced model, or <strong>gpt-4.1</strong> for highest quality at higher cost.
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
