import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Zap, CheckCircle2, Circle, SkipForward, ArrowRight,
  Building2, Brain, BookOpen, Wifi, Users, MessageSquare,
  UserPlus, Rocket, ChevronRight, AlertTriangle,
} from 'lucide-react';
import { useApi } from '../hooks/useApi';
import { onboarding as onboardingApi } from '../api/client';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import './Onboarding.css';

const STEP_ICONS = {
  account_created: Building2,
  business_info: Building2,
  knowledge_base: BookOpen,
  whatsapp_connect: Wifi,
  llm_configured: Brain,
  first_contact: Users,
  first_message: MessageSquare,
  team_invited: UserPlus,
};

const STEP_LINKS = {
  business_info: '/settings',
  knowledge_base: '/knowledge',
  whatsapp_connect: '/settings',
  llm_configured: '/settings',
  first_contact: '/contacts',
  first_message: '/conversations',
  team_invited: '/team',
};

const STEP_DESCRIPTIONS = {
  account_created: 'Your workspace and admin account are set up.',
  business_info: 'Add your business name and configure the bot persona.',
  knowledge_base: 'Add product/service info so the AI knows your business.',
  whatsapp_connect: 'Connect your WhatsApp Business number (or skip for demo).',
  llm_configured: 'Add at least one AI provider API key.',
  first_contact: 'Import or add your first customer contact.',
  first_message: 'Send a test or simulated message to verify the pipeline.',
  team_invited: 'Invite a team member or skip for now.',
};

export default function Onboarding() {
  const navigate = useNavigate();
  const { data, loading, refetch } = useApi(() => onboardingApi.get(), []);
  const { data: readiness } = useApi(() => onboardingApi.readiness(), []);
  const [acting, setActing] = useState(null);

  if (loading) return (
    <div className="onboarding-loading">
      <Zap size={32} className="onboarding-pulse" />
      <p>Loading setup wizard...</p>
    </div>
  );

  const state = data || {};
  // Normalise API response: backend returns steps_list[] with {id, done, skipped, title}
  // Map to a flat array with consistent shape for the UI
  const steps = (state.steps_list || []).map(s => ({
    step_id: s.id ?? s.step_id,
    name: s.title ?? s.name ?? s.step_id,
    status: s.done ? 'done' : s.skipped ? 'skipped' : 'pending',
    skippable: s.skippable,
    description: s.description,
  }));
  const progress = state.progress_pct || 0;
  const isComplete = state.is_complete ?? state.completed;
  const checks = readiness?.checks || [];

  async function handleDone(stepId) {
    setActing(stepId);
    try {
      await onboardingApi.markDone(stepId);
      refetch();
    } catch (err) {
      alert(err?.message || 'Failed');
    } finally {
      setActing(null);
    }
  }

  async function handleSkip(stepId) {
    setActing(stepId);
    try {
      await onboardingApi.skip(stepId);
      refetch();
    } catch (err) {
      alert(err?.message || 'Failed');
    } finally {
      setActing(null);
    }
  }

  return (
    <div className="page-content onboarding-page">
      {/* Header */}
      <div className="onboarding-header">
        <div>
          <h1 className="onboarding-title">
            <Zap size={24} /> Setup Wizard
          </h1>
          <p className="onboarding-subtitle">
            {isComplete
              ? 'All set! Your workspace is ready to go.'
              : 'Complete these steps to start selling with Nazar.'}
          </p>
        </div>
        {isComplete && (
          <Button icon={Rocket} onClick={() => navigate('/')}>Go to Dashboard</Button>
        )}
      </div>

      {/* Progress bar */}
      <div className="onboarding-progress-wrap">
        <div className="onboarding-progress-bar">
          <div className="onboarding-progress-fill" style={{ width: `${progress}%` }} />
        </div>
        <span className="onboarding-progress-text">{progress}% complete</span>
      </div>

      {/* Steps */}
      <div className="onboarding-steps">
        {steps.map((step, index) => {
          const Icon = STEP_ICONS[step.step_id] || Circle;
          const isDone = step.status === 'done';
          const isSkipped = step.status === 'skipped';
          const isPending = step.status === 'pending';
          const isNext = isPending && index === steps.findIndex(s => s.status === 'pending');

          return (
            <div
              key={step.step_id}
              className={`onboarding-step ${isDone ? 'onboarding-step--done' : ''} ${isSkipped ? 'onboarding-step--skipped' : ''} ${isNext ? 'onboarding-step--next' : ''}`}
            >
              <div className="onboarding-step-icon">
                {isDone ? (
                  <CheckCircle2 size={20} />
                ) : isSkipped ? (
                  <SkipForward size={20} />
                ) : (
                  <span className="onboarding-step-num">{index + 1}</span>
                )}
              </div>

              <div className="onboarding-step-content">
                <div className="onboarding-step-header">
                  <span className="onboarding-step-name">{step.name || step.step_id}</span>
                  {isDone && <Badge variant="success" size="sm">Done</Badge>}
                  {isSkipped && <Badge variant="gray" size="sm">Skipped</Badge>}
                </div>
                <p className="onboarding-step-desc">
                  {STEP_DESCRIPTIONS[step.step_id] || step.description || ''}
                </p>
              </div>

              <div className="onboarding-step-actions">
                {isPending && (
                  <>
                    {STEP_LINKS[step.step_id] && (
                      <Button
                        size="sm"
                        icon={ArrowRight}
                        onClick={() => navigate(STEP_LINKS[step.step_id])}
                      >
                        Go
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="secondary"
                      loading={acting === step.step_id}
                      onClick={() => handleDone(step.step_id)}
                    >
                      Mark Done
                    </Button>
                    {step.skippable !== false && (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => handleSkip(step.step_id)}
                      >
                        Skip
                      </Button>
                    )}
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Readiness checklist */}
      {checks.length > 0 && (
        <div className="onboarding-readiness">
          <h2 className="onboarding-readiness-title">Readiness Checklist</h2>
          <div className="onboarding-checks">
            {checks.map((c, i) => (
              <div key={i} className={`onboarding-check ${c.passed ? 'onboarding-check--pass' : 'onboarding-check--fail'}`}>
                {c.passed ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
                <span>{c.label || c.check}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
