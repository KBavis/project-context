import './Button.css';

export default function Button({
    children,
    variant = 'primary',
    size = 'md',
    onClick,
    disabled = false,
    type = 'button',
    icon = null,
    fullWidth = false,
    loading = false,
}) {
    const classes = [
        'btn',
        `btn-${variant}`,
        `btn-${size}`,
        fullWidth && 'btn-full-width',
        loading && 'btn-loading',
    ].filter(Boolean).join(' ');

    return (
        <button
            type={type}
            className={classes}
            onClick={onClick}
            disabled={disabled || loading}
        >
            {loading && (
                <span className="btn-spinner spin"></span>
            )}
            {icon && !loading && (
                <span className="btn-icon">{icon}</span>
            )}
            <span className="btn-content">{children}</span>
        </button>
    );
}
