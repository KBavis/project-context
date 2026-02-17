import { useAlert } from '../contexts/AlertContext';
import '../styles/Alert.css';

export default function AlertContainer() {
    const { alerts, removeAlert } = useAlert();

    return (
        <div className="alert-container">
            {alerts.map((alert) => (
                <div
                    key={alert.id}
                    className={`alert alert-${alert.type} fade-in-right`}
                >
                    <div className="alert-content">
                        <span className="alert-icon">
                            {alert.type === 'success' ? '✅' : alert.type === 'error' ? '❌' : 'ℹ️'}
                        </span>
                        <span className="alert-message">{alert.message}</span>
                    </div>
                    <button
                        className="alert-close"
                        onClick={() => removeAlert(alert.id)}
                    >
                        ✕
                    </button>
                </div>
            ))}
        </div>
    );
}
