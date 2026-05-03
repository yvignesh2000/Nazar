/**
 * Interactive Product Tour — self-guided.
 *
 * The user (a prospective customer) drives this themselves. Each "mission"
 * has a value headline, a one-sentence reason it matters, a single concrete
 * action to perform, and an optional "Show me" auto-action so they're never
 * stuck. Verifiers detect when the action actually happened and unlock
 * the next mission.
 *
 * Schema:
 *   chapter:     short uppercase label (groups missions in the progress bar)
 *   title:       big value-driven headline
 *   value:       one-line ROI-driven "why this matters" (always present)
 *   mission:     direct, second-person instruction ("You" / "Try")
 *   hint:        optional: a sub-hint shown when the user gets stuck
 *   route:       optional: pathname to pre-navigate to
 *   selector:    optional: CSS selector to highlight with the spotlight ring
 *   verify:      optional: () => boolean — auto-completes the mission
 *   action:      optional: { type, label, run() } — "Show me" auto-helper
 *   completion:  optional: success-state copy shown when verify passes
 *   cta:         optional: { label, href } — used on the final mission only
 */

/* ── Helpers ──────────────────────────────────────────────── */
const $   = (sel) => document.querySelector(sel);
const $$  = (sel) => Array.from(document.querySelectorAll(sel));
const exists = (sel) => () => !!$(sel);
const onPath = (path) => () => window.location.pathname === path ||
                               window.location.pathname.startsWith(path + '/');
const countMessages = () => $$('.chat-messages .message-bubble, .chat-messages [class*="message"]').length;

/* Click first element matching a selector (used by "Show me" actions). */
const click = (sel) => {
  const el = $(sel);
  if (el) el.click();
  return !!el;
};

/* Type into an input/textarea and dispatch the event so React updates state. */
const setInputValue = (sel, value) => {
  const el = $(sel);
  if (!el) return false;
  const proto = el.tagName === 'TEXTAREA'
    ? window.HTMLTextAreaElement.prototype
    : window.HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
  setter.call(el, value);
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.focus();
  return true;
};

/* ── Chapters ─────────────────────────────────────────────── */
export const CHAPTERS = [
  { id: 'welcome',  name: 'Welcome' },
  { id: 'inbox',    name: 'Inbox' },
  { id: 'live',     name: 'Live AI' },
  { id: 'teach',    name: 'Teach the AI' },
  { id: 'human',    name: 'Human handoff' },
  { id: 'pipeline', name: 'Pipeline' },
  { id: 'finish',   name: 'Finish' },
];

/* ── Missions ─────────────────────────────────────────────── */
export const STEPS = [
  /* ── 1. Welcome ──────────────────────────────────────────── */
  {
    chapter: 'welcome',
    title: 'Take Nazar for a 3-minute test drive.',
    value: 'You will send a real message to a real AI, teach it a new fact, and watch it reply — all in this browser.',
    mission: 'Click "Start tour" when ready.',
  },

  /* ── 2. Inbox: see real conversations ────────────────────── */
  {
    chapter: 'inbox',
    title: 'This is your unified inbox.',
    value: 'Every WhatsApp conversation in one place — and the AI has already replied to most of them, on its own.',
    mission: 'Open the Inbox and pick any conversation that catches your eye.',
    route: '/inbox',
    selector: '.conv-list',
    verify: () => /^\/inbox\/[\w-]+/.test(window.location.pathname),
    action: {
      label: 'Show me',
      run: () => {
        if (window.location.pathname !== '/inbox') return false;
        const item = $('.conv-list .conv-item');
        if (item) { item.click(); return true; }
        return false;
      },
    },
    completion: 'Notice the AI label on past replies — those went out without anyone touching the keyboard.',
  },

  /* ── 3. Send a message as the customer (THE moment) ──────── */
  {
    chapter: 'live',
    title: 'Send a message as the customer.',
    value: 'Type anything a real prospect would ask. The AI will answer using your business knowledge — live, in real time.',
    mission: 'Switch to Test Mode at the bottom of the chat, type a question, and press Send.',
    hint: 'Try: "What is your warranty?" or "Can you do my kitchen in 2 weeks?"',
    selector: '.chat-input-wrapper',
    verify: () => {
      // succeeds when a new outbound bot reply appears after a sim-mode inbound
      const msgs = $$('.chat-messages .message-bubble, .chat-messages [class*="message"]');
      return msgs.length >= 2 && /test|sim/i.test(document.body.innerHTML.slice(-5000)) && countMessages() > (window.__tourBaselineMsgs || 0);
    },
    action: {
      label: 'Show me',
      run: () => {
        // Find Test-Mode toggle and activate it
        const simBtn = $$('.mode-btn').find(b => /test mode/i.test(b.textContent || ''));
        if (simBtn && !simBtn.classList.contains('mode-btn--active')) simBtn.click();
        // Pre-fill the input
        const input = $('.chat-input input');
        if (input) {
          window.__tourBaselineMsgs = countMessages();
          setInputValue('.chat-input input', 'What is your warranty and how long does delivery take?');
        }
        return !!input;
      },
    },
    completion: 'That reply was generated just now. Three to five seconds — that is real LLM latency, not a script.',
  },

  /* ── 4. Teach the AI a new fact ──────────────────────────── */
  {
    chapter: 'teach',
    title: 'Teach the AI a new fact.',
    value: 'No retraining. No deployment. Add a fact, hit save, and the very next reply will use it.',
    mission: 'Open Knowledge Base → Quick Edit, add one new line at the top, and save.',
    hint: 'Suggested line:  We are running a 10% Diwali discount this month on all kitchens.',
    route: '/knowledge',
    selector: '.kb-editor, .kb-tabs',
    verify: () => {
      const ta = $('.kb-textarea');
      if (!ta) return false;
      // success when the textarea contains our suggested phrase OR the "Saved!" badge appears
      const txt = ta.value || '';
      const savedBadge = /saved!/i.test(document.body.innerText.slice(0, 5000));
      return /diwali|discount|10%/i.test(txt) || savedBadge;
    },
    action: {
      label: 'Show me',
      run: () => {
        // ensure quick-edit tab is active
        const tab = $$('.kb-tabs .tab').find(t => /quick edit/i.test(t.textContent || ''));
        if (tab && !tab.classList.contains('tab--active')) tab.click();
        setTimeout(() => {
          const ta = $('.kb-textarea');
          if (!ta) return;
          const newLine = 'We are running a 10% Diwali discount this month on all kitchens. Quote valid till month end.\n\n';
          setInputValue('.kb-textarea', newLine + (ta.value || ''));
        }, 200);
        return true;
      },
    },
    completion: 'Saved. That fact is live. Let us prove it.',
  },

  /* ── 5. Prove the AI learned ─────────────────────────────── */
  {
    chapter: 'teach',
    title: 'Now ask the AI about it.',
    value: 'The fact you just saved is already in the AI’s knowledge — no rebuild, no waiting.',
    mission: 'Go back to the same conversation and ask about the new fact.',
    hint: 'Try: "Are there any offers running this month?"',
    selector: '.chat-input-wrapper',
    verify: () => {
      // Detect a fresh outbound bot reply since this step started
      const msgs = $$('.chat-messages .message-bubble, .chat-messages [class*="message"]');
      return msgs.length >= ((window.__tourTeachBaseline || 0) + 2);
    },
    action: {
      label: 'Show me',
      run: () => {
        // Navigate back to inbox first if needed
        if (!/^\/inbox\/[\w-]+/.test(window.location.pathname)) {
          // best effort: go back to inbox list
          window.history.back();
          return false;
        }
        const simBtn = $$('.mode-btn').find(b => /test mode/i.test(b.textContent || ''));
        if (simBtn && !simBtn.classList.contains('mode-btn--active')) simBtn.click();
        window.__tourTeachBaseline = countMessages();
        setInputValue('.chat-input input', 'Are there any offers running this month?');
        return true;
      },
    },
    completion: 'The reply just used a fact that did not exist sixty seconds ago.',
  },

  /* ── 6. Human handoff ────────────────────────────────────── */
  {
    chapter: 'human',
    title: 'The AI knows when to step aside.',
    value: 'Negotiations, complaints, sensitive cases — the AI escalates and waits for a human. No more bots making promises they shouldn’t.',
    mission: 'Open Inbox and find the contact "Pranav Shetty" (Negotiation). The status will say "You are handling".',
    route: '/inbox',
    selector: '.conv-list',
    verify: () => {
      // succeeds once the user lands on a conversation with a paused bot
      if (!/^\/inbox\/[\w-]+/.test(window.location.pathname)) return false;
      const banner = document.body.innerText.slice(0, 8000);
      return /you are handling|owner handling|needs your reply/i.test(banner);
    },
    action: {
      label: 'Show me',
      run: () => {
        if (window.location.pathname !== '/inbox') return false;
        // Find "Pranav" item by name text
        const items = $$('.conv-item');
        const target = items.find(i => /pranav/i.test(i.textContent || ''));
        if (target) { target.click(); return true; }
        // fallback: first escalated/paused conv
        const escalated = $('.conv-item--escalated');
        if (escalated) { escalated.click(); return true; }
        return false;
      },
    },
    completion: 'Notice the handoff reason at the top. The AI explains why it stepped back so your team can pick up smoothly.',
  },

  /* ── 7. Pipeline auto-organises ─────────────────────────── */
  {
    chapter: 'pipeline',
    title: 'Your pipeline updates itself.',
    value: 'Stage, deal value, lead score — the AI reads the conversation and sets them. You never have to log in to update a CRM again.',
    mission: 'Open Contacts and switch to the Pipeline view. Look for the AI badge on each card.',
    route: '/contacts',
    selector: '.pipeline-board, .page-content',
    verify: () => exists('.pipeline-board')() || /pipeline/i.test(window.location.search),
    action: {
      label: 'Show me',
      run: () => {
        // Try to click a "Pipeline" view toggle button if present
        const tabs = $$('button, a');
        const pipelineBtn = tabs.find(t => /pipeline/i.test(t.textContent || '') && t.tagName !== 'A');
        if (pipelineBtn) { pipelineBtn.click(); return true; }
        return false;
      },
    },
    completion: 'Every card shows the stage the AI assigned, and the value it inferred from the conversation.',
  },

  /* ── 8. Done ─────────────────────────────────────────────── */
  {
    chapter: 'finish',
    title: 'You just ran an AI sales agent.',
    value: 'In three minutes you sent a real message, taught the AI live, watched it learn, saw it hand off cleanly, and saw your pipeline organise itself. That is Nazar.',
    mission: 'Want to do this with your own data? Book a 20-minute setup call and we will load your business in.',
    cta: { label: 'Book a setup call', href: 'mailto:hello@nazar.app?subject=Nazar%20setup%20call' },
  },
];
