import { useNavigate } from 'react-router-dom';
import '../styles/Landing.css';

export default function Landing() {
    const navigate = useNavigate();
    return (
        <div className="landing-page">
            <div className="landing-grid">
                <div className="landing-hero">
                    <div className="hero-badge">AI-Powered Workspace</div>
                    <h1 className="hero-title">
                        <span className="hero-icon">🧠</span>
                        Contextualized
                    </h1>
                    <p className="hero-description">
                        Connect your repositories, documentation, and tools into a unified AI workspace. 
                        Ask questions, track changes, and get intelligent answers grounded in your actual codebase.
                    </p>
                    <div className="hero-features">
                        <div className="feature-pill">
                            <span>📦</span> Project Workspaces
                        </div>
                        <div className="feature-pill">
                            <span>🔄</span> Repository Sync
                        </div>
                        <div className="feature-pill">
                            <span>💬</span> Context-Aware Chat
                        </div>
                        <div className="feature-pill">
                            <span>⚡</span> MCP Integration
                        </div>
                    </div>
                    <button className="hero-cta" onClick={() => navigate('/home')}>
                        Open Dashboard
                        <span className="cta-arrow">→</span>
                    </button>
                </div>
            </div>
            <div className="landing-ambient">
                <div className="ambient-orb orb-1"></div>
                <div className="ambient-orb orb-2"></div>
            </div>
        </div>
    );
}
