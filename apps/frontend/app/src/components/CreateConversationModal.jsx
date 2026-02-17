import { useState, useEffect } from 'react';
import Modal from './Modal';
import Input from './Input';
import Button from './Button';
import { api } from '../services/api';
import './CreateConversationModal.css';

export default function CreateConversationModal({ isOpen, onClose, onCreated }) {
    const [projects, setProjects] = useState([]);
    const [selectedProject, setSelectedProject] = useState('');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');

    useEffect(() => {
        if (isOpen) {
            loadProjects();
        }
    }, [isOpen]);

    const loadProjects = async () => {
        try {
            const data = await api.projects.list();
            setProjects(data);
        } catch (err) {
            setError('Failed to load projects');
        }
    };

    const handleSubmit = async (e) => {
        e.preventDefault();

        if (!selectedProject) {
            setError('Please select a project');
            return;
        }

        setLoading(true);
        setError('');

        try {
            const conversation = await api.conversations.create(selectedProject);
            onCreated(conversation);
            onClose();
            setSelectedProject('');
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
                        value={selectedProject}
                        onChange={(e) => setSelectedProject(e.target.value)}
                        className="input"
                        required
                    >
                        <option value="">Choose a project...</option>
                        {projects.map((project) => (
                            <option key={project.id} value={project.id}>
                                {project.project_name}
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
