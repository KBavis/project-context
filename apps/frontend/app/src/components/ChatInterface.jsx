import { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkBreaks from 'remark-breaks';
import { useConversations } from '../contexts/ConversationContext';
import { useProjects } from '../contexts/ProjectContext';
import { useAlert } from '../contexts/AlertContext';
import Button from './Button';
import '../styles/ChatInterface.css';

// Allow the private `cite:` scheme through react-markdown's URL sanitizer while still
// blocking genuinely unsafe protocols (javascript:, data:, etc.).
const safeUrlTransform = (url) => {
    if (!url) return url;
    if (url.startsWith('cite:')) return url;
    if (/^(https?:|mailto:|tel:|#|\/)/i.test(url)) return url;
    return '';
};

// Pull the embedded citation map (persisted as a stripped HTML comment) out of stored
// content so citations still render on reload. Returns the cleaned body + parsed map.
const extractEmbeddedCitations = (rawContent) => {
    const text = rawContent || '';
    const match = text.match(/\n*<!--CITATIONS:([\s\S]*?)-->\s*$/);
    if (!match) return { body: text, embeddedMap: null };
    let embeddedMap = null;
    try {
        embeddedMap = JSON.parse(match[1]);
    } catch {
        embeddedMap = null;
    }
    return { body: text.slice(0, match.index).trimEnd(), embeddedMap };
};

// Renders an assistant/user message: markdown body with de-emphasized inline citations
// (cite:<id> links) plus an auto-generated, grouped Citations footer built from the
// markers the answer actually placed.
function MessageContent({ content, citations }) {
    const { body, embeddedMap } = extractEmbeddedCitations(content);
    const citationMap = citations || embeddedMap || {};

    // Collect the citation ids the answer actually referenced, in first-seen order.
    const usedIds = [];
    const seen = new Set();
    const re = /\(cite:(\w+)\)/g;
    let m;
    while ((m = re.exec(body)) !== null) {
        if (!seen.has(m[1]) && citationMap[m[1]]) {
            seen.add(m[1]);
            usedIds.push(m[1]);
        }
    }

    const components = {
        a: ({ href, children, ...props }) => {
            if (href && href.startsWith('cite:')) {
                const c = citationMap[href.slice(5)];
                if (c) {
                    // Show a deterministic, precise label (file:line-range) from the citation
                    // map rather than whatever text the model wrote, so line numbers always show.
                    const shortLabel = c.label && c.label.includes('/')
                        ? c.label.split('/').pop()
                        : c.label;
                    return (
                        <a
                            href={c.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="citation-link"
                            title={c.label}
                        >
                            {shortLabel || children}
                        </a>
                    );
                }
                // Unknown/dropped citation id — show the label as plain de-emphasized text.
                return <span className="citation-link citation-link-missing">{children}</span>;
            }
            return (
                <a href={href} target="_blank" rel="noopener noreferrer" {...props}>
                    {children}
                </a>
            );
        },
    };

    // Group referenced citations by their data source for the footer, keeping each
    // unique source (by resolved URL) only once — distinct findings can point to the
    // same file+lines, which would otherwise duplicate footer entries.
    const groups = {};
    const seenUrls = new Set();
    usedIds.forEach((id) => {
        const c = citationMap[id];
        if (seenUrls.has(c.url)) return;
        seenUrls.add(c.url);
        const key = c.data_source_name || 'Sources';
        if (!groups[key]) groups[key] = { url: c.data_source_url, items: [] };
        groups[key].items.push({ id, ...c });
    });

    return (
        <>
            <ReactMarkdown
                remarkPlugins={[remarkGfm, remarkBreaks]}
                urlTransform={safeUrlTransform}
                components={components}
            >
                {body}
            </ReactMarkdown>

            {usedIds.length > 0 && (
                <div className="citations-section">
                    <div className="citations-heading">Citations</div>
                    {Object.entries(groups).map(([name, group]) => (
                        <div key={name} className="citation-group">
                            <div className="citation-group-title">
                                📂{' '}
                                {group.url ? (
                                    <a href={group.url} target="_blank" rel="noopener noreferrer">{name}</a>
                                ) : (
                                    <span>{name}</span>
                                )}
                            </div>
                            <ul className="citation-list">
                                {group.items.map((item) => (
                                    <li key={item.id}>
                                        <a
                                            href={item.url}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            className="citation-link"
                                        >
                                            {item.label}
                                        </a>
                                    </li>
                                ))}
                            </ul>
                        </div>
                    ))}
                </div>
            )}
        </>
    );
}

export default function ChatInterface({ conversationId }) {
    const { getMessages, getStream, sendMessage } = useConversations();
    const { selectedProject, syncingProjects } = useProjects();
    const [input, setInput] = useState('');
    const { showAlert } = useAlert();
    const [lastAlertedConvId, setLastAlertedConvId] = useState(null);

    const syncState = selectedProject ? syncingProjects[selectedProject.id] : null;
    const isSyncing = syncState?.isSyncing;
    const syncError = syncState?.error;
    
    const notReady = !!syncState && syncState.is_ready === false;
    const syncStatus = syncState ? (syncState.overall_status || syncState.status) : null;
    
    const blockMessage = (() => {
        if (!notReady) return null;
        const reasons = (syncState.reasons || []).join(' ').trim();
        const suffix = reasons ? ` (${reasons})` : '';
        if (isSyncing || syncStatus === 'in_progress') return `Project is syncing - please wait until it finishes before chatting.${suffix}`;
        if (syncStatus === 'failed') return `Project sync failed - re-sync it from the Data Sources tab before chatting.${suffix}`;
        if (syncStatus === 'not_yet_synced') return `This project hasn't been synced yet - sync it from the Data Sources tab.${suffix}`;
        return `This project isn't ready to chat yet - sync it from the Data Sources tab.${suffix}`;
    })();

    // Per-conversation view state (lives in context so it survives navigation)
    const messages = getMessages(conversationId);
    const { isStreaming, status, streamingMessage, streamingCitations } = getStream(conversationId);

    const messagesEndRef = useRef(null);
    const messagesContainerRef = useRef(null);
    const shouldAutoScrollRef = useRef(true);
    const inputRef = useRef(null);

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    };

    // Track whether the user is pinned to the bottom. If they scroll up to read,
    // stop auto-scrolling so streaming output doesn't yank them back down.
    const handleMessagesScroll = () => {
        const el = messagesContainerRef.current;
        if (!el) return;
        const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
        shouldAutoScrollRef.current = distanceFromBottom <= 80;
    };

    const focusInput = () => {
        inputRef.current?.focus();
    };

    // Reset to "pinned" when switching conversations so a fresh chat lands at the bottom.
    useEffect(() => {
        shouldAutoScrollRef.current = true;
    }, [conversationId]);

    useEffect(() => {
        if (shouldAutoScrollRef.current) scrollToBottom();
    }, [messages, streamingMessage]);

    useEffect(() => {
        if (conversationId && notReady && conversationId !== lastAlertedConvId) {
            setLastAlertedConvId(conversationId);
            showAlert(blockMessage, syncStatus === 'failed' ? 'error' : 'warning');
        }
    }, [conversationId, notReady, blockMessage, syncStatus, showAlert, lastAlertedConvId]);

    // Auto-resize textarea as user types
    useEffect(() => {
        const textarea = inputRef.current;
        if (textarea) {
            textarea.style.height = 'auto';
            textarea.style.height = `${textarea.scrollHeight}px`;
        }
    }, [input]);

    const handleSend = async () => {
        if (!input.trim() || isStreaming) return;
        if (notReady) {
            showAlert(blockMessage, syncStatus === 'failed' ? 'error' : 'warning');
            return;
        }

        const content = input;
        setInput('');
        sendMessage(conversationId, content);
    };

    const handleKeyPress = (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    };

    const isUser = (msg) => {
        const role = msg.role || msg.sender;
        return role && role.toUpperCase() === 'USER';
    };

    const getSyncPlaceholder = () => {
        if (!notReady) return "Type your message...";
        if (isSyncing || syncStatus === 'in_progress') return "Project is syncing - please wait...";
        if (syncStatus === 'failed') return "Project sync failed - re-sync in Data Sources to chat";
        if (syncStatus === 'not_yet_synced') return "Project not synced - sync it in Data Sources to chat";
        return "Project not ready - sync it in Data Sources to chat";
    };

    const getRoleClass = (msg) => {
        return isUser(msg) ? 'message-user' : 'message-assistant';
    };

    if (!conversationId) {
        return (
            <div className="chat-empty">
                <div className="chat-empty-icon">💬</div>
                <h3>No Conversation Selected</h3>
                <p>Create a new conversation to get started</p>
            </div>
        );
    }

    return (
        <div className="chat-container">
            <div className="chat-messages" ref={messagesContainerRef} onScroll={handleMessagesScroll}>
                {messages.map((msg, idx) => (
                    <div key={idx} className={`message ${getRoleClass(msg)}`}>
                        <div className="message-avatar">
                            {isUser(msg) ? '👤' : '🤖'}
                        </div>
                        <div className="message-content">
                            <div className="message-text">
                                <MessageContent content={msg.content} citations={msg.citations} />
                            </div>
                            <div className="message-timestamp">
                                {(msg.timestamp || msg.created_at) && new Date(msg.timestamp || msg.created_at).toLocaleTimeString()}
                            </div>
                        </div>
                    </div>
                ))}

                {(isStreaming || streamingMessage) && (
                    <div className="message message-assistant message-streaming">
                        <div className="message-avatar">🤖</div>
                        <div className="message-content">
                            <div className="message-text">
                                {streamingMessage ? (
                                    <MessageContent content={streamingMessage} citations={streamingCitations} />
                                ) : (
                                    <div className="typing-dots">
                                        <span></span><span></span><span></span>
                                    </div>
                                )}
                            </div>
                            <div className="message-streaming-indicator">
                                <span className="pulse"></span> {status || 'Thinking...'}
                            </div>
                        </div>
                    </div>
                )}

                <div ref={messagesEndRef} />
            </div>

            <div className="chat-input-wrapper" onClick={focusInput}>
                <div className="chat-input-container">
                    <textarea
                        ref={inputRef}
                        className="chat-input"
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={handleKeyPress}
                        placeholder={getSyncPlaceholder()}
                        rows={1}
                        disabled={isStreaming || isSyncing}
                    />
                    <Button
                        onClick={handleSend}
                        disabled={!input.trim() || isStreaming || notReady}
                        loading={isStreaming}
                        icon={notReady ? undefined : "→"}
                    >
                        Send
                    </Button>
                </div>
                {blockMessage && (
                    <div 
                        className="sync-error-banner" 
                        style={{ 
                            marginTop: '8px', 
                            fontSize: '12px', 
                            color: syncStatus === 'failed' ? 'var(--color-danger, #e5484d)' : 'var(--color-warning, #f0ad4e)'
                        }}
                    >
                        {blockMessage}
                    </div>
                )}
            </div>
        </div>
    );
}
