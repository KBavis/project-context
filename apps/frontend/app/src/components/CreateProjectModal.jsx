import { useState } from 'react';
import Modal from './Modal';
import Input from './Input';
import Button from './Button';
import { api } from '../services/api';

export default function CreateProjectModal({ isOpen, onClose, onCreated }) {
    const [projectName, setProjectName] = useState('');
    const [description, setDescription] = useState('');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');

    const handleSubmit = async (e) => {
        e.preventDefault();

        if (!projectName.trim()) {
            setError('Project name is required');
            return;
        }

        setLoading(true);
        setError('');

        try {
            const project = await api.projects.create(projectName, description);
            onCreated(project);
            onClose();
            setProjectName('');
            setDescription('');
        } catch (err) {
            setError(err.message || 'Failed to create project');
        } finally {
            setLoading(false);
        }
    };

    return (
        <Modal isOpen={isOpen} onClose={onClose} title="Create New Project" size="md">
            <form onSubmit={handleSubmit} className="create-conversation-form">
                <Input
                    label="Project Name"
                    value={projectName}
                    onChange={setProjectName}
                    placeholder="Enter project name"
                    required
                    error={error && !projectName ? error : ''}
                />

                <Input
                    label="Description"
                    value={description}
                    onChange={setDescription}
                    placeholder="Enter project description (optional)"
                    multiline
                    rows={4}
                />

                {error && projectName && (
                    <div className="error-message">{error}</div>
                )}

                <div className="form-actions">
                    <Button type="button" variant="ghost" onClick={onClose}>
                        Cancel
                    </Button>
                    <Button type="submit" loading={loading}>
                        Create Project
                    </Button>
                </div>
            </form>
        </Modal>
    );
}
