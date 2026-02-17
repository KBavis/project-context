import { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkBreaks from 'remark-breaks';
import { api } from '../services/api';
import Button from './Button';
import './ChatInterface.css';

export default function ChatInterface({ conversationId }) {
    const [messages, setMessages] = useState([]);
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);
    const [streamingMessage, setStreamingMessage] = useState('');
    const messagesEndRef = useRef(null);

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages, streamingMessage]);

    useEffect(() => {
        if (conversationId) {
            loadMessages();
        }
    }, [conversationId]);

    const loadMessages = async () => {
        try {
            const data = await api.messages.list(conversationId);
            setMessages(data);
        } catch (error) {
            console.error('Failed to load messages:', error);
        }
    };

    const handleSend = async () => {
        if (!input.trim() || loading) return;

        const userMessage = { role: 'user', content: input, timestamp: new Date() };
        setMessages(prev => [...prev, userMessage]);
        setInput('');
        setLoading(true);
        setStreamingMessage('');

        try {
            const response = await api.messages.send(conversationId, input);

            // Handle streaming response
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let assistantMessage = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                const chunk = decoder.decode(value);
                assistantMessage += chunk;
                setStreamingMessage(assistantMessage);
            }

            // Add complete message to history
            const completeMessage = {
                role: 'assistant',
                content: assistantMessage,
                timestamp: new Date(),
            };
            setMessages(prev => [...prev, completeMessage]);
            setStreamingMessage('');

        } catch (error) {
            console.error('Failed to send message:', error);
            const errorMessage = {
                role: 'assistant',
                content: 'Sorry, there was an error processing your message.',
                timestamp: new Date(),
                error: true,
            };
            setMessages(prev => [...prev, errorMessage]);
        } finally {
            setLoading(false);
        }
    };

    const handleKeyPress = (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    };

    const isUser = (msg) => {
        // Handle both 'role' (local state) and 'sender' (backend DB)
        const role = msg.role || msg.sender;
        return role && role.toUpperCase() === 'USER';
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
            <div className="chat-messages">
                {messages.map((msg, idx) => (
                    <div key={idx} className={`message ${getRoleClass(msg)}`}>
                        <div className="message-avatar">
                            {isUser(msg) ? '👤' : '🤖'}
                        </div>
                        <div className="message-content">
                            <div className="message-text">
                                <ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks]}>
                                    {msg.content}
                                </ReactMarkdown>
                            </div>
                            <div className="message-timestamp">
                                {(msg.timestamp || msg.created_at) && new Date(msg.timestamp || msg.created_at).toLocaleTimeString()}
                            </div>
                        </div>
                    </div>
                ))}

                {streamingMessage && (
                    <div className="message message-assistant message-streaming">
                        <div className="message-avatar">🤖</div>
                        <div className="message-content">
                            <div className="message-text">
                                <ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks]}>
                                    {streamingMessage}
                                </ReactMarkdown>
                            </div>
                            <div className="message-streaming-indicator">
                                <span className="pulse">●</span> Generating...
                            </div>
                        </div>
                    </div>
                )}

                <div ref={messagesEndRef} />
            </div>

            <div className="chat-input-container">
                <textarea
                    className="chat-input"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyPress={handleKeyPress}
                    placeholder="Type your message... (Shift+Enter for new line)"
                    rows={3}
                    disabled={loading}
                />
                <Button
                    onClick={handleSend}
                    disabled={!input.trim() || loading}
                    loading={loading}
                    icon="→"
                >
                    Send
                </Button>
            </div>
        </div>
    );
}
