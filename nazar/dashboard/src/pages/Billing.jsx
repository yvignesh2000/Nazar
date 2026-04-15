import { useState } from 'react';
import {
  CreditCard, Check, Crown, Zap, ArrowUpRight,
  AlertTriangle, Clock, Users, MessageSquare, Send, Brain,
} from 'lucide-react';
import { useApi } from '../hooks/useApi';
import { billing as billingApi } from '../api/client';
import PageHeader from '../components/ui/PageHeader';
import Badge from '../components/ui/Badge';
import Button from '../components/ui/Button';
import Spinner from '../components/ui/Spinner';
import './Billing.css';

const PLAN_ICONS = {
  starter: Zap,
  growth: ArrowUpRight,
  pro: Crown,
  enterprise: Crown,
};

const PLAN_COLORS = {
  starter: 'default',
  growth: 'success',
  pro: 'warning',
  enterprise: 'orange',
};

export default function Billing() {
  const { data: plansData, loading: plansLoading } = useApi(() => billingApi.plans(), []);
  const { data: subData, loading: subLoading, refetch: refetchSub } = useApi(() => billingApi.subscription(), []);
  const { data: usageData, refetch: refetchUsage } = useApi(() => billingApi.usage(), []);
  const [upgrading, setUpgrading] = useState(null);
  const [cancelling, setCancelling] = useState(false);

  if (plansLoading || subLoading) return <Spinner />;

  const plans = plansData?.plans || [];
  const sub = subData?.subscription || {};
  const usage = usageData || {};
  const currentPlan = sub.plan_id || 'starter';
  const isTrialActive = sub.trial_active;
  const isCancelled = sub.status === 'cancelled' || sub.cancel_at_period_end;

  async function handleUpgrade(planId) {
    if (planId === currentPlan) return;
    setUpgrading(planId);
    try {
      await billingApi.upgrade(planId);
      refetchSub();
      refetchUsage();
    } catch (err) {
      alert('Upgrade failed: ' + (err?.message || 'Unknown error'));
    } finally {
      setUpgrading(null);
    }
  }

  async function handleCancel() {
    if (!confirm('Are you sure you want to cancel? You will retain access until the end of the billing period.')) return;
    setCancelling(true);
    try {
      await billingApi.cancel(true);
      refetchSub();
    } catch (err) {
      alert('Cancel failed: ' + (err?.message || 'Unknown error'));
    } finally {
      setCancelling(false);
    }
  }

  return (
    <div className="page-content">
      <PageHeader
        title="Billing & Plans"
        description="Manage your subscription and monitor usage"
      />

      {/* Current subscription banner */}
      <div className="billing-current">
        <div className="billing-current-info">
          <div className="billing-plan-badge">
            <CreditCard size={18} />
            <span className="billing-plan-name">{currentPlan.charAt(0).toUpperCase() + currentPlan.slice(1)}</span>
            {isTrialActive && <Badge variant="warning">Trial</Badge>}
            {isCancelled && <Badge variant="danger">Cancelling</Badge>}
            {!isTrialActive && !isCancelled && sub.status === 'active' && <Badge variant="success">Active</Badge>}
          </div>
          <p className="billing-period">
            {isTrialActive && sub.trial_ends_at ? (
              <>Trial ends: {new Date(sub.trial_ends_at).toLocaleDateString()}</>
            ) : sub.current_period_end ? (
              <>Current period ends: {new Date(sub.current_period_end).toLocaleDateString()}</>
            ) : (
              <>Started: {sub.created_at ? new Date(sub.created_at).toLocaleDateString() : '—'}</>
            )}
          </p>
        </div>
        {!isCancelled && currentPlan !== 'enterprise' && (
          <Button variant="ghost" size="sm" onClick={handleCancel} loading={cancelling}>
            Cancel Plan
          </Button>
        )}
      </div>

      {/* Usage meters */}
      <div className="billing-usage-section">
        <h2 className="billing-section-title">Current Usage</h2>
        <div className="usage-grid">
          <UsageMeter
            icon={Users}
            label="Contacts"
            used={usage.contacts?.used || 0}
            limit={usage.contacts?.limit}
          />
          <UsageMeter
            icon={MessageSquare}
            label="Messages (this month)"
            used={usage.messages?.used || 0}
            limit={usage.messages?.limit}
          />
          <UsageMeter
            icon={Brain}
            label="AI Generations"
            used={usage.ai_generations?.used || 0}
            limit={usage.ai_generations?.limit}
          />
          <UsageMeter
            icon={Send}
            label="Campaigns"
            used={usage.campaigns?.used || 0}
            limit={usage.campaigns?.limit}
          />
        </div>
      </div>

      {/* Plans comparison */}
      <div className="billing-section-title">Choose a Plan</div>
      <div className="plans-grid">
        {plans.map(plan => {
          const PlanIcon = PLAN_ICONS[plan.plan_id] || Zap;
          const isCurrent = plan.plan_id === currentPlan;
          const variant = PLAN_COLORS[plan.plan_id] || 'default';

          return (
            <div
              key={plan.plan_id}
              className={`plan-card ${isCurrent ? 'plan-card--current' : ''}`}
            >
              {isCurrent && <div className="plan-current-tag">Current Plan</div>}
              <div className="plan-header">
                <PlanIcon size={20} className={`plan-icon plan-icon--${variant}`} />
                <h3 className="plan-name">{plan.name}</h3>
                <div className="plan-price">
                  {plan.price === 0 ? (
                    <span className="plan-price-amount">Free</span>
                  ) : plan.price === -1 ? (
                    <span className="plan-price-amount">Custom</span>
                  ) : (
                    <>
                      <span className="plan-price-amount">${plan.price}</span>
                      <span className="plan-price-period">/mo</span>
                    </>
                  )}
                </div>
              </div>

              <ul className="plan-features">
                {(plan.features || []).map((f, i) => (
                  <li key={i}><Check size={14} /> {f}</li>
                ))}
              </ul>

              <div className="plan-action">
                {isCurrent ? (
                  <Button variant="secondary" size="sm" disabled>Current Plan</Button>
                ) : plan.plan_id === 'enterprise' ? (
                  <Button variant="secondary" size="sm" onClick={() => window.open('mailto:sales@nazar.app', '_blank')}>
                    Contact Sales
                  </Button>
                ) : (
                  <Button
                    variant={variant === 'success' ? 'success' : 'primary'}
                    size="sm"
                    loading={upgrading === plan.plan_id}
                    onClick={() => handleUpgrade(plan.plan_id)}
                  >
                    {plans.findIndex(p => p.plan_id === plan.plan_id) > plans.findIndex(p => p.plan_id === currentPlan)
                      ? 'Upgrade' : 'Switch'}
                  </Button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function UsageMeter({ icon: Icon, label, used, limit }) {
  const isUnlimited = !limit || limit < 0;
  const pct = isUnlimited ? 0 : Math.min(100, (used / limit) * 100);
  const isHigh = pct > 80;
  const isFull = pct >= 100;

  return (
    <div className="usage-meter">
      <div className="usage-meter-header">
        <Icon size={16} />
        <span className="usage-meter-label">{label}</span>
      </div>
      <div className="usage-meter-bar-track">
        <div
          className={`usage-meter-bar-fill ${isHigh ? 'usage-meter-bar-fill--high' : ''} ${isFull ? 'usage-meter-bar-fill--full' : ''}`}
          style={{ width: isUnlimited ? '0%' : `${pct}%` }}
        />
      </div>
      <div className="usage-meter-values">
        <span>{used.toLocaleString()}</span>
        <span>{isUnlimited ? 'Unlimited' : limit.toLocaleString()}</span>
      </div>
    </div>
  );
}
