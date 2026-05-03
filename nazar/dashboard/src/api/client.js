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

function getToken() {
  return localStorage.getItem('nazar_token');
}

async function request(method, path, body = null, params = null, customHeaders = {}) {
  const url = new URL(`${BASE}${path}`, window.location.origin);
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== null && v !== undefined && v !== '') url.searchParams.set(k, v);
    });
  }

  const token = getToken();
  const headers = {
    ...(token ? { 'Authorization': `Bearer ${token}` } : { 'X-Nazar-Key': API_KEY }),
    ...(body ? { 'Content-Type': 'application/json' } : {}),
    ...customHeaders,
  };

  const opts = {
    method,
    headers,
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
  import: (csv) => post('/contacts/import', { csv }),
  // 24h service window
  getWindow: (id) => get(`/contacts/${id}/window`),
  listWindows: (stage) => get('/contacts/windows', { stage }),
};

export const conversations = {
  list: () => get('/conversations'),
  get: (id, days = 7) => get(`/conversations/${id}`, { days }),
  send: (id, message) => post(`/conversations/${id}/send`, { message }),
  handover: (id, botOn) => post(`/conversations/${id}/handover`, { bot_mode: botOn }),
};

export const handoffs = {
  list: () => get('/handoffs'),
  history: () => get('/handoffs/history'),
  stats: () => get('/handoffs/stats'),
  resume: (id, reason) => post(`/handoffs/${id}/resume`, { reason }),
};

export const pipeline = {
  get: () => get('/pipeline'),
  moveStage: (id, stage) => patch(`/pipeline/${id}/move`, { stage }),
  enableAutoClassify: (id) => patch(`/pipeline/${id}/auto-classify`),
};

export const followups = {
  list: () => get('/followups'),
};

export const campaigns = {
  list: () => get('/campaigns'),
  get: (id) => get(`/campaigns/${id}`),
  create: (data) => post('/campaigns', data),
  retarget: (id, type = 'failed') => post(`/campaigns/${id}/retarget`, { type }),
  audienceAnalysis: (stage, tag) => get('/campaigns/audience-analysis', { stage, tag }),
};

export const jobs = {
  get: (jobId) => get(`/jobs/${jobId}`),
  list: (params) => get('/jobs', params),
  cancel: (jobId) => post(`/jobs/${jobId}/cancel`),
};

export const replyModes = {
  get: (contactId) => get(`/reply-modes/${contactId}`),
  set: (contactId, mode) => put(`/reply-modes/${contactId}`, { mode }),
  clear: (contactId) => del(`/reply-modes/${contactId}`),
};

export const drafts = {
  list: () => get('/drafts'),
  get: (contactId) => get(`/drafts/${contactId}`),
  approve: (contactId, editedText) => post(`/drafts/${contactId}/approve`, { edited_text: editedText || '' }),
  reject: (contactId) => post(`/drafts/${contactId}/reject`),
  regenerate: (contactId) => post(`/drafts/${contactId}/regenerate`),
};

export const templates = {
  list: (params) => get('/templates', params),
  get: (id) => get(`/templates/${id}`),
  create: (data) => post('/templates', data),
  update: (id, data) => patch(`/templates/${id}`, data),
  delete: (id) => del(`/templates/${id}`),
  render: (id, contactId) => post(`/templates/${id}/render`, { contact_id: contactId }),
  // Meta template sync
  metaStatus: () => get('/templates/meta/status'),
  submitToMeta: (id) => post(`/templates/${id}/submit-to-meta`),
  getMetaStatus: (id) => get(`/templates/${id}/meta-status`),
  syncWithMeta: () => post('/templates/meta/sync'),
};

export const config = {
  get: () => get('/config'),
  update: (data) => put('/config', data),
};

export const kb = {
  get: () => get('/kb'),
  update: (content) => post('/kb/upload', { content }),
  listDocuments: (params) => get('/kb/documents', params),
  addDocument: (data) => post('/kb/documents', data),
  deleteDocument: (id) => del(`/kb/documents/${id}`),
  moveDocument: (id, folderId) => patch(`/kb/documents/${id}/move`, { folder_id: folderId }),
  uploadFile: (file, title = '', scope = 'global', folderId = '') => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('title', title);
    formData.append('scope', scope);
    if (folderId) formData.append('folder_id', folderId);
    const token = localStorage.getItem('nazar_token');
    const headers = token ? { 'Authorization': `Bearer ${token}` } : { 'X-Nazar-Key': 'nazar_dev_key' };
    return fetch(`/api/kb/upload-file`, { method: 'POST', headers, body: formData })
      .then(async res => {
        const data = await res.json().catch(() => null);
        if (!res.ok) throw new Error(data?.detail || res.statusText);
        return data;
      });
  },
  uploadFiles: (files, scope = 'global', folderId = '') => {
    const formData = new FormData();
    for (const file of files) {
      formData.append('files', file);
    }
    formData.append('scope', scope);
    if (folderId) formData.append('folder_id', folderId);
    const token = localStorage.getItem('nazar_token');
    const headers = token ? { 'Authorization': `Bearer ${token}` } : { 'X-Nazar-Key': 'nazar_dev_key' };
    return fetch(`/api/kb/upload-files`, { method: 'POST', headers, body: formData })
      .then(async res => {
        const data = await res.json().catch(() => null);
        if (!res.ok) throw new Error(data?.detail || res.statusText);
        return data;
      });
  },
  // Folder operations
  listFolders: (parentId) => get('/kb/folders', parentId !== undefined ? { parent_id: parentId } : {}),
  createFolder: (name, parentId) => post('/kb/folders', { name, parent_id: parentId || null }),
  renameFolder: (id, name) => patch(`/kb/folders/${id}`, { name }),
  deleteFolder: (id, recursive = false) => del(`/kb/folders/${id}?recursive=${recursive}`),
};

export const groups = {
  list: () => get('/groups'),
  get: (id) => get(`/groups/${id}`),
  create: (data) => post('/groups', data),
  update: (id, data) => patch(`/groups/${id}`, data),
  delete: (id) => del(`/groups/${id}`),
  addMembers: (id, contactIds) => post(`/groups/${id}/members`, { contact_ids: contactIds }),
  removeMembers: (id, contactIds) => request('DELETE', `/groups/${id}/members`, { contact_ids: contactIds }),
  getContactGroups: (contactId) => get(`/contacts/${contactId}/groups`),
};

export const team = {
  list: () => get('/team'),
};

export const digest = {
  today: () => get('/digest'),
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

export const setup = {
  status: () => get('/setup/status'),
  saveKeys: (keys) => post('/setup/keys', { keys }),
  testLlm: () => post('/setup/test-llm'),
};

export const simulate = {
  message: (contactId, message) => post('/simulate/message', { contact_id: contactId, message }),
};

// ====================================================================
//  NEW API MODULES — Auth, Analytics, Billing, Users, Onboarding
// ====================================================================

export const auth = {
  login: (email, password, workspaceId = 'default') =>
    request('POST', '/auth/login', { email, password, workspace_id: workspaceId }, null, { 'X-Nazar-Key': API_KEY }),
  logout: () => post('/auth/logout'),
  me: (tokenOverride) =>
    request('GET', '/auth/me', null, null, tokenOverride ? { 'Authorization': `Bearer ${tokenOverride}` } : {}),
};

export const analytics = {
  snapshot: () => get('/analytics'),
  conversations: (days = 7) => get('/analytics/conversations', { days }),
  pipeline: () => get('/analytics/pipeline'),
  campaigns: (days = 30) => get('/analytics/campaigns', { days }),
  ai: (days = 7) => get('/analytics/ai', { days }),
  leads: () => get('/analytics/leads'),
  trend: (days = 14) => get('/analytics/trend', { days }),
};

export const billing = {
  plans: () => get('/billing/plans'),
  subscription: () => get('/billing/subscription'),
  usage: () => get('/billing/usage'),
  upgrade: (planId) => post('/billing/upgrade', { plan_id: planId }),
  cancel: (atPeriodEnd = true) => post('/billing/cancel', { at_period_end: atPeriodEnd }),
};

export const payments = {
  config: () => get('/payments/config'),
  subscribe: (planId) => post('/payments/subscribe', { plan_id: planId }),
  verify: (data) => post('/payments/verify', data),
  invoice: (workspaceId) => get(`/payments/invoice/${workspaceId}`),
};

export const users = {
  list: () => get('/users'),
  create: (data) => post('/users', data),
  update: (id, data) => patch(`/users/${id}`, data),
  delete: (id) => del(`/users/${id}`),
  changePassword: (id, oldPassword, newPassword) =>
    post(`/users/${id}/change-password`, { old_password: oldPassword, new_password: newPassword }),
};

export const invites = {
  list: () => get('/invites'),
  create: (email, role = 'agent') => post('/invites', { email, role }),
  accept: (token, name, password) => post(`/invites/${token}/accept`, { name, password }),
};

export const workspace = {
  get: () => get('/workspace'),
  update: (data) => patch('/workspace', data),
};

export const onboarding = {
  get: () => get('/onboarding'),
  markDone: (stepId) => post(`/onboarding/step/${stepId}/done`),
  skip: (stepId) => post(`/onboarding/step/${stepId}/skip`),
  readiness: () => get('/onboarding/readiness'),
};

export { ApiError };
