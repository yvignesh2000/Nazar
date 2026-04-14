import './StatCard.css';

export default function StatCard({ icon: Icon, label, value, sub, variant = 'default' }) {
  return (
    <div className={`stat-card stat-card--${variant}`}>
      {Icon && (
        <div className="stat-card-icon">
          <Icon size={20} />
        </div>
      )}
      <div className="stat-card-body">
        <span className="stat-card-value">{value}</span>
        <span className="stat-card-label">{label}</span>
        {sub && <span className="stat-card-sub">{sub}</span>}
      </div>
    </div>
  );
}
