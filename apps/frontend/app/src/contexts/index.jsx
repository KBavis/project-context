import { ProjectProvider } from './ProjectContext';
import { ConversationProvider } from './ConversationContext';
import { DataSourcesProvider } from './DataSourcesContext';
import { JobProvider } from './JobContext';
import { AlertProvider } from './AlertContext';

export function AppProvider({ children }) {
    return (
        <AlertProvider>
            <ProjectProvider>
                <ConversationProvider>
                    <DataSourcesProvider>
                        <JobProvider>
                            {children}
                        </JobProvider>
                    </DataSourcesProvider>
                </ConversationProvider>
            </ProjectProvider>
        </AlertProvider>
    );
}

export * from './ProjectContext';
export * from './ConversationContext';
export * from './DataSourcesContext';
export * from './JobContext';
export * from './AlertContext';
