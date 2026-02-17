import { useState } from 'react';
import Modal from './Modal';
import Input from './Input';
import Button from './Button';
import { useProjects } from '../contexts/index';

export default function CreateProjectModal({ isOpen, onClose }) {
    const { createProject } = useProjects();
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
            await createProject(projectName, description);
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
        <Modal
            isOpen={isOpen}
            onClose={onClose}
            title="Create New Project"
            size="md"
            actions={
                <>
                    <Button type="button" variant="ghost" onClick={onClose}>
                        Cancel
                    </Button>
                    <Button form="create-project-form" type="submit" loading={loading}>
                        Create Project
                    </Button>
                </>
            }
        >
            <form id="create-project-form" onSubmit={handleSubmit} className="create-conversation-form">
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
            </form>
        </Modal>
    );
}
