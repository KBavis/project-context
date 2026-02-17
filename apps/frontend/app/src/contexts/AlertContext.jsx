import { createContext, useContext, useState, useCallback, useMemo } from 'react';

const AlertContext = createContext();

export function useAlert() {
    const context = useContext(AlertContext);
    if (!context) {
        throw new Error('useAlert must be used within an AlertProvider');
    }
    return context;
}

export function AlertProvider({ children }) {
    const [alerts, setAlerts] = useState([]);

    const showAlert = useCallback((message, type = 'success', duration = 5000) => {
        const id = Date.now();
        setAlerts((prev) => [...prev, { id, message, type }]);

        if (duration > 0) {
            setTimeout(() => {
                setAlerts((prev) => prev.filter((a) => a.id !== id));
            }, duration);
        }
    }, []);

    const removeAlert = useCallback((id) => {
        setAlerts((prev) => prev.filter((a) => a.id !== id));
    }, []);

    const value = useMemo(() => ({
        showAlert,
        removeAlert,
        alerts
    }), [showAlert, removeAlert, alerts]);

    return (
        <AlertContext.Provider value={value}>
            {children}
        </AlertContext.Provider>
    );
}
