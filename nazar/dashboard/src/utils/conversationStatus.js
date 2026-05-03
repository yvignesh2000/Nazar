/**
 * Computes a single, unambiguous status for a conversation based on
 *   • whether the bot is on or paused
 *   • the direction of the last message (inbound/outbound)
 *   • who sent it (bot / human / customer)
 *   • how long ago it was
 *
 * The goal: a viewer should never see "AI is replying" while a customer
 * message sits unanswered at the bottom. The status answers the question
 * "what is happening with this conversation right now?"
 *
 * Returned shape:
 *   {
 *     id:        machine id (used for CSS / filtering)
 *     label:     short text shown in the badge
 *     tone:      'success' | 'primary' | 'orange' | 'gray' | 'warning'
 *     hint:      tooltip / longer description (optional)
 *     animated:  true if the badge should pulse (e.g. AI thinking)
 *   }
 */

export const STATUSES = {
  NO_MESSAGES:    { id: 'no_messages',    label: 'No messages yet',     tone: 'gray',    animated: false },
  AI_REPLIED:     { id: 'ai_replied',     label: 'AI replied',          tone: 'success', animated: false },
  YOU_REPLIED:    { id: 'you_replied',    label: 'You replied',         tone: 'gray',    animated: false },
  AI_THINKING:    { id: 'ai_thinking',    label: 'AI is responding…',   tone: 'primary', animated: true  },
  AI_PENDING:     { id: 'ai_pending',     label: 'Awaiting AI reply',   tone: 'primary', animated: false },
  NEEDS_REPLY:    { id: 'needs_reply',    label: 'Needs your reply',    tone: 'orange',  animated: false },
  YOU_HANDLING:   { id: 'you_handling',   label: 'You are handling',    tone: 'orange',  animated: false },
  DRAFT_PENDING:  { id: 'draft_pending',  label: 'Draft awaiting review', tone: 'warning', animated: true },
};

/**
 * @param {object} args
 * @param {boolean} args.botOn        true if AI auto-reply is enabled for this contact
 * @param {string}  args.lastDir      'inbound' | 'outbound'
 * @param {string}  args.lastSender   'bot' | 'bot-approved' | 'human' | 'customer' | 'contact'
 * @param {string}  args.lastTime     ISO timestamp of the last message
 * @param {boolean} args.hasDraft     true if there is a pending AI draft awaiting approval
 * @param {string}  args.replyMode    'auto_ai' | 'ai_draft' | 'human_only'
 * @returns {object} status entry from STATUSES
 */
export function getConversationStatus({
  botOn = true,
  lastDir = null,
  lastSender = null,
  lastTime = null,
  hasDraft = false,
  replyMode = 'auto_ai',
} = {}) {
  // No messages at all
  if (!lastDir) return STATUSES.NO_MESSAGES;

  // Pending draft has highest priority (human review queue)
  if (hasDraft) return STATUSES.DRAFT_PENDING;

  const isCustomerLast = lastDir === 'inbound';
  const minutesAgo = lastTime
    ? Math.max(0, (Date.now() - new Date(lastTime).getTime()) / 60000)
    : 9999;

  // Bot paused
  if (!botOn) {
    if (isCustomerLast) return STATUSES.NEEDS_REPLY;
    return STATUSES.YOU_HANDLING;
  }

  // Bot on, customer was last to message
  if (isCustomerLast) {
    // ai_draft mode: AI generates a draft, doesn't auto-send → awaiting review
    if (replyMode === 'ai_draft') return STATUSES.DRAFT_PENDING;
    // human_only: bot is technically "on" but mode is human → needs reply
    if (replyMode === 'human_only') return STATUSES.NEEDS_REPLY;
    // auto_ai: < 60s = thinking, otherwise stuck/awaiting
    if (minutesAgo < 1) return STATUSES.AI_THINKING;
    return STATUSES.AI_PENDING;
  }

  // Bot on, last message was outbound
  if (lastSender === 'human') return STATUSES.YOU_REPLIED;
  return STATUSES.AI_REPLIED; // 'bot' or 'bot-approved'
}

/**
 * Maps a status tone → existing Badge component variant.
 */
export function statusToBadgeVariant(tone) {
  switch (tone) {
    case 'success': return 'success';
    case 'primary': return 'primary';
    case 'orange':  return 'orange';
    case 'warning': return 'warning';
    case 'gray':
    default:        return 'default';
  }
}
