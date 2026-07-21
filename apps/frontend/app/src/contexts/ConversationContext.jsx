import { createContext, useContext, useState, useEffect, useRef } from 'react';
import { api } from '../services/api';
import { useProjects } from './ProjectContext';

// Stable defaults so the per-conversation accessors don't return fresh refs each call.
const EMPTY_MESSAGES = [];
const DEFAULT_STREAM = { isStreaming: false, status: '', streamingMessage: '', streamingCitations: null };

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
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    // Per-conversation state so a stream is scoped to its conversation: a run started
    // in one conversation never touches another's view, survives navigation (including
    // to other projects), and multiple conversations can stream concurrently.
    const [messagesByConv, setMessagesByConv] = useState({});
    const [streamsByConv, setStreamsByConv] = useState({});

    // Conversations whose persisted history we've already fetched (avoids re-fetch and
    // clobbering an in-flight stream's optimistic messages).
    const loadedConvIdsRef = useRef(new Set());

    useEffect(() => {
        // Clear stale selection from previous project immediately
        // Switching projects clears the *selection* only. In-flight streams and their
        // per-conversation state are intentionally preserved so the user can navigate
        // away (even to another project) and return to a still-running answer.
        setSelectedConversation(null);

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

    // Lazily load a conversation's persisted history the first time it is selected.
    useEffect(() => {
        const loadMessages = async () => {
            if (!selectedConversation) return;
            const conv = selectedConversation;
            if (loadedConvIdsRef.current.has(conv.id)) return;
            loadedConvIdsRef.current.add(conv.id);
            try {
                const messagesData = await api.messages.list(conv.id);
                setMessagesByConv(prev => (prev[conv.id] ? prev : { ...prev, [conv.id]: messagesData }));
            } catch (err) {
                console.error('Failed to load messages:', err);
                loadedConvIdsRef.current.delete(conv.id);
            }
        };
        loadMessages();
    }, [selectedConversation]);


    const createConversation = async (projectId, llModelName, llModelProvider) => {
        try {
            const conv = await api.conversations.create(projectId, llModelName, llModelProvider);
            setConversations(prev => [conv, ...prev]);
            setSelectedConversation(conv);
            return conv;
        } catch (err) {
            console.error('Failed to create conversation:', err);
            throw err;
        }
    };

    const selectConversation = (conv) => setSelectedConversation(conv);

    // Patch a conversation in place (e.g. when the backend reports a freshly generated
    // summary/title after the first message) so the sidebar updates without a refresh.
    const updateConversation = (conversationId, patch) => {
        setConversations(prev => prev.map(c => (c.id === conversationId ? { ...c, ...patch } : c)));
        setSelectedConversation(prev => (prev?.id === conversationId ? { ...prev, ...patch } : prev));
    };

    const deleteConversation = async (conversationId) => {
        try {
            await api.conversations.delete(conversationId);
            setConversations(prev => prev.filter(c => c.id !== conversationId));
            setSelectedConversation(prev => (prev?.id === conversationId ? null : prev));
            setMessagesByConv(prev => { const next = { ...prev }; delete next[conversationId]; return next; });
            setStreamsByConv(prev => { const next = { ...prev }; delete next[conversationId]; return next; });
            loadedConvIdsRef.current.delete(conversationId);
        } catch (err) {
            console.error('Failed to delete conversation:', err);
            throw err;
        }
    };

    // Per-conversation accessors + streaming
    const getMessages = (convId) => messagesByConv[convId] || EMPTY_MESSAGES;
    const getStream = (convId) => streamsByConv[convId] || DEFAULT_STREAM;

    const patchStream = (convId, patch) =>
        setStreamsByConv(prev => ({ ...prev, [convId]: { ...(prev[convId] || DEFAULT_STREAM), ...patch } }));

    const appendMessage = (convId, msg) =>
        setMessagesByConv(prev => ({ ...prev, [convId]: [...(prev[convId] || EMPTY_MESSAGES), msg] }));

    // Fire an agentic message for a specific conversation and stream the answer into
    // THAT conversation's state. Runs independently of the current selection, so it
    // is safe to navigate away or start another conversation's run concurrently.
    const sendMessage = async (convId, content) => {
        if (!convId || !content?.trim()) return;
        if (streamsByConv[convId]?.isStreaming) return; // one in-flight run per conversation

        appendMessage(convId, { role: 'user', content, timestamp: new Date() });
        patchStream(convId, { isStreaming: true, status: 'Thinking...', streamingMessage: '', streamingCitations: null });

        let assistantMessage = '';
        let citationsMap = null;
        try {
            const response = await api.messages.send(convId, content);
            if (!response.body) throw new Error('No response body');

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });

                const lines = buffer.split('\n');
                buffer = lines.pop() || '';

                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;

                    let parsedEvent;
                    try {
                        parsedEvent = JSON.parse(line.replace('data: ', ''));
                    } catch {
                        continue;
                    }

                    if (parsedEvent.event === 'status') {
                        patchStream(convId, { status: parsedEvent.data });
                    } else if (parsedEvent.event === 'chunk') {
                        assistantMessage += parsedEvent.data;
                        patchStream(convId, { streamingMessage: assistantMessage, status: 'Generating...' });
                    } else if (parsedEvent.event === 'citations') {
                        citationsMap = parsedEvent.data;
                        patchStream(convId, { streamingCitations: parsedEvent.data });
                    } else if (parsedEvent.event === 'metadata') {
                        if (parsedEvent.data?.conversation_summary && parsedEvent.data?.conversation_id) {
                            updateConversation(parsedEvent.data.conversation_id, {
                                summary: parsedEvent.data.conversation_summary,
                            });
                        }
                    } else if (parsedEvent.event === 'error') {
                        throw new Error(parsedEvent.data);
                    }
                }
            }

            appendMessage(convId, {
                role: 'assistant',
                content: assistantMessage,
                citations: citationsMap,
                timestamp: new Date(),
            });
        } catch (err) {
            console.error('Failed to send message:', err);
            const errorText = err.message && err.message !== 'Failed to fetch' ? `**Error:** ${err.message}` : 'Sorry, there was an error processing your message.';
            appendMessage(convId, { role: 'assistant', content: errorText, timestamp: new Date(), error: true });
        } finally {
            patchStream(convId, { isStreaming: false, status: '', streamingMessage: '', streamingCitations: null });
        }
    };

    const value = {
        conversations,
        selectedConversation,
        loading,
        error,
        createConversation,
        selectConversation,
        deleteConversation,
        updateConversation,
        getMessages,
        getStream,
        sendMessage,
    };

    return (
        <ConversationContext.Provider value={value}>
            {children}
        </ConversationContext.Provider>
    );
}
