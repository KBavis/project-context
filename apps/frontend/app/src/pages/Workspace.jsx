import { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useProjects, useConversations, useDataSources } from '../contexts/index';
import ChatInterface from '../components/ChatInterface';
import CreateConversationModal from '../components/CreateConversationModal';
import DataSourcesView from '../components/DataSourcesView';
import Modal from '../components/Modal';
import Button from '../components/Button';

import AlertContainer from '../components/Alert';
import '../styles/Workspace.css';

export default function Workspace() {
    const { projectId } = useParams();
    const navigate = useNavigate();
    const { projects, selectProject } = useProjects();
    const { conversations, selectedConversation, selectConversation, deleteConversation, getStream } = useConversations();
    const { dataSources } = useDataSources();
    
    const [view, setView] = useState('chat');
    const [showCreateConv, setShowCreateConv] = useState(false);
    const [confirmModal, setConfirmModal] = useState({ isOpen: false, title: '', message: '', onConfirm: null, confirmLabel: 'Confirm' });
    const hasSelected = useRef(false);

    useEffect(() => {
        if (hasSelected.current) return;
        const p = projects.find(p => p.id === projectId);
        if (p) {
            selectProject(p);
            hasSelected.current = true;
        }
    }, [projectId, projects, selectProject]);

    // Reset ref when projectId changes (navigating to a different workspace)
    useEffect(() => {
        hasSelected.current = false;
    }, [projectId]);

    const project = projects.find(p => p.id === projectId);
    
    if (!project) {
        return <div className="workspace-loading">Loading Workspace...</div>;
    }

    const projectDataSources = dataSources.filter(ds => ds.linked_projects?.includes(project.id));
    const repoSources = projectDataSources.filter(ds => ds.type === 'REPOSITORY' && ds.scope_by_issues);
    const hasIssueScopedRepo = repoSources.length > 0;

    const closeConfirmModal = () => setConfirmModal(prev => ({ ...prev, isOpen: false }));

    const requestDeleteConversation = (conv) => {
        setConfirmModal({
            isOpen: true,
            title: 'Delete Conversation',
            message: `Are you sure you want to delete '${conv.summary || 'New Chat'}'? This action cannot be undone.`,
            confirmLabel: 'Delete',
            onConfirm: async () => {
                try {
                    await deleteConversation(conv.id);
                } catch {
                    /* handled in context */
                }
                closeConfirmModal();
            }
        });
    };

    return (
        <div className="workspace-layout fade-in">
            <aside className="workspace-sidebar">
                <div className="workspace-brand" onClick={() => navigate('/home')}>
                    <span className="back-icon">←</span> Dashboard
                </div>
                
                <div className="workspace-header">
                    <h2>{project.project_name || project.name}</h2>
                    <p className="workspace-meta-label">Active Workspace</p>
                    {project.description && (
                        <p className="workspace-description">{project.description}</p>
                    )}
                    {project.parent_issues && project.parent_issues.length > 0 && (
                        <div className="workspace-issues">
                            <span className="issues-label">Parent Issues</span>
                            <div className="issues-list">
                                {project.parent_issues.map((issue, idx) => (
                                    <a 
                                        key={idx} 
                                        className="issue-tag" 
                                        href={issue} 
                                        target="_blank" 
                                        rel="noopener noreferrer"
                                        title={issue}
                                    >
                                        🔗 {issue.split('/').pop()}
                                    </a>
                                ))}
                            </div>
                        </div>
                    )}
                    <div className="workspace-stats">
                        <div className="stat-item">
                            <span className="stat-value">{projectDataSources.length}</span>
                            <span className="stat-label">Data Sources</span>
                        </div>
                        <div className="stat-item">
                            <span className="stat-value">{conversations.length}</span>
                            <span className="stat-label">Conversations</span>
                        </div>
                    </div>
                </div>
                
                <nav className="workspace-nav">
                    <div className="nav-group">
                        <button onClick={() => setView('chat')} className={view === 'chat' ? 'active' : ''}>
                            <span className="nav-icon">💬</span> Conversations
                        </button>
                        <button onClick={() => setView('datasources')} className={view === 'datasources' ? 'active' : ''}>
                            <span className="nav-icon">📁</span> Data Sources
                        </button>

                    </div>
                </nav>

                {view === 'chat' && (
                    <div className="workspace-conversations">
                         <div className="conv-header">
                             <h3>Recent Chats</h3>
                             <button className="add-conv-btn" onClick={() => setShowCreateConv(true)}>+</button>
                         </div>
                         <div className="conv-list">
                             {conversations.length === 0 ? (
                                 <p className="empty-text">No conversations yet.</p>
                             ) : (
                                 conversations.map(c => (
                                     <div key={c.id} className="conv-item-row" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                                         <button 
                                            onClick={() => selectConversation(c)} 
                                            className={`conv-item ${selectedConversation?.id === c.id ? 'active' : ''}`}
                                            style={{ flex: 1, minWidth: 0 }}
                                         >
                                             <span className="conv-icon">💬</span>
                                             <span className="conv-title">{c.summary || 'New Chat'}</span>
                                             {getStream(c.id).isStreaming && (
                                                 <span className="conv-processing-dot" title="Agent is processing..." />
                                             )}
                                         </button>
                                         <button
                                             className="conv-delete-btn"
                                             title="Delete conversation"
                                             onClick={() => requestDeleteConversation(c)}
                                             style={{ background: 'none', border: 'none', cursor: 'pointer', opacity: 0.6, fontSize: '0.85rem', padding: '4px' }}
                                         >
                                             🗑️
                                         </button>
                                     </div>
                                 ))
                             )}
                         </div>
                    </div>
                )}
            </aside>
            <main className="workspace-main">
                {view === 'chat' && <ChatInterface conversationId={selectedConversation?.id} />}
                {view === 'datasources' && <DataSourcesView projectId={project.id} />}

            </main>
            <CreateConversationModal isOpen={showCreateConv} onClose={() => setShowCreateConv(false)} />
            <Modal
                isOpen={confirmModal.isOpen}
                onClose={closeConfirmModal}
                title={confirmModal.title}
                actions={
                    <>
                        <Button size='sm' variant='secondary' onClick={closeConfirmModal}>Cancel</Button>
                        <Button
                            size='sm'
                            variant={confirmModal.confirmLabel === 'Delete' ? 'danger' : 'primary'}
                            onClick={confirmModal.onConfirm}
                        >
                            {confirmModal.confirmLabel}
                        </Button>
                    </>
                }
            >
                <p>{confirmModal.message}</p>
            </Modal>
            <AlertContainer />
        </div>
    );
}
