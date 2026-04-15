/**
 * Nazar — Formatting Utilities
 *
 * Centralised formatters for currency, dates, numbers, and text.
 * Replaces all hardcoded ₹ symbols and date strings scattered across pages.
 */

// ---------------------------------------------------------------------------
// Currency
// ---------------------------------------------------------------------------

/**
 * Supported currencies. Add more as needed.
 * key: ISO 4217 code  →  value: symbol
 */
export const CURRENCIES = {
  INR: '₹',
  USD: '$',
  EUR: '€',
  GBP: '£',
  AED: 'د.إ',
  SGD: 'S$',
  AUD: 'A$',
  CAD: 'C$',
};

/**
 * Format a numeric amount as a currency string.
 *
 * @param {number} amount  - Numeric value
 * @param {string} currency - ISO 4217 code (default: read from localStorage, fallback INR)
 * @param {object} opts    - Intl.NumberFormat options override
 * @returns {string}       e.g. "₹1,25,000" or "$1,250"
 */
export function formatCurrency(amount, currency, opts = {}) {
  const code = currency || getConfiguredCurrency();
  const symbol = CURRENCIES[code] || code;

  if (typeof amount !== 'number' || isNaN(amount)) {
    return `${symbol}0`;
  }

  try {
    const formatted = new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: code,
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
      ...opts,
    }).format(amount);
    return formatted;
  } catch {
    // Fallback for unsupported locales
    return `${symbol}${amount.toLocaleString()}`;
  }
}

/**
 * Format a compact currency (e.g. ₹1.2L, $1.2M).
 */
export function formatCurrencyCompact(amount, currency) {
  const code = currency || getConfiguredCurrency();
  const symbol = CURRENCIES[code] || code;

  if (typeof amount !== 'number' || isNaN(amount)) return `${symbol}0`;

  if (amount >= 10_000_000) return `${symbol}${(amount / 10_000_000).toFixed(1)}Cr`;
  if (amount >= 100_000)    return `${symbol}${(amount / 100_000).toFixed(1)}L`;
  if (amount >= 1_000_000)  return `${symbol}${(amount / 1_000_000).toFixed(1)}M`;
  if (amount >= 1_000)      return `${symbol}${(amount / 1_000).toFixed(1)}K`;
  return `${symbol}${amount}`;
}

/**
 * Read the configured currency from localStorage (set in Settings page).
 * Falls back to INR.
 */
export function getConfiguredCurrency() {
  try {
    return localStorage.getItem('nazar_currency') || 'INR';
  } catch {
    return 'INR';
  }
}

/**
 * Save the user's preferred currency to localStorage.
 */
export function setConfiguredCurrency(code) {
  if (CURRENCIES[code]) {
    localStorage.setItem('nazar_currency', code);
  }
}

// ---------------------------------------------------------------------------
// Dates & times
// ---------------------------------------------------------------------------

/**
 * Format an ISO timestamp as a human-friendly relative string.
 * e.g. "2 hours ago", "Yesterday", "14 Jan"
 */
export function formatRelativeTime(isoString) {
  if (!isoString) return '';
  try {
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now - date;
    const diffSec = Math.floor(diffMs / 1000);
    const diffMin = Math.floor(diffSec / 60);
    const diffHr  = Math.floor(diffMin / 60);
    const diffDay = Math.floor(diffHr / 24);

    if (diffSec < 60)   return 'Just now';
    if (diffMin < 60)   return `${diffMin}m ago`;
    if (diffHr < 24)    return `${diffHr}h ago`;
    if (diffDay === 1)  return 'Yesterday';
    if (diffDay < 7)    return `${diffDay}d ago`;

    return date.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
  } catch {
    return isoString;
  }
}

/**
 * Format an ISO timestamp as a full date-time string.
 * e.g. "14 Jan 2026, 10:35 AM"
 */
export function formatDateTime(isoString) {
  if (!isoString) return '';
  try {
    return new Date(isoString).toLocaleString('en-IN', {
      day: 'numeric', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  } catch {
    return isoString;
  }
}

// ---------------------------------------------------------------------------
// Numbers
// ---------------------------------------------------------------------------

/**
 * Format a percentage (0-100) with one decimal.
 */
export function formatPercent(value) {
  if (typeof value !== 'number' || isNaN(value)) return '0%';
  return `${value.toFixed(1)}%`;
}

/**
 * Compact number format: 1500 → "1.5K", 1200000 → "1.2M"
 */
export function formatNumber(n) {
  if (typeof n !== 'number' || isNaN(n)) return '0';
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000)     return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}
