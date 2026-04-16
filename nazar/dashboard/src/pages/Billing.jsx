import { useState, useEffect } from 'react';
import {
  CreditCard, Check, Crown, Zap, ArrowUpRight,
  AlertTriangle, Clock, Users, MessageSquare, Send, Brain,
  ExternalLink, FileText, IndianRupee,
} from 'lucide-react';
import { useApi } from '../hooks/useApi';
import { billing as billingApi, payments as paymentsApi } from '../api/client';
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
  const { data: paymentConfig } = useApi(() => paymentsApi.config(), []);
  const [upgrading, setUpgrading] = useState(null);
  const [cancelling, setCancelling] = useState(false);

  const razorpayConfigured = paymentConfig?.configured || false;

  if (plansLoading || subLoading) return <Spinner />;

  const plans = plansData?.plans || [];
  const sub = subData?.subscription || {};
  const usage = usageData || {};
  const currentPlan = sub.plan_id || 'starter';
  const isTrialActive = sub.status === 'trialing';
  const isCancelled = sub.status === 'cancelled' || sub.cancel_at_period_end;

  async function handleUpgrade(planId) {
    if (planId === currentPlan) return;
    setUpgrading(planId);

    try {
      if (razorpayConfigured) {
        // Real payment flow: create Razorpay subscription, open checkout
        const result = await paymentsApi.subscribe(planId);
        if (result.short_url) {
          // Option 1: Redirect to Razorpay hosted page
          window.open(result.short_url, '_blank');
        } else if (result.subscription_id && window.Razorpay) {
          // Option 2: Embedded Razorpay checkout
          const options = {
            key: paymentConfig.key_id,
            subscription_id: result.subscription_id,
            name: 'Nazar',
            description: `${planId.charAt(0).toUpperCase() + planId.slice(1)} Plan`,
            handler: async function (response) {
              // Verify payment on backend
              try {
                await paymentsApi.verify({
                  razorpay_payment_id: response.razorpay_payment_id,
                  razorpay_signature: response.razorpay_signature,
                  razorpay_subscription_id: response.razorpay_subscription_id,
                  plan_id: planId,
                });
                refetchSub();
                refetchUsage();
              } catch (err) {
                alert('Payment verification failed. Please contact support.');
              }
            },
            theme: { color: '#6366f1' },
          };
          const rzp = new window.Razorpay(options);
          rzp.open();
        }
      } else {
        // Fallback: direct upgrade (dev mode / no payment gateway)
        await billingApi.upgrade(planId);
        refetchSub();
        refetchUsage();
      }
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
            {isTrialActive && sub.trial_end ? (
              <>Trial ends: {new Date(sub.trial_end).toLocaleDateString()}</>
            ) : sub.current_period_end ? (
              <>Current period ends: {new Date(sub.current_period_end).toLocaleDateString()}</>
            ) : (
              <>Started: {sub.created_at ? new Date(sub.created_at).toLocaleDateString() : '—'}</>
            )}
          </p>
          {!razorpayConfigured && (
            <p className="billing-dev-notice">
              <AlertTriangle size={12} /> Payment gateway not configured — upgrades are instant (dev mode)
            </p>
          )}
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
            used={usage.usage?.contacts || 0}
            limit={usage.limits?.contacts}
          />
          <UsageMeter
            icon={Brain}
            label="AI Messages (this month)"
            used={usage.usage?.ai_messages || 0}
            limit={usage.limits?.ai_messages_per_month}
          />
          <UsageMeter
            icon={Send}
            label="Campaigns (this month)"
            used={usage.usage?.campaigns || 0}
            limit={usage.limits?.campaigns_per_month}
          />
          <UsageMeter
            icon={Users}
            label="Team Members"
            used={usage.usage?.team_members || 0}
            limit={usage.limits?.team_members}
          />
        </div>
      </div>

      {/* Plans comparison */}
      <div className="billing-section-title">Choose a Plan</div>
      <div className="plans-grid">
        {plans.map(plan => {
          const PlanIcon = PLAN_ICONS[plan.id] || Zap;
          const isCurrent = plan.id === currentPlan;
          const variant = PLAN_COLORS[plan.id] || 'default';

          return (
            <div
              key={plan.id}
              className={`plan-card ${isCurrent ? 'plan-card--current' : ''} ${plan.popular ? 'plan-card--popular' : ''}`}
            >
              {plan.popular && <div className="plan-popular-tag">Most Popular</div>}
              {isCurrent && <div className="plan-current-tag">Current Plan</div>}
              <div className="plan-header">
                <PlanIcon size={20} className={`plan-icon plan-icon--${variant}`} />
                <h3 className="plan-name">{plan.name}</h3>
                <div className="plan-price">
                  {plan.price_inr === 0 ? (
                    <span className="plan-price-amount">Custom</span>
                  ) : (
                    <>
                      <span className="plan-price-currency">₹</span>
                      <span className="plan-price-amount">{plan.price_inr.toLocaleString('en-IN')}</span>
                      <span className="plan-price-period">/mo</span>
                    </>
                  )}
                </div>
                {plan.price_inr > 0 && (
                  <div className="plan-price-gst">+ 18% GST</div>
                )}
              </div>

              <ul className="plan-features">
                {(plan.features || []).map((f, i) => (
                  <li key={i}><Check size={14} /> {f}</li>
                ))}
              </ul>

              <div className="plan-limits">
                <div className="plan-limit-item">
                  <Users size={12} /> {plan.limits?.contacts === -1 ? 'Unlimited' : plan.limits?.contacts?.toLocaleString()} contacts
                </div>
                <div className="plan-limit-item">
                  <Brain size={12} /> {plan.limits?.ai_messages_per_month === -1 ? 'Unlimited' : plan.limits?.ai_messages_per_month?.toLocaleString()} AI msgs/mo
                </div>
                <div className="plan-limit-item">
                  <Send size={12} /> {plan.limits?.campaigns_per_month === -1 ? 'Unlimited' : plan.limits?.campaigns_per_month} campaigns/mo
                </div>
              </div>

              <div className="plan-action">
                {isCurrent ? (
                  <Button variant="secondary" size="sm" disabled>Current Plan</Button>
                ) : plan.id === 'enterprise' ? (
                  <Button variant="secondary" size="sm" onClick={() => window.open('mailto:sales@nazar.app', '_blank')}>
                    Contact Sales
                  </Button>
                ) : (
                  <Button
                    variant={variant === 'success' ? 'success' : 'primary'}
                    size="sm"
                    loading={upgrading === plan.id}
                    onClick={() => handleUpgrade(plan.id)}
                  >
                    {razorpayConfigured ? (
                      <><IndianRupee size={12} /> Subscribe</>
                    ) : (
                      plans.findIndex(p => p.id === plan.id) > plans.findIndex(p => p.id === currentPlan)
                        ? 'Upgrade' : 'Switch'
                    )}
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
