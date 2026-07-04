import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useProjects } from '../contexts/index';
import DataSourcesView from '../components/DataSourcesView';
import JobsView from '../components/JobsView';
import MCPConfigsView from '../components/MCPConfigsView';
import CreateProjectModal from '../components/CreateProjectModal';
import AlertContainer from '../components/Alert';
import '../styles/Dashboard.css';

export default function Dashboard() {
    const navigate = useNavigate();
    const { projects } = useProjects();
    const [view, setView] = useState('projects'); 
    const [showCreate, setShowCreate] = useState(false);

    return (
        <div className="dashboard-layout fade-in">
             <header className="dashboard-header">
                 <div className="header-left">
                     <span className="app-icon">🧠</span>
                     <h1>Contextualized</h1>
                 </div>
                 <nav className="dashboard-nav">
                     <button onClick={() => setView('projects')} className={view === 'projects' ? 'active' : ''}>Projects</button>
                     <button onClick={() => setView('datasources')} className={view === 'datasources' ? 'active' : ''}>Data Sources</button>
                     <button onClick={() => setView('jobs')} className={view === 'jobs' ? 'active' : ''}>Sync History</button>
                     <button onClick={() => setView('mcp')} className={view === 'mcp' ? 'active' : ''}>MCP Configs</button>
                 </nav>
             </header>
             <main className="dashboard-main">
                  {view === 'projects' && (
                      <div className="projects-container">
                          <div className="projects-header-actions">
                              <h2>Your Workspaces</h2>
                              <p className="projects-header-subtitle">Select a project to enter its workspace, or create a new one.</p>
                          </div>
                          <div className="projects-grid">
                              <div className="project-card create-card" onClick={() => setShowCreate(true)}>
                                  <div className="create-icon">+</div>
                                  <h3>Create New Project</h3>
                                  <p>Start a new isolated workspace</p>
                              </div>
                              {projects.map(p => (
                                  <div key={p.id} className="project-card" onClick={() => navigate(`/workspace/${p.id}`)}>
                                      <div className="project-card-icon">📦</div>
                                      <h3>{p.project_name || p.name}</h3>
                                      {p.description && (
                                          <p className="project-card-desc">{p.description}</p>
                                      )}
                                      <p className="project-card-meta">Click to enter workspace →</p>
                                  </div>
                              ))}
                          </div>
                      </div>
                  )}
                  {view === 'datasources' && <DataSourcesView />}
                  {view === 'jobs' && <JobsView systemWide={true} />}
                  {view === 'mcp' && <MCPConfigsView />}
             </main>
             <CreateProjectModal isOpen={showCreate} onClose={() => setShowCreate(false)} />
             <AlertContainer />
        </div>
    );
}
