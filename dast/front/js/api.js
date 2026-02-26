/* api.js - مدیریت API و احراز هویت */

import { toast } from './utils.js';

export const API = 'https://ai.dastgheibqoba.info/api';

export let token = localStorage.getItem('tk');
export let role = localStorage.getItem('rl');
export let uname = localStorage.getItem('un');

export function setAuth(newToken, newRole, newUname) {
  token = newToken;
  role = newRole;
  uname = newUname;
  localStorage.setItem('tk', token);
  localStorage.setItem('rl', role);
  localStorage.setItem('un', uname);
}

export function clearAuth() {
  localStorage.clear();
  location.reload();
}

export async function api(path, method = 'GET', body = null, auth = true) {
  const opts = { method, headers: {} };
  if (auth && token) opts.headers['Authorization'] = `Bearer ${token}`;
  if (body) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(API + path, opts);
  if (r.status === 401) { clearAuth(); return; }
  const d = await r.json();
  if (!r.ok) throw new Error(d.detail || 'خطای سرور');
  return d;
}
