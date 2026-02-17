import '../styles/Input.css';

export default function Input({
    label,
    id,
    type = 'text',
    value,
    onChange,
    placeholder,
    error,
    disabled = false,
    required = false,
    multiline = false,
    rows = 3,
}) {
    const inputId = id || `input-${Math.random().toString(36).substr(2, 9)}`;

    const baseProps = {
        id: inputId,
        value,
        onChange: (e) => onChange(e.target.value),
        placeholder,
        disabled,
        required,
        className: `input ${error ? 'input-error' : ''}`,
    };

    return (
        <div className="input-wrapper">
            {label && (
                <label htmlFor={inputId} className="input-label">
                    {label}
                    {required && <span className="input-required">*</span>}
                </label>
            )}

            {multiline ? (
                <textarea {...baseProps} rows={rows} />
            ) : (
                <input {...baseProps} type={type} />
            )}

            {error && (
                <span className="input-error-message">{error}</span>
            )}
        </div>
    );
}
