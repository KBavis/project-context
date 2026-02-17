import { useState } from 'react';
import Modal from './Modal';
import Button from './Button';
import { useProjects, useConversations } from '../contexts/index';
import '../styles/CreateConversationModal.css';

export default function CreateConversationModal({ isOpen, onClose }) {
    const { projects } = useProjects();
    const { createConversation } = useConversations();
    const [selectedProjectId, setSelectedProjectId] = useState('');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');

    const handleSubmit = async (e) => {
        e.preventDefault();

        if (!selectedProjectId) {
            setError('Please select a project');
            return;
        }

        setLoading(true);
        setError('');

        try {
            await createConversation(selectedProjectId);
            onClose();
            setSelectedProjectId('');
        } catch (err) {
            setError(err.message || 'Failed to create conversation');
        } finally {
            setLoading(false);
        }
    };

    return (
        <Modal isOpen={isOpen} onClose={onClose} title="Create New Conversation" size="md">
            <form onSubmit={handleSubmit} className="create-conversation-form">
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

                {error && (
                    <div className="error-message">{error}</div>
                )}

                <div className="form-actions">
                    <Button type="button" variant="ghost" onClick={onClose}>
                        Cancel
                    </Button>
                    <Button type="submit" loading={loading}>
                        Create Conversation
                    </Button>
                </div>
            </form>
        </Modal>
    );
}
