import { ProjectProvider } from './ProjectContext';
import { ConversationProvider } from './ConversationContext';
import { DataSourcesProvider } from './DataSourcesContext';
import { IngestionJobProvider } from './IngestionJobContext';
import { AlertProvider } from './AlertContext';

export function AppProvider({ children }) {
    return (
        <ProjectProvider>
            <ConversationProvider>
                <DataSourcesProvider>
                    <IngestionJobProvider>
                        <AlertProvider>
                            {children}
                        </AlertProvider>
                    </IngestionJobProvider>
                </DataSourcesProvider>
            </ConversationProvider>
        </ProjectProvider>
    );
}

export * from './ProjectContext';
export * from './ConversationContext';
export * from './DataSourcesContext';
export * from './IngestionJobContext';
export * from './AlertContext';
