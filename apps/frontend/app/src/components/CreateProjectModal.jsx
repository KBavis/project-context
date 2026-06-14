import { useState, useRef, useEffect } from 'react';
import Modal from './Modal';
import Input from './Input';
import Button from './Button';
import { useProjects } from '../contexts/index';

export default function CreateProjectModal({ isOpen, onClose }) {
    const { createProject } = useProjects();
    const [projectName, setProjectName] = useState('');
    const [description, setDescription] = useState('');
    const [parentIssues, setParentIssues] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const lastInputRef = useRef(null);

    const addIssueRow = () => {
        setParentIssues(prev => [...prev, '']);
    };

    const updateIssue = (index, value) => {
        setParentIssues(prev => prev.map((v, i) => i === index ? value : v));
    };

    const removeIssue = (index) => {
        setParentIssues(prev => prev.filter((_, i) => i !== index));
    };

    // Auto-focus the newest input when a row is added
    useEffect(() => {
        if (parentIssues.length > 0) {
            lastInputRef.current?.focus();
        }
    }, [parentIssues.length]);

    const handleSubmit = async (e) => {
        e.preventDefault();

        if (!projectName.trim()) {
            setError('Project name is required');
            return;
        }

        const finalIssues = parentIssues.map(i => i.trim()).filter(Boolean);

        setLoading(true);
        setError('');

        try {
            await createProject(projectName, description, finalIssues);
            onClose();
            setProjectName('');
            setDescription('');
            setParentIssues([]);
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

                {/* Parent Issues */}
                <div className="form-field">
                    <div className="issue-field-header">
                        <label className="input-label">Parent Issues</label>
                        <button
                            type="button"
                            className="issue-add-btn"
                            onClick={addIssueRow}
                            aria-label="Add parent issue"
                        >
                            + Add Issue
                        </button>
                    </div>

                    {parentIssues.length === 0 && (
                        <p className="input-hint">
                            Add issue keys (e.g. PROJ-123) to scope repository syncing to commits linked to these issues.
                        </p>
                    )}

                    {parentIssues.length > 0 && (
                        <div className="issue-rows">
                            {parentIssues.map((issue, index) => (
                                <div key={index} className="issue-row">
                                    <input
                                        ref={index === parentIssues.length - 1 ? lastInputRef : null}
                                        type="text"
                                        className="input issue-row-input"
                                        value={issue}
                                        onChange={e => updateIssue(index, e.target.value)}
                                        placeholder={`e.g. PROJ-${100 + index + 1}`}
                                    />
                                    <button
                                        type="button"
                                        className="issue-remove-btn"
                                        onClick={() => removeIssue(index)}
                                        aria-label="Remove issue"
                                    >
                                        ×
                                    </button>
                                </div>
                            ))}
                        </div>
                    )}
                </div>

                {error && projectName && (
                    <div className="error-message">{error}</div>
                )}
            </form>
        </Modal>
    );
}
