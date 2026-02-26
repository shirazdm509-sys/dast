/* app.js - نقطه ورود اصلی */

import { id, v, esc, toast } from './utils.js';
import { API, token, role, uname, setAuth, clearAuth, api } from './api.js';
import { sendMsg, stopStream, clearChat, onKey, resizeInput } from './chat.js';
import { toggleSB, closeSB, stab, loadFiles } from './sidebar.js';
import { loadTickets, openNewTicket, sendNewTicket, openTicket, sendReply, closeTicketStatus, closeTicketModal } from './support.js';
import { openAdmin, closeAdmin, atab, createUser, prevColor, saveSettings } from './admin.js';

let deferredInstall = null;

// ── PWA ──────────────────────────────────────────────────────
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(() => {});
}
window.addEventListener('beforeinstallprompt', e => {
  e.preventDefault();
  deferredInstall = e;
  id('installBanner')?.classList.add('show');
});

function installPWA() {
  if (deferredInstall) { deferredInstall.prompt(); deferredInstall = null; }
  id('installBanner')?.classList.remove('show');
}

// ── AUTH ──────────────────────────────────────────────────────
(function init() { if (token) showApp(); })();

async function doLogin() {
  const u = v('lu'), p = v('lp');
  const err = id('lerr');
  err.style.display = 'none';
  if (!u || !p) { showErr(err, 'نام کاربری و رمز الزامی است'); return; }
  try {
    const r = await api('/auth/login', 'POST', { username: u, password: p }, false);
    setAuth(r.access_token, r.role, r.username);
    showApp();
  } catch (e) { showErr(err, e.message || 'خطا در ورود'); }
}

function showErr(el, msg) { el.textContent = msg; el.style.display = 'block'; }

function showApp() {
  id('loginScreen').style.display = 'none';
  id('app').style.display = 'flex';
  id('huser').textContent = uname;
  const rt = id('hrole');
  rt.textContent = role === 'admin' ? 'ادمین' : 'کاربر';
  rt.className = 'rtag ' + (role === 'admin' ? 'a' : 'u');
  if (role === 'admin') id('btnAdmin').style.display = 'flex';
  loadPubSettings();
  loadFiles();
  loadTickets();
  checkBroadcast();
}

function doLogout() { clearAuth(); }

// ── PUBLIC SETTINGS ───────────────────────────────────────────
async function loadPubSettings() {
  try {
    const s = await api('/settings/public', 'GET', null, false);
    if (s.site_title) { id('siteTitle').textContent = s.site_title; document.title = s.site_title; }
    if (s.site_subtitle) id('siteSub').textContent = s.site_subtitle;
    if (s.welcome_text) {
      const el = id('welcomeTxt');
      if (el) el.textContent = s.welcome_text;
    }
    if (s.primary_color) document.documentElement.style.setProperty('--ac', s.primary_color);
    if (s.gold_color) document.documentElement.style.setProperty('--gold', s.gold_color);
    // Logo
    if (s.logo_url) {
      const logoImg = id('siteLogo');
      if (logoImg) logoImg.src = s.logo_url;
    }
  } catch (e) { /* ignore */ }
}

window.addEventListener('refreshSettings', loadPubSettings);

// ── BROADCAST ────────────────────────────────────────────────
async function checkBroadcast() {
  try {
    const b = await api('/broadcast/latest');
    if (!b || !b.message) return;
    const lastSeen = localStorage.getItem('lastBroadcast');
    if (lastSeen === b.id) return;
    toast(b.message, 'ok');
    localStorage.setItem('lastBroadcast', b.id);
  } catch (e) { /* ignore */ }
}

// ── Register all global functions for HTML onclick handlers ──
window.doLogin = doLogin;
window.doLogout = doLogout;
window.showApp = showApp;
window.installPWA = installPWA;
window.sendMsg = sendMsg;
window.stopStream = stopStream;
window.clearChat = clearChat;
window.onKey = onKey;
window.resizeInput = resizeInput;
window.toggleSB = toggleSB;
window.closeSB = closeSB;
window.stab = stab;
window.openAdmin = openAdmin;
window.closeAdmin = closeAdmin;
window.atab = atab;
window.createUser = createUser;
window.prevColor = prevColor;
window.saveSettings = saveSettings;
window.openNewTicket = openNewTicket;
window.sendNewTicket = sendNewTicket;
window.openTicket = openTicket;
window.sendReply = sendReply;
window.closeTicketStatus = closeTicketStatus;
window.closeTicketModal = closeTicketModal;
window.submitBug = submitBug;

// ── BUG SUBMIT ───────────────────────────────────────────────
async function submitBug() {
  const t = v('btitle'), d = v('bdesc');
  if (!t || !d) { toast('عنوان و توضیح الزامی است', 'er'); return; }
  try {
    await api('/bugs', 'POST', { title: t, description: d, question: v('bq') });
    id('bsuc').style.display = 'block';
    ['btitle', 'bdesc', 'bq'].forEach(x => id(x).value = '');
    setTimeout(() => id('bsuc').style.display = 'none', 3000);
  } catch (e) { toast(e.message, 'er'); }
}

// ── Login enter key ──────────────────────────────────────────
id('lp')?.addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });
id('lu')?.addEventListener('keydown', e => { if (e.key === 'Enter') id('lp')?.focus(); });
