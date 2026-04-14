import clsx from 'clsx';
import './Badge.css';

const VARIANTS = {
  default: 'badge--default',
  primary: 'badge--primary',
  success: 'badge--success',
  warning: 'badge--warning',
  danger:  'badge--danger',
  orange:  'badge--orange',
  gray:    'badge--gray',
};

export default function Badge({ children, variant = 'default', dot = false, size = 'sm' }) {
  return (
    <span className={clsx('badge', VARIANTS[variant], `badge--${size}`)}>
      {dot && <span className="badge-dot" />}
      {children}
    </span>
  );
}
