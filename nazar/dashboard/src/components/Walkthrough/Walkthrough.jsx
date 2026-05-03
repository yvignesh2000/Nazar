/**
 * Interactive Product Tour
 * ------------------------
 * A self-guided tour the prospect drives themselves. Each "mission" is a
 * value-led card with one concrete action. We auto-detect when the action
 * happens and unlock the next mission. A "Show me" helper performs the
 * action for them as a fallback.
 *
 * Launch:
 *   - Floating "Start tour" button (bottom-right) when not running
 *   - URL param ?tour=1
 *   - Keyboard: T to start; Esc to exit; Arrow keys to navigate
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  ArrowRight, Check, ChevronLeft, Lightbulb, Pause, Play, Sparkles, X,
} from 'lucide-react';
import { CHAPTERS, STEPS } from './walkthroughSteps';
import './Walkthrough.css';

const STORAGE_KEY = 'nazar.tour.completed';

export default function Walkthrough() {
  const [active, setActive] = useState(false);
  const [paused, setPaused] = useState(false);
  const [stepIdx, setStepIdx] = useState(0);
  const [verified, setVerified] = useState(false);
  const [ringRect, setRingRect] = useState(null);

  const navigate = useNavigate();
  const location = useLocation();
  const verifyTimerRef = useRef(null);
  const ringTimerRef = useRef(null);

  const step = STEPS[stepIdx];
  const total = STEPS.length;
  const chapter = CHAPTERS.find(c => c.id === step?.chapter);
  const isFirst = stepIdx === 0;
  const isLast = stepIdx === total - 1;
  const tourCompleted = typeof window !== 'undefined' && localStorage.getItem(STORAGE_KEY) === '1';

  /* ── Auto-launch via ?tour=1 ──────────────────────────── */
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    if (params.get('tour') === '1') {
      start();
      params.delete('tour');
      const s = params.toString();
      navigate({ pathname: location.pathname, search: s ? `?${s}` : '' }, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* ── Keyboard ─────────────────────────────────────────── */
  useEffect(() => {
    function onKey(e) {
      const tag = (e.target.tagName || '').toLowerCase();
      const typing = tag === 'input' || tag === 'textarea' || e.target.isContentEditable;
      if (!active) {
        if (!typing && (e.key === 't' || e.key === 'T')) start();
        return;
      }
      if (e.key === 'Escape') { end(); return; }
      if (typing) return;
      if (e.key === 'ArrowRight') next();
      else if (e.key === 'ArrowLeft') prev();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, stepIdx]);

  /* ── Pre-navigate when a step requires a route ────────── */
  useEffect(() => {
    if (!active || !step) return;
    if (step.route && !location.pathname.startsWith(step.route)) {
      navigate(step.route);
    }
    setVerified(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, stepIdx]);

  /* ── Poll verifier ────────────────────────────────────── */
  useEffect(() => {
    clearInterval(verifyTimerRef.current);
    if (!active || paused || !step?.verify) {
      setVerified(false);
      return;
    }
    const tick = () => {
      try {
        if (step.verify()) {
          setVerified(true);
          clearInterval(verifyTimerRef.current);
        }
      } catch { /* ignore */ }
    };
    tick();
    verifyTimerRef.current = setInterval(tick, 500);
    return () => clearInterval(verifyTimerRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, paused, stepIdx]);

  /* ── Spotlight ring ───────────────────────────────────── */
  useEffect(() => {
    clearInterval(ringTimerRef.current);
    if (!active || paused || !step?.selector) {
      setRingRect(null);
      return;
    }
    const measure = () => {
      const el = document.querySelector(step.selector);
      if (!el) { setRingRect(null); return; }
      const r = el.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) { setRingRect(null); return; }
      const pad = 6;
      setRingRect({
        top: r.top - pad,
        left: r.left - pad,
        width: r.width + pad * 2,
        height: r.height + pad * 2,
      });
    };
    measure();
    ringTimerRef.current = setInterval(measure, 350);
    window.addEventListener('resize', measure);
    window.addEventListener('scroll', measure, true);
    return () => {
      clearInterval(ringTimerRef.current);
      window.removeEventListener('resize', measure);
      window.removeEventListener('scroll', measure, true);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, paused, stepIdx]);

  /* ── Controls ─────────────────────────────────────────── */
  const start = useCallback(() => {
    setStepIdx(0);
    setPaused(false);
    setActive(true);
  }, []);

  const end = useCallback(() => {
    setActive(false);
    setPaused(false);
    setVerified(false);
    clearInterval(verifyTimerRef.current);
    clearInterval(ringTimerRef.current);
    try { localStorage.setItem(STORAGE_KEY, '1'); } catch { /* ignore */ }
  }, []);

  const next = useCallback(() => {
    setStepIdx(i => Math.min(i + 1, total - 1));
  }, [total]);

  const prev = useCallback(() => {
    setStepIdx(i => Math.max(i - 1, 0));
  }, []);

  const runShowMe = useCallback(() => {
    if (!step?.action?.run) return;
    try { step.action.run(); } catch { /* ignore */ }
  }, [step]);

  /* ── Closed: floating launcher ────────────────────────── */
  if (!active) {
    // Hide the floating launcher on routes where it would overlap a
    // primary bottom-right action (e.g. the Send button inside the
    // conversation composer). The user can still trigger the tour with
    // the keyboard shortcut "T" or via ?tour=1.
    const path = location.pathname || '';
    const hideLauncher =
      /^\/(inbox|conversations)\/[^/]+/.test(path);
    if (hideLauncher) return null;

    return (
      <button
        className={`tour-launcher ${tourCompleted ? 'tour-launcher--seen' : 'tour-launcher--new'}`}
        onClick={start}
        title="Take an interactive tour (press T)"
      >
        <Sparkles size={14} />
        <span>{tourCompleted ? 'Restart tour' : 'Take a 3-min tour'}</span>
      </button>
    );
  }

  /* ── Paused: small chip ───────────────────────────────── */
  if (paused) {
    return (
      <>
        {ringRect && <div className="tour-ring" style={ringRect} />}
        <button
          className="tour-paused-chip"
          onClick={() => setPaused(false)}
          title="Resume tour"
        >
          <Play size={12} />
          <span>Resume tour ({stepIdx + 1}/{total})</span>
        </button>
      </>
    );
  }

  /* ── Active: full rail ────────────────────────────────── */
  const progressPct = Math.round(((stepIdx + (verified ? 1 : 0)) / total) * 100);

  return (
    <>
      {ringRect && <div className="tour-ring" style={ringRect} />}

      <aside className="tour-rail" role="dialog" aria-label="Product tour">
        {/* ── Top: chapter pill + close ───────────────────── */}
        <div className="tour-top">
          <div className="tour-top-left">
            <span className="tour-chapter">{chapter?.name}</span>
            <span className="tour-step-num">Mission {stepIdx + 1} of {total}</span>
          </div>
          <div className="tour-top-right">
            <button
              className="tour-icon-btn"
              onClick={() => setPaused(true)}
              title="Pause tour"
            >
              <Pause size={13} />
            </button>
            <button
              className="tour-icon-btn"
              onClick={end}
              title="Exit tour (Esc)"
            >
              <X size={13} />
            </button>
          </div>
        </div>

        {/* ── Progress bar ─────────────────────────────────── */}
        <div className="tour-progress">
          <div className="tour-progress-fill" style={{ width: `${progressPct}%` }} />
        </div>

        {/* ── Body ─────────────────────────────────────────── */}
        <div className="tour-body">
          <h2 className="tour-title">{step.title}</h2>

          {step.value && (
            <p className="tour-value">{step.value}</p>
          )}

          {step.mission && (
            <div className="tour-mission">
              <div className="tour-mission-label">
                {verified ? <Check size={12} /> : <ArrowRight size={12} />}
                <span>{verified ? 'Done' : 'Try it'}</span>
              </div>
              <p className="tour-mission-text">{step.mission}</p>
              {step.hint && !verified && (
                <div className="tour-hint">
                  <Lightbulb size={12} />
                  <span>{step.hint}</span>
                </div>
              )}
            </div>
          )}

          {verified && step.completion && (
            <div className="tour-completion">
              <Check size={14} />
              <span>{step.completion}</span>
            </div>
          )}

          {step.cta && (
            <a
              className="tour-cta-link"
              href={step.cta.href}
              target={step.cta.href?.startsWith('http') ? '_blank' : undefined}
              rel="noreferrer"
            >
              {step.cta.label}
              <ArrowRight size={14} />
            </a>
          )}
        </div>

        {/* ── Footer controls ─────────────────────────────── */}
        <div className="tour-foot">
          <button
            className="tour-btn tour-btn--ghost"
            onClick={prev}
            disabled={isFirst}
            title="Back"
          >
            <ChevronLeft size={14} />
            Back
          </button>

          <div className="tour-foot-spacer" />

          {step.action && !verified && (
            <button
              className="tour-btn tour-btn--secondary"
              onClick={runShowMe}
              title="Auto-perform this action"
            >
              {step.action.label || 'Show me'}
            </button>
          )}

          {isLast ? (
            <button className="tour-btn tour-btn--primary" onClick={end}>
              Finish tour
              <Check size={14} />
            </button>
          ) : isFirst ? (
            <button className="tour-btn tour-btn--primary" onClick={next}>
              Start tour
              <ArrowRight size={14} />
            </button>
          ) : (
            <button
              className={`tour-btn tour-btn--primary ${verified ? 'tour-btn--verified' : ''}`}
              onClick={next}
              title="Next mission"
            >
              {verified ? 'Next mission' : 'Skip'}
              <ArrowRight size={14} />
            </button>
          )}
        </div>
      </aside>
    </>
  );
}
