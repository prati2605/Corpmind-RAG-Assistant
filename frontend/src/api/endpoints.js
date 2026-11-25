/** One function per backend endpoint. Pages never build URLs themselves. */
import { api } from "./client";

export const auth = {
  login: (email, password) => api("/auth/login", { method: "POST", body: { email, password } }),
  register: (data) => api("/auth/register", { method: "POST", body: data }),
  logout: () => api("/auth/logout", { method: "POST" }),
};

export const me = {
  get: () => api("/users/me"),
  update: (data) => api("/users/me", { method: "PATCH", body: data }),
  changePassword: (current_password, new_password) =>
    api("/users/me/password", { method: "POST", body: { current_password, new_password } }),
  categories: () => api("/categories"),
  stats: () => api("/dashboard/stats"),
};

export const chat = {
  ask: (question, conversationId, filters) =>
    api("/chat/ask", { method: "POST", body: { question, conversation_id: conversationId || null, filters } }),
  conversations: (q) => api("/chat/conversations", { query: { q, limit: 100 } }),
  conversation: (id) => api(`/chat/conversations/${id}`),
  rename: (id, title) => api(`/chat/conversations/${id}`, { method: "PATCH", body: { title } }),
  clear: (id) => api(`/chat/conversations/${id}/clear`, { method: "POST" }),
  remove: (id) => api(`/chat/conversations/${id}`, { method: "DELETE" }),
  feedback: (messageId, rating, comment) =>
    api(`/chat/messages/${messageId}/feedback`, { method: "PUT", body: { rating, comment: comment || null } }),
  removeFeedback: (messageId) => api(`/chat/messages/${messageId}/feedback`, { method: "DELETE" }),
  suggestions: () => api("/chat/suggestions"),
};

export const documents = {
  list: (params) => api("/documents", { query: params }),
  get: (id) => api(`/documents/${id}`),
  chunk: (chunkId) => api(`/documents/chunks/${encodeURIComponent(chunkId)}`),
  pageChunks: (id, page) => api(`/documents/${id}/chunks`, { query: { page } }),
  upload: (files, categoryId, { title, description, effectiveDate } = {}) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    form.append("category_id", String(categoryId));
    if (title) form.append("title", title);
    if (description) form.append("description", description);
    if (effectiveDate) form.append("effective_date", effectiveDate);
    return api("/documents", { method: "POST", form });
  },
  uploadVersion: (id, file, effectiveDate) => {
    const form = new FormData();
    form.append("file", file);
    if (effectiveDate) form.append("effective_date", effectiveDate);
    return api(`/documents/${id}/versions`, { method: "POST", form });
  },
  activate: (id, versionId) => api(`/documents/${id}/versions/${versionId}/activate`, { method: "POST" }),
  reprocess: (id, versionId) => api(`/documents/${id}/versions/${versionId}/reprocess`, { method: "POST" }),
  removeVersion: (id, versionId) => api(`/documents/${id}/versions/${versionId}`, { method: "DELETE" }),
  remove: (id) => api(`/documents/${id}`, { method: "DELETE" }),
};

export const admin = {
  users: (params) => api("/admin/users", { query: { limit: 200, ...params } }),
  createUser: (data) => api("/admin/users", { method: "POST", body: data }),
  updateUser: (id, data) => api(`/admin/users/${id}`, { method: "PATCH", body: data }),
  categories: () => api("/admin/categories"),
  createCategory: (data) => api("/admin/categories", { method: "POST", body: data }),
  setCategoryRoles: (id, roles) => api(`/admin/categories/${id}/roles`, { method: "PUT", body: { roles } }),
  deleteCategory: (id) => api(`/admin/categories/${id}`, { method: "DELETE" }),
  analytics: (days) => api("/admin/analytics", { query: { days } }),
  feedback: (rating) => api("/admin/feedback", { query: { rating } }),
  auditLogs: (action) => api("/admin/audit-logs", { query: { action, limit: 200 } }),
};
