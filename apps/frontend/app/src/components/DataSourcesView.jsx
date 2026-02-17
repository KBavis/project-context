import { useDataSources } from '../contexts/DataSourcesContext';
import Button from './Button';
import '../styles/DataSourcesView.css';

export default function DataSourcesView({ projectId }) {
    const { dataSources, loading, error, deleteDataSource } = useDataSources();

    const handleDelete = async (dataSourceId) => {
        if (!confirm('Are you sure you want to delete this data source?')) {
            return;
        }

        try {
            await deleteDataSource(dataSourceId);
        } catch (err) {
            alert('Failed to delete data source');
        }
    };

    if (!projectId) {
        return (
            <div className="data-sources-empty">
                <div className="empty-icon">📁</div>
                <h3>No Project Selected</h3>
                <p>Select a project to view its data sources</p>
            </div>
        );
    }

    if (loading && dataSources.length === 0) {
        return (
            <div className="data-sources-loading">
                <div className="spinner spin"></div>
                <p>Loading data sources...</p>
            </div>
        );
    }

    return (
        <div className="data-sources-container">
            <div className="data-sources-header">
                <h2>Data Sources</h2>
                <Button size="sm">+ Add Data Source</Button>
            </div>

            {error && (
                <div className="error-message">{error}</div>
            )}

            {dataSources.length === 0 ? (
                <div className="data-sources-empty">
                    <div className="empty-icon">📁</div>
                    <h3>No Data Sources</h3>
                    <p>Add a data source to get started</p>
                </div>
            ) : (
                <div className="data-sources-grid">
                    {dataSources.map((ds) => (
                        <div key={ds.id} className="data-source-card fade-in">
                            <div className="data-source-icon">
                                {getDataSourceIcon(ds.type)}
                            </div>

                            <div className="data-source-info">
                                <h3 className="data-source-name">{ds.name || ds.type}</h3>
                                <p className="data-source-type">{ds.type}</p>

                                {ds.config && (
                                    <div className="data-source-meta">
                                        {Object.entries(ds.config).slice(0, 3).map(([key, value]) => (
                                            <div key={key} className="meta-item">
                                                <span className="meta-key">{key}:</span>
                                                <span className="meta-value">{String(value).substring(0, 30)}</span>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>

                            <div className="data-source-actions">
                                <Button
                                    size="sm"
                                    variant="ghost"
                                    onClick={() => handleDelete(ds.id)}
                                >
                                    Delete
                                </Button>
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}

function getDataSourceIcon(type) {
    const icons = {
        github: '🔗',
        file: '📄',
        web: '🌐',
        database: '🗄️',
    };
    return icons[type?.toLowerCase()] || '📦';
}
