import { useState, useEffect } from 'react';
import { api } from './services/api';
import Button from './components/Button';
import ChatInterface from './components/ChatInterface';
import CreateConversationModal from './components/CreateConversationModal';
import CreateProjectModal from './components/CreateProjectModal';
import DataSourcesView from './components/DataSourcesView';
import IngestionJobsView from './components/IngestionJobsView';
import './App.css';

function App() {
  const [currentView, setCurrentView] = useState('chat'); // chat, dataSources, ingestion
  const [selectedProject, setSelectedProject] = useState(null);
  const [selectedConversation, setSelectedConversation] = useState(null);
  const [projects, setProjects] = useState([]);
  const [conversations, setConversations] = useState([]);

  const [showCreateConversation, setShowCreateConversation] = useState(false);
  const [showCreateProject, setShowCreateProject] = useState(false);

  useEffect(() => {
    loadProjects();
  }, []);

  useEffect(() => {
    if (selectedProject) {
      loadConversations();
    }
  }, [selectedProject]);

  const loadProjects = async () => {
    try {
      const data = await api.projects.list();
      setProjects(data);
      if (data.length > 0 && !selectedProject) {
        setSelectedProject(data[0]);
      }
    } catch (error) {
      console.error('Failed to load projects:', error);
    }
  };

  const loadConversations = async () => {
    try {
      const data = await api.conversations.list();
      // Filter conversations by selected project
      const filtered = data.filter(c => c.project_id === selectedProject?.id);
      setConversations(filtered);
    } catch (error) {
      console.error('Failed to load conversations:', error);
    }
  };

  const handleProjectCreated = (project) => {
    setProjects(prev => [...prev, project]);
    setSelectedProject(project);
  };

  const handleConversationCreated = (conversation) => {
    setConversations(prev => [...prev, conversation]);
    setSelectedConversation(conversation);
    setCurrentView('chat');
  };

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
            <span>Ingestion Jobs</span>
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
                onClick={() => setSelectedProject(project)}
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
                  onClick={() => setSelectedConversation(conv)}
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
      </main>

      {/* Modals */}
      <CreateConversationModal
        isOpen={showCreateConversation}
        onClose={() => setShowCreateConversation(false)}
        onCreated={handleConversationCreated}
      />

      <CreateProjectModal
        isOpen={showCreateProject}
        onClose={() => setShowCreateProject(false)}
        onCreated={handleProjectCreated}
      />
    </div>
  );
}

export default App;
