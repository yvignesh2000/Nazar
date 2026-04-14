import clsx from 'clsx';
import './Button.css';

export default function Button({
  children, variant = 'primary', size = 'md', icon: Icon,
  loading = false, disabled = false, className, ...props
}) {
  return (
    <button
      className={clsx('btn', `btn--${variant}`, `btn--${size}`, loading && 'btn--loading', className)}
      disabled={disabled || loading}
      {...props}
    >
      {loading ? (
        <span className="btn-spinner" />
      ) : Icon ? (
        <Icon size={size === 'sm' ? 14 : 16} />
      ) : null}
      {children && <span>{children}</span>}
    </button>
  );
}
