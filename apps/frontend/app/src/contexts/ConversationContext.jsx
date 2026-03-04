import { createContext, useContext, useState, useEffect } from 'react';
import { api } from '../services/api';
import { useProjects } from './ProjectContext';

const ConversationContext = createContext();

export function useConversations() {
    const context = useContext(ConversationContext);
    if (!context) {
        throw new Error('useConversations must be used within a ConversationProvider');
    }
    return context;
}

export function ConversationProvider({ children }) {
    const { selectedProject } = useProjects();
    const [conversations, setConversations] = useState([]);
    const [selectedConversation, setSelectedConversation] = useState(null);
    const [messages, setMessages] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    useEffect(() => {
        const loadConversations = async () => {
            if (!selectedProject) {
                setConversations([]);
                return;
            }
            setLoading(true);
            try {
                const data = await api.conversations.list();
                const filtered = data.filter(c => c.project_id === selectedProject.id);
                setConversations(filtered);
            } catch (err) {
                setError(err.message);
            } finally {
                setLoading(false);
            }
        };
        loadConversations();
    }, [selectedProject]);

    useEffect(() => {
        const loadMessages = async () => {
            if (!selectedConversation) {
                setMessages([]);
                return;
            }
            try {
                const [messagesData, citationsData] = await Promise.all([
                    api.messages.list(selectedConversation.id),
                    api.citations.list(selectedConversation.id),
                ]);

                // Group citations by message_id for O(1) lookup
                const citationsByMessage = citationsData.reduce((acc, citation) => {
                    if (!acc[citation.message_id]) acc[citation.message_id] = [];
                    acc[citation.message_id].push(citation);
                    return acc;
                }, {});

                // Attach citations to their respective messages
                const messagesWithCitations = messagesData.map(msg => ({
                    ...msg,
                    citations: citationsByMessage[msg.id] ?? [],
                }));

                setMessages(messagesWithCitations);
            } catch (err) {
                console.error('Failed to load messages:', err);
            }
        };
        loadMessages();
    }, [selectedConversation]);


    const createConversation = async (projectId, llModelName, llModelProvider) => {
        try {
            const conv = await api.conversations.create(projectId, llModelName, llModelProvider);
            setConversations(prev => [...prev, conv]);
            setSelectedConversation(conv);
            return conv;
        } catch (err) {
            console.error('Failed to create conversation:', err);
            throw err;
        }
    };

    const selectConversation = (conv) => setSelectedConversation(conv);

    const value = {
        conversations,
        selectedConversation,
        messages,
        loading,
        error,
        createConversation,
        selectConversation,
        setMessages, // Useful for streaming or optimistic updates
    };

    return (
        <ConversationContext.Provider value={value}>
            {children}
        </ConversationContext.Provider>
    );
}
