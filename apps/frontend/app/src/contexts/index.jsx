import { ProjectProvider } from './ProjectContext';
import { ConversationProvider } from './ConversationContext';
import { DataSourcesProvider } from './DataSourcesContext';
import { IngestionJobProvider } from './IngestionJobContext';

export function AppProvider({ children }) {
    return (
        <ProjectProvider>
            <ConversationProvider>
                <DataSourcesProvider>
                    <IngestionJobProvider>
                        {children}
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
