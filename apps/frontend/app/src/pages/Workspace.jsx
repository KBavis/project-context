import { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useProjects, useConversations, useDataSources } from '../contexts/index';
import ChatInterface from '../components/ChatInterface';
import CreateConversationModal from '../components/CreateConversationModal';
import DataSourcesView from '../components/DataSourcesView';
import DiffSyncView from '../components/DiffSyncView';
import AlertContainer from '../components/Alert';
import '../styles/Workspace.css';

export default function Workspace() {
    const { projectId } = useParams();
    const navigate = useNavigate();
    const { projects, selectProject } = useProjects();
    const { conversations, selectedConversation, selectConversation } = useConversations();
    const { dataSources } = useDataSources();
    
    const [view, setView] = useState('chat');
    const [showCreateConv, setShowCreateConv] = useState(false);
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
                        {hasIssueScopedRepo && (
                            <button onClick={() => setView('sync')} className={view === 'sync' ? 'active' : ''}>
                                <span className="nav-icon">🔄</span> Repository Sync
                            </button>
                        )}
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
                                     <button 
                                        key={c.id} 
                                        onClick={() => selectConversation(c)} 
                                        className={`conv-item ${selectedConversation?.id === c.id ? 'active' : ''}`}
                                     >
                                         <span className="conv-icon">💭</span>
                                         <span className="conv-title">{c.summary || 'New Chat'}</span>
                                     </button>
                                 ))
                             )}
                         </div>
                    </div>
                )}
            </aside>
            <main className="workspace-main">
                {view === 'chat' && <ChatInterface conversationId={selectedConversation?.id} />}
                {view === 'datasources' && <DataSourcesView projectId={project.id} />}
                {view === 'sync' && <DiffSyncView projectId={project.id} />}
            </main>
            <CreateConversationModal isOpen={showCreateConv} onClose={() => setShowCreateConv(false)} />
            <AlertContainer />
        </div>
    );
}
