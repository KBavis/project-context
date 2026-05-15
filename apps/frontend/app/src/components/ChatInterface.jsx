import { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkBreaks from 'remark-breaks';
import { api } from '../services/api';
import { useConversations } from '../contexts/ConversationContext';
import Button from './Button';
import '../styles/ChatInterface.css';

export default function ChatInterface({ conversationId }) {
    const { messages, setMessages } = useConversations();
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);
    const [streamingMessage, setStreamingMessage] = useState('');
    const [status, setStatus] = useState('');
    const messagesEndRef = useRef(null);
    const inputRef = useRef(null);

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    };

    const focusInput = () => {
        inputRef.current?.focus();
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages, streamingMessage]);

    const handleSend = async () => {
        if (!input.trim() || loading) return;

        const userMessage = { role: 'user', content: input, timestamp: new Date() };
        setMessages(prev => [...prev, userMessage]);
        setInput('');
        setLoading(true);
        setStreamingMessage('');

        try {
            const response = await api.messages.send(conversationId, input);

            if (!response.body) {
                throw new Error('No response body');
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let assistantMessage = '';
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });

                // Process buffer for SSE lines
                const lines = buffer.split('\n');
                // Keep the last partial line in the buffer
                buffer = lines.pop() || '';

                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;

                    let parsedEvent;
                    try {
                        const jsonStr = line.replace('data: ', '');
                        parsedEvent = JSON.parse(jsonStr);
                    } catch (e) {
                        console.error('Failed to parse SSE event:', e, line);
                        continue;
                    }

                    if (parsedEvent.event === 'status') {
                        setStatus(parsedEvent.data);
                    } else if (parsedEvent.event === 'chunk') {
                        assistantMessage += parsedEvent.data;
                        setStreamingMessage(assistantMessage);
                        setStatus('Generating...'); // Reset to "Generating" when we get actual tokens
                    } else if (parsedEvent.event === 'metadata') {
                        // Final data (token counts, etc)
                        console.log('Stream Metadata:', parsedEvent.data);
                    } else if (parsedEvent.event === 'error') {
                        throw new Error(parsedEvent.data);
                    }
                }
            }

            const completeMessage = {
                role: 'assistant',
                content: assistantMessage,
                timestamp: new Date(),
            };
            setMessages(prev => [...prev, completeMessage]);
            setStreamingMessage('');
            setStatus('');

        } catch (error) {
            console.error('Failed to send message:', error);

            // Extract the specific error message if it came from our SSE stream
            const errorText = error.message && error.message !== 'Failed to fetch'
                ? `**Error:** ${error.message}`
                : 'Sorry, there was an error processing your message.';

            const errorMessage = {
                role: 'assistant',
                content: errorText,
                timestamp: new Date(),
                error: true,
            };
            setMessages(prev => [...prev, errorMessage]);
        } finally {
            setLoading(false);
            setStatus('');
        }
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

                {(loading || streamingMessage) && (
                    <div className="message message-assistant message-streaming">
                        <div className="message-avatar">🤖</div>
                        <div className="message-content">
                            <div className="message-text">
                                {streamingMessage ? (
                                    <ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks]}>
                                        {streamingMessage}
                                    </ReactMarkdown>
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
                        placeholder="Type your message..."
                        rows={1}
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
        </div>
    );
}
