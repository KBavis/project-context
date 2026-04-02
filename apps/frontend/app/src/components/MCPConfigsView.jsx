import { useState } from 'react';
import { useDataSources, useAlert } from '../contexts/index';
import Button from './Button';
import Modal from './Modal';
import '../styles/DataSourcesView.css'; // Reuse existing styles for now

export default function MCPConfigsView() {
    const { dataSources, mcpConfigs, loading, error, createMcpConfig, deleteMcpConfig, fetchData } = useDataSources();
    const { showAlert } = useAlert();
    const [showAddForm, setShowAddForm] = useState(false);
    const [deletingId, setDeletingId] = useState(null);
    const [mcpToDelete, setMcpToDelete] = useState(null);

    const [mcpConfig, setMcpConfig] = useState({
        name: '',
        transport_type: 'stdio',
        timeout: 300,
        data_source_id: '',
        config: {
            command: 'docker',
            args: '',
            cwd: '',
            env_pairs: [{ key: '', value: '' }],
            url: '',
            header_pairs: [{ key: '', value: '' }]
        }
    });

    const handleDelete = async () => {
        if (!mcpToDelete) return;
        setDeletingId(mcpToDelete.id);
        try {
            await deleteMcpConfig(mcpToDelete.id);
            showAlert('MCP Configuration deleted successfully', 'success');
            setMcpToDelete(null);
        } catch (err) {
            showAlert('Failed to delete MCP: ' + err.message, 'error');
        } finally {
            setDeletingId(null);
        }
    };

    const getFullCommand = (config) => {
        if (!config || !config.command || !config.args) return '';
        const args = Array.isArray(config.args) ? config.args : [];
        return `${config.command} ${args.join(' ')}`;
    };

    const maskSecrets = (envVars) => {
        if (!envVars) return null;
        const masked = {};
        const secretKeys = ['TOKEN', 'KEY', 'SECRET', 'PASSWORD', 'AUTH'];
        Object.keys(envVars).forEach(key => {
            if (secretKeys.some(sk => key.toUpperCase().includes(sk))) {
                masked[key] = '********';
            } else {
                masked[key] = envVars[key];
            }
        });
        return masked;
    };

    const handleAddMCP = async (e) => {
        e.preventDefault();
        try {
            let finalArgs = [];
            let envVariables = {};

            if (mcpConfig.transport_type === 'stdio') {
                envVariables = mcpConfig.config.env_pairs.reduce((acc, pair) => {
                    if (pair.key) acc[pair.key] = pair.value;
                    return acc;
                }, {});

                const userArgs = mcpConfig.config.args ? mcpConfig.config.args.split(',').map(a => a.trim()) : [];
                
                if (mcpConfig.config.command === 'docker') {
                    // Auto-construct premium Docker command
                    finalArgs = ['run', '-i', '--rm'];
                    // Add environment variable passthroughs for Docker
                    Object.keys(envVariables).forEach(key => {
                        finalArgs.push('-e', key);
                    });
                    // Append the user's image name and any extra args
                    finalArgs = [...finalArgs, ...userArgs];
                } else if (mcpConfig.config.command === 'npx') {
                    // Auto-construct premium NPX command
                    finalArgs = ['-y', ...userArgs];
                } else {
                    finalArgs = userArgs;
                }
            }

            const mcpData = {
                name: mcpConfig.name,
                transport_type: mcpConfig.transport_type,
                timeout: parseInt(mcpConfig.timeout),
                data_source_id: mcpConfig.data_source_id,
                config: mcpConfig.transport_type === 'stdio' ? {
                    command: mcpConfig.config.command,
                    args: finalArgs,
                    cwd: mcpConfig.config.cwd || null,
                    env_variables: envVariables
                } : {
                    url: mcpConfig.config.url,
                    headers: mcpConfig.config.header_pairs.reduce((acc, pair) => {
                        if (pair.key) acc[pair.key] = pair.value;
                        return acc;
                    }, {})
                }
            };

            await createMcpConfig(mcpData);
            setShowAddForm(false);
            setMcpConfig({
                name: '',
                transport_type: 'stdio',
                timeout: 300,
                data_source_id: '',
                config: {
                    command: 'docker',
                    args: '',
                    cwd: '',
                    env_pairs: [{ key: '', value: '' }],
                    url: '',
                    header_pairs: [{ key: '', value: '' }]
                }
            });
            showAlert('MCP Configuration added successfully', 'success');
            fetchData();
        } catch (err) {
            showAlert('Failed to add MCP configuration: ' + err.message, 'error');
        }
    };

    return (
        <div className="data-sources-container">
            <div className="data-sources-header">
                <div className="header-title">
                    <h2>MCP Configurations</h2>
                    <p className="header-subtitle">Manage protocol connections for your data sources</p>
                </div>
                <Button size="sm" onClick={() => setShowAddForm(!showAddForm)}>
                    {showAddForm ? 'Cancel' : '+ Create MCP Config'}
                </Button>
            </div>

            {/* Custom Delete Confirmation Modal */}
            <Modal 
                isOpen={!!mcpToDelete} 
                onClose={() => setMcpToDelete(null)}
                title="Delete MCP Configuration"
                actions={
                    <div className="form-actions-inline">
                        <Button size="sm" variant="secondary" onClick={() => setMcpToDelete(null)}>Cancel</Button>
                        <Button size="sm" variant="danger" onClick={handleDelete} loading={!!deletingId}>Delete Server</Button>
                    </div>
                }
            >
                <div className="delete-confirmation">
                    <p>Are you sure you want to delete <strong>{mcpToDelete?.name}</strong>?</p>
                    <p className="warning-text">This action cannot be undone and will disconnect its associated data source.</p>
                </div>
            </Modal>

            {showAddForm && (
                <div className="add-datasource-card fade-in">
                    <form onSubmit={handleAddMCP}>
                        <div className="form-section">
                            <h4 className="section-title">Base Configuration</h4>
                            <div className="form-row-mcp">
                                <div className="form-field flex-2">
                                    <label className="input-label">MCP Name</label>
                                    <input
                                        className="input"
                                        type="text"
                                        value={mcpConfig.name}
                                        onChange={e => setMcpConfig({ ...mcpConfig, name: e.target.value })}
                                        placeholder="e.g. GitHub Server"
                                        required
                                    />
                                </div>

                                <div className="form-field flex-2">
                                    <label className="input-label">Associated Data Source</label>
                                    <select 
                                        className="input"
                                        value={mcpConfig.data_source_id}
                                        onChange={e => setMcpConfig({ ...mcpConfig, data_source_id: e.target.value })}
                                        required
                                    >
                                        <option value="">Select a data source...</option>
                                        {dataSources.map(ds => {
                                            const hasMcp = mcpConfigs.some(c => c.data_source_id === ds.id);
                                            return (
                                                <option key={ds.id} value={ds.id} disabled={hasMcp}>
                                                    {ds.name} ({ds.provider}){hasMcp ? ' - Already Linked' : ''}
                                                </option>
                                            );
                                        })}
                                    </select>
                                </div>

                                <div className="form-field flex-1">
                                    <label className="input-label">Transport</label>
                                    <select
                                        className="input"
                                        value={mcpConfig.transport_type}
                                        onChange={e => setMcpConfig({ ...mcpConfig, transport_type: e.target.value })}
                                    >
                                        <option value="stdio">Local (STDIO)</option>
                                        <option value="http">Remote (HTTP)</option>
                                    </select>
                                </div>

                                <div className="form-field flex-1">
                                    <label className="input-label">Timeout (s)</label>
                                    <input
                                        className="input"
                                        type="number"
                                        value={mcpConfig.timeout}
                                        onChange={e => setMcpConfig({ ...mcpConfig, timeout: e.target.value })}
                                    />
                                </div>
                            </div>
                        </div>

                        <div className="form-section">
                            <h4 className="section-title">Execution Settings</h4>
                            {mcpConfig.transport_type === 'stdio' ? (
                                <div className="form-row-mcp">
                                    <div className="form-field flex-1">
                                        <label className="input-label">Service Type</label>
                                        <select
                                            className="input"
                                            value={mcpConfig.config.command}
                                            onChange={e => {
                                                setMcpConfig({ 
                                                    ...mcpConfig, 
                                                    config: { ...mcpConfig.config, command: e.target.value, args: '' } 
                                                });
                                            }}
                                        >
                                            <option value="docker">Docker Container</option>
                                            <option value="npx">NPX Package</option>
                                            <option value="python3">Python Script</option>
                                            <option value="uv">UV Tool</option>
                                            <option value="node">Node.js</option>
                                        </select>
                                    </div>
                                    <div className="form-field flex-3">
                                        <label className="input-label">
                                            {mcpConfig.config.command === 'docker' ? 'Image Name (e.g. ghcr.io/...)' : 
                                             mcpConfig.config.command === 'npx' ? 'Package Name' : 'Execution Arguments'}
                                        </label>
                                        <input
                                            className="input"
                                            type="text"
                                            value={mcpConfig.config.args}
                                            onChange={e => setMcpConfig({ ...mcpConfig, config: { ...mcpConfig.config, args: e.target.value } })}
                                            placeholder={mcpConfig.config.command === 'docker' ? "ghcr.io/github/github-mcp-server" : "@modelcontextprotocol/server-github"}
                                        />
                                        <small className="field-hint">
                                            {mcpConfig.config.command === 'docker' ? "System will automatically add 'run -i --rm' and '-e' flags for environment variables." : 
                                             mcpConfig.config.command === 'npx' ? "System will automatically add the '-y' flag." : "Separate arguments with commas."}
                                        </small>
                                    </div>
                                    <div className="form-field flex-2">
                                        <label className="input-label">Working Dir (Optional)</label>
                                        <input
                                            className="input"
                                            type="text"
                                            value={mcpConfig.config.cwd}
                                            onChange={e => setMcpConfig({ ...mcpConfig, config: { ...mcpConfig.config, cwd: e.target.value } })}
                                            placeholder="/path/to/server"
                                        />
                                    </div>
                                </div>
                            ) : (
                                <div className="form-field full-width">
                                    <label className="input-label">Server Endpoint URL</label>
                                    <input
                                        className="input"
                                        type="url"
                                        value={mcpConfig.config.url}
                                        onChange={e => setMcpConfig({ ...mcpConfig, config: { ...mcpConfig.config, url: e.target.value } })}
                                        placeholder="https://mcp.example.com"
                                        required={mcpConfig.transport_type === 'http'}
                                    />
                                </div>
                            )}
                        </div>

                        <div className="form-section">
                            <h4 className="section-title">Environment & Secrets</h4>
                            <div className="kv-editor">
                                {(mcpConfig.transport_type === 'stdio' ? mcpConfig.config.env_pairs : mcpConfig.config.header_pairs).map((pair, index) => (
                                    <div key={index} className="kv-row">
                                        <input 
                                            className="input kv-key"
                                            placeholder="KEY"
                                            value={pair.key}
                                            onChange={e => {
                                                const key = mcpConfig.transport_type === 'stdio' ? 'env_pairs' : 'header_pairs';
                                                const newPairs = [...mcpConfig.config[key]];
                                                newPairs[index].key = e.target.value;
                                                setMcpConfig({ ...mcpConfig, config: { ...mcpConfig.config, [key]: newPairs } });
                                            }}
                                        />
                                        <input 
                                            className="input kv-value"
                                            placeholder={mcpConfig.transport_type === 'stdio' ? "VALUE (Masked if secret)" : "Header Value"}
                                            value={pair.value}
                                            onChange={e => {
                                                const key = mcpConfig.transport_type === 'stdio' ? 'env_pairs' : 'header_pairs';
                                                const newPairs = [...mcpConfig.config[key]];
                                                newPairs[index].value = e.target.value;
                                                setMcpConfig({ ...mcpConfig, config: { ...mcpConfig.config, [key]: newPairs } });
                                            }}
                                        />
                                        <button 
                                            type="button" 
                                            className="kv-remove"
                                            onClick={() => {
                                                const key = mcpConfig.transport_type === 'stdio' ? 'env_pairs' : 'header_pairs';
                                                const newPairs = mcpConfig.config[key].filter((_, i) => i !== index);
                                                setMcpConfig({ ...mcpConfig, config: { ...mcpConfig.config, [key]: newPairs.length ? newPairs : [{ key: '', value: '' }] } });
                                            }}
                                        >
                                            ✕
                                        </button>
                                    </div>
                                ))}
                                <button 
                                    type="button" 
                                    className="kv-add"
                                    onClick={() => {
                                        const key = mcpConfig.transport_type === 'stdio' ? 'env_pairs' : 'header_pairs';
                                        const newPairs = [...mcpConfig.config[key], { key: '', value: '' }];
                                        setMcpConfig({ ...mcpConfig, config: { ...mcpConfig.config, [key]: newPairs } });
                                    }}
                                >
                                    + Add {mcpConfig.transport_type === 'stdio' ? 'Variable' : 'Header'}
                                </button>
                            </div>
                        </div>

                        <div className="form-actions-right">
                            <Button type="submit" size="md">Create MCP Server</Button>
                        </div>
                    </form>
                </div>
            )}

            {error && <div className="error-message">{error}</div>}

            {loading && mcpConfigs.length === 0 ? (
                <div className="data-sources-loading">
                    <div className="spinner spin"></div>
                    <p>Fetching MCP servers...</p>
                </div>
            ) : mcpConfigs.length === 0 ? (
                <div className="data-sources-empty">
                    <div className="empty-icon">🔌</div>
                    <h3>No MCP Servers Configured</h3>
                    <p>Connect your data sources using the Model Context Protocol</p>
                </div>
            ) : (
                <div className="data-sources-grid card-view">
                    {mcpConfigs.map((config) => (
                        <div key={config.id} className="data-source-wrapper full-width">
                            <div className="data-source-card fade-in premium-card">
                                <div className="data-source-main">
                                    <div className="data-source-icon" style={{ background: 'var(--primary-gradient)', color: 'white' }}>
                                        {config.transport_type === 'stdio' ? '💻' : '🌐'}
                                    </div>
                                    <div className="data-source-content">
                                        <div className="data-source-title-row">
                                            <h3 className="data-source-name" style={{ whiteSpace: 'normal' }}>{config.name}</h3>
                                            <span className="source-status active">Connected</span>
                                        </div>
                                        <div className="mcp-config-details">
                                            <div className="detail-row">
                                                <span className="detail-label">Linked To:</span>
                                                <span className="detail-value">{config.data_source?.name || 'Unknown'}</span>
                                            </div>
                                            <div className="detail-row">
                                                <span className="detail-label">Transport:</span>
                                                <span className="detail-value status-badge">{config.transport_type}</span>
                                            </div>

                                            <div className="detail-row full-width">
                                                <span className="detail-label">{config.transport_type === 'stdio' ? 'Full Command:' : 'Endpoint:'}</span>
                                                <div className="command-display-container">
                                                    <code className="detail-value code-font wrap-text">
                                                        {config.transport_type === 'stdio' ? getFullCommand(config.config) : config.config.url}
                                                    </code>
                                                    <button 
                                                        className="copy-btn-modern" 
                                                        onClick={() => {
                                                            const text = config.transport_type === 'stdio' ? getFullCommand(config.config) : config.config.url;
                                                            navigator.clipboard.writeText(text);
                                                            showAlert('Copied to clipboard', 'success');
                                                        }}
                                                        title="Copy to clipboard"
                                                    >
                                                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                                            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                                                            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                                                        </svg>
                                                        <span>Copy</span>
                                                    </button>
                                                </div>
                                            </div>

                                            {config.transport_type === 'stdio' && config.config.env_variables && Object.keys(config.config.env_variables).length > 0 && (
                                                <div className="detail-row full-width">
                                                    <span className="detail-label">Environment:</span>
                                                    <code className="detail-value code-font wrap-text">
                                                        {Object.entries(maskSecrets(config.config.env_variables)).map(([k, v]) => `${k}=${v}`).join(' ')}
                                                    </code>
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                    <div className="data-source-actions">
                                        <button 
                                            className="delete-icon-button"
                                            onClick={() => setMcpToDelete(config)}
                                            title="Delete Configuration"
                                        >
                                            🗑️
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
