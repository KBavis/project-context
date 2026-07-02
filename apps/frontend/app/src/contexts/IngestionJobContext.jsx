// DEPRECATED: This file has been replaced by JobContext.jsx
// Safe to delete from your repository.
import { createContext, useContext } from 'react';

const IngestionJobContext = createContext();

export function useIngestionJobs() {
    const context = useContext(IngestionJobContext);
    if (!context) {
        throw new Error('useIngestionJobs is deprecated — use useJobs from JobContext instead');
    }
    return context;
}

export function IngestionJobProvider({ children }) {
    return children;
}
