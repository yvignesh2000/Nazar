/**
 * Centralized API client for Nazar backend.
 * All API calls go through here — single place for auth, error handling, base URL.
 */

const API_KEY = 'nazar_dev_key';
const BASE = '/api';

class ApiError extends Error {
  constructor(status, message, data = null) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

async function request(method, path, body = null, params = null) {
  const url = new URL(`${BASE}${path}`, window.location.origin);
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== null && v !== undefined && v !== '') url.searchParams.set(k, v);
    });
  }

  const opts = {
    method,
    headers: {
      'X-API-Key': API_KEY,
      ...(body ? { 'Content-Type': 'application/json' } : {}),
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
  };

  const res = await fetch(url.toString(), opts);
  const data = await res.json().catch(() => null);

  if (!res.ok) {
    throw new ApiError(res.status, data?.detail || res.statusText, data);
  }

  return data;
}

// Convenience methods
const get    = (path, params) => request('GET', path, null, params);
const post   = (path, body)   => request('POST', path, body);
const patch  = (path, body)   => request('PATCH', path, body);
const del    = (path)          => request('DELETE', path);
const put    = (path, body)   => request('PUT', path, body);

// ====================================================================
//  API MODULES
// ====================================================================

export const overview = {
  get: () => get('/overview'),
};

export const activity = {
  list: () => get('/activity'),
};

export const contacts = {
  list: (params) => get('/contacts', params),
  get: (id) => get(`/contacts/${id}`),
  create: (data) => post('/contacts', data),
  update: (id, data) => patch(`/contacts/${id}`, data),
  delete: (id) => del(`/contacts/${id}`),
  import: (csv) => post('/contacts/import', { csv_content: csv }),
};

export const conversations = {
  list: () => get('/conversations'),
  get: (id, days = 7) => get(`/conversations/${id}`, { days }),
  send: (id, message) => post(`/conversations/${id}/send`, { message }),
  handover: (id, botOn) => post(`/conversations/${id}/handover`, { bot_on: botOn }),
};

export const handoffs = {
  list: () => get('/handoffs'),
  history: () => get('/handoffs/history'),
  stats: () => get('/handoffs/stats'),
  resume: (id, reason) => post(`/handoffs/${id}/resume`, { reason }),
};

export const pipeline = {
  get: () => get('/pipeline'),
  moveStage: (id, stage) => post(`/pipeline/${id}/move`, { stage }),
};

export const followups = {
  list: () => get('/followups'),
};

export const broadcasts = {
  send: (data) => post('/broadcast', data),
  history: () => get('/broadcasts'),
};

export const templates = {
  list: (params) => get('/templates', params),
  get: (id) => get(`/templates/${id}`),
  create: (data) => post('/templates', data),
  update: (id, data) => patch(`/templates/${id}`, data),
  delete: (id) => del(`/templates/${id}`),
  render: (id, contactId) => post(`/templates/${id}/render`, { contact_id: contactId }),
};

export const config = {
  get: () => get('/config'),
  update: (data) => post('/config', data),
};

export const kb = {
  get: () => get('/kb'),
  update: (content) => post('/kb', { content }),
};

export const team = {
  list: () => get('/team'),
};

export const digest = {
  today: () => get('/digest/today'),
  generate: () => post('/digest/generate'),
  history: () => get('/digest/history'),
};

export const memory = {
  get: (contactId, query) => get(`/contacts/${contactId}/memory`, { query }),
};

export const health = {
  check: () => get('/health'),
  llm: () => get('/llm/health'),
};

export { ApiError };
