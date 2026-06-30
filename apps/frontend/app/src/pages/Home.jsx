import { useState } from 'react';
import ChatInterface from '../components/ChatInterface';
import CreateConversationModal from '../components/CreateConversationModal';
import CreateProjectModal from '../components/CreateProjectModal';
import DataSourcesView from '../components/DataSourcesView';
import MCPConfigsView from '../components/MCPConfigsView';
import IngestionJobsView from '../components/IngestionJobsView';
import AlertContainer from '../components/Alert';
import { useProjects, useConversations } from '../contexts/index';
import '../styles/App.css';

export default function Home({ view }) {
    const [currentView, setCurrentView] = useState(view || 'chat');
    const { projects, selectedProject, selectProject } = useProjects();
    const { conversations, selectedConversation, selectConversation } = useConversations();
    const [showCreateConversation, setShowCreateConversation] = useState(false);
    const [showCreateProject, setShowCreateProject] = useState(false);

    return (
        <div className="app">
            {/* Sidebar */}
            <aside className="sidebar">
                <div className="sidebar-header">
                    <h1 className="app-title">
                        <span className="app-icon">🧠</span>
                        Contextualized
                    </h1>
                </div>

                <nav className="sidebar-nav">
                    <button
                        className={`nav-item ${currentView === 'chat' ? 'active' : ''}`}
                        onClick={() => setCurrentView('chat')}
                    >
                        <span className="nav-icon">💬</span>
                        <span>Chat</span>
                    </button>

                    <button
                        className={`nav-item ${currentView === 'dataSources' ? 'active' : ''}`}
                        onClick={() => setCurrentView('dataSources')}
                    >
                        <span className="nav-icon">📁</span>
                        <span>Data Sources</span>
                    </button>

                    <button
                        className={`nav-item ${currentView === 'ingestion' ? 'active' : ''}`}
                        onClick={() => setCurrentView('ingestion')}
                    >
                        <span className="nav-icon">⚙️</span>
                        <span>Refresh History</span>
                    </button>

                    <button
                        className={`nav-item ${currentView === 'mcp' ? 'active' : ''}`}
                        onClick={() => setCurrentView('mcp')}
                    >
                        <span className="nav-icon">⚡</span>
                        <span>MCP Configs</span>
                    </button>
                </nav>

                <div className="sidebar-section">
                    <div className="section-header">
                        <h3>Projects</h3>
                        <button
                            className="icon-button"
                            onClick={() => setShowCreateProject(true)}
                            title="Create project"
                        >
                            +
                        </button>
                    </div>

                    <div className="projects-list">
                        {projects.map(project => (
                            <button
                                key={project.id}
                                className={`project-item ${selectedProject?.id === project.id ? 'active' : ''}`}
                                onClick={() => selectProject(project)}
                            >
                                <span className="project-icon">📦</span>
                                <span className="project-name">{project.project_name || project.name}</span>
                            </button>
                        ))}
                    </div>
                </div>

                {currentView === 'chat' && (
                    <div className="sidebar-section">
                        <div className="section-header">
                            <h3>Conversations</h3>
                            <button
                                className="icon-button"
                                onClick={() => setShowCreateConversation(true)}
                                title="Create conversation"
                            >
                                +
                            </button>
                        </div>

                        <div className="conversations-list">
                            {conversations.map(conv => (
                                <button
                                    key={conv.id}
                                    className={`conversation-item ${selectedConversation?.id === conv.id ? 'active' : ''}`}
                                    onClick={() => selectConversation(conv)}
                                >
                                    <span className="conversation-icon">💬</span>
                                    <div className="conversation-info">
                                        <span className="conversation-title">
                                            {conv.summary || 'New Conversation'}
                                        </span>
                                        <span className="conversation-meta">
                                            {conv.ll_model_name || 'Default Model'}
                                        </span>
                                    </div>
                                </button>
                            ))}
                        </div>
                    </div>
                )}
            </aside>

            {/* Main Content */}
            <main className="main-content">
                {currentView === 'chat' && (
                    <ChatInterface conversationId={selectedConversation?.id} />
                )}

                {currentView === 'dataSources' && (
                    <DataSourcesView projectId={selectedProject?.id} />
                )}

                {currentView === 'ingestion' && (
                    <IngestionJobsView projectId={selectedProject?.id} />
                )}

                {currentView === 'mcp' && (
                    <MCPConfigsView />
                )}
            </main>

            {/* Modals */}
            <CreateConversationModal
                isOpen={showCreateConversation}
                onClose={() => setShowCreateConversation(false)}
            />

            <CreateProjectModal
                isOpen={showCreateProject}
                onClose={() => setShowCreateProject(false)}
            />

            <AlertContainer />
        </div>
    );
}
