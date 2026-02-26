/* admin.js - پنل مدیریت */

import { id, v, esc, toast } from './utils.js';
import { api, role } from './api.js';
import { openTicket, loadTickets, slbl } from './support.js';

export function openAdmin() {
  id('adminModal').classList.add('open');
  atab('Dashboard');
}

export function closeAdmin() {
  id('adminModal').classList.remove('open');
}

export function atab(name) {
  const tabs = ['Dashboard', 'Bugs', 'Support', 'Users', 'Settings', 'Logs'];
  document.querySelectorAll('.atab').forEach((t, i) => {
    t.classList.toggle('on', tabs[i] === name);
  });
  document.querySelectorAll('.apanel').forEach(p => p.classList.remove('on'));
  const panel = id('ap' + name);
  if (panel) panel.classList.add('on');
  const fn = {
    Dashboard: loadDashboard,
    Bugs: loadAdminBugs,
    Support: loadAdminSup,
    Users: loadAdminUsers,
    Settings: loadAdminSettings,
    Logs: loadAdminLogs
  };
  fn[name]?.();
}

// ── Dashboard ───────────────────────────────────────────────
async function loadDashboard() {
  const el = id('apDashboard');
  if (!el) return;
  try {
    const d = await api('/admin/analytics');
    el.innerHTML = `
      <div class="dash-grid">
        <div class="dash-card"><div class="num">${d.total_users}</div><div class="lbl">کاربران</div></div>
        <div class="dash-card"><div class="num">${d.questions_today}</div><div class="lbl">سوالات امروز</div></div>
        <div class="dash-card"><div class="num">${d.questions_total}</div><div class="lbl">کل سوالات</div></div>
        <div class="dash-card"><div class="num">${d.open_bugs}</div><div class="lbl">باگ باز</div></div>
        <div class="dash-card"><div class="num">${d.open_tickets}</div><div class="lbl">تیکت باز</div></div>
      </div>
      <div class="acard">
        <h4 style="font-size:12px;color:var(--mu);margin-bottom:8px">سوالات 7 روز اخیر</h4>
        <div class="chart-bar" id="dailyChart"></div>
      </div>
      <div class="acard" style="margin-top:10px">
        <h4 style="font-size:12px;color:var(--mu);margin-bottom:8px">کلمات پرتکرار</h4>
        <div id="topKeywords"></div>
      </div>`;

    // Bar chart
    const chart = id('dailyChart');
    if (chart && d.daily_questions) {
      const entries = Object.entries(d.daily_questions);
      const max = Math.max(...entries.map(e => e[1]), 1);
      chart.innerHTML = entries.map(([date, count]) => {
        const h = Math.max((count / max) * 70, 2);
        const shortDate = date.slice(5);
        return `<div style="flex:1;text-align:center">
          <div style="height:70px;display:flex;align-items:flex-end;justify-content:center">
            <div class="bar" style="height:${h}px;width:100%"></div>
          </div>
          <div class="bar-label">${shortDate}</div>
          <div style="font-size:10px;color:var(--tx)">${count}</div>
        </div>`;
      }).join('');
    }

    // Keywords
    const kwEl = id('topKeywords');
    if (kwEl && d.top_keywords) {
      kwEl.innerHTML = Object.entries(d.top_keywords)
        .map(([w, c]) => `<span class="ktag" style="margin:2px">${esc(w)} (${c})</span>`)
        .join('');
    }
  } catch (e) {
    el.innerHTML = `<p style="color:var(--er)">${e.message}</p>`;
  }
}

// ── Bugs ─────────────────────────────────────────────────────
async function loadAdminBugs() {
  try {
    const d = await api('/bugs');
    const el = id('adminBugList');
    if (!el) return;
    if (!d.bugs || !d.bugs.length) {
      el.innerHTML = '<p style="color:var(--mu);text-align:center">هیچ گزارشی وجود ندارد</p>';
      return;
    }
    el.innerHTML = `<p style="font-size:11px;color:var(--mu);margin-bottom:10px">مجموع: ${d.total} | باز: ${d.open}</p>` +
      d.bugs.map(b => {
        const safeId = esc(b.id);
        return `
        <div class="acard">
          <div class="acard-h"><div class="acard-t">${esc(b.title)}</div><span class="abadge ${b.status}">${b.status === 'open' ? 'باز' : 'حل‌شده'}</span></div>
          <div class="ameta">${esc(b.username)} - ${new Date(b.created_at).toLocaleDateString('fa-IR')}</div>
          <div class="adesc">${esc(b.description)}</div>
          ${b.question ? `<div class="aq">${esc(b.question)}</div>` : ''}
          ${b.status === 'open' ? `<button class="abtn ok" data-bid="${safeId}" onclick="window._resolveBug(this.dataset.bid)">حل‌شده</button>` : ''}
        </div>`;
      }).join('');
  } catch (e) {
    const el = id('adminBugList');
    if (el) el.innerHTML = `<p style="color:var(--er)">${e.message}</p>`;
  }
}

async function resolveBug(bid) {
  await api(`/bugs/${bid}?status=resolved`, 'PATCH');
  loadAdminBugs();
}

// ── Support ──────────────────────────────────────────────────
async function loadAdminSup() {
  try {
    const d = await api('/support');
    const el = id('adminSupList');
    if (!el) return;
    if (!d.tickets || !d.tickets.length) {
      el.innerHTML = '<p style="color:var(--mu);text-align:center">هیچ تیکتی وجود ندارد</p>';
      return;
    }
    el.innerHTML = d.tickets.map(t => {
      const safeId = esc(t.id);
      return `
      <div class="acard">
        <div class="acard-h"><div class="acard-t">${esc(t.subject)}</div><span class="abadge ${t.status}">${slbl(t.status)}</span></div>
        <div class="ameta">${esc(t.username)} - ${t.messages.length} پیام - ${new Date(t.created_at).toLocaleDateString('fa-IR')}</div>
        <button class="abtn ac" data-tid="${safeId}" onclick="window._adminReplyTicket(this.dataset.tid)">پاسخ</button>
        ${t.status !== 'closed' ? `<button class="abtn er" data-tid="${safeId}" onclick="window._adminCloseT(this.dataset.tid)">بستن</button>` : ''}
      </div>`;
    }).join('');
  } catch (e) { /* ignore */ }
}

async function adminReplyTicket(tid) {
  closeAdmin();
  await openTicket(tid);
}

async function adminCloseT(tid) {
  await api(`/support/${tid}/close`, 'PATCH');
  toast('تیکت بسته شد', 'ok');
  loadAdminSup();
}

// ── Users ────────────────────────────────────────────────────
async function loadAdminUsers() {
  try {
    const d = await api('/admin/users');
    const tbody = id('usersTbody');
    if (!tbody) return;
    tbody.innerHTML = d.users.map(u => {
      const safeUn = esc(u.username);
      return `
      <tr>
        <td>${safeUn}</td>
        <td><span class="rtag ${u.role === 'admin' ? 'a' : 'u'}">${u.role === 'admin' ? 'ادمین' : 'کاربر'}</span></td>
        <td>${u.created_at ? new Date(u.created_at).toLocaleDateString('fa-IR') : '—'}</td>
        <td>${u.username !== 'admin' ? `<button class="abtn er" data-uname="${safeUn}" onclick="window._delUser(this.dataset.uname)">حذف</button>` : '—'}</td>
      </tr>`;
    }).join('');
  } catch (e) { /* ignore */ }
}

export async function createUser() {
  const un = v('unew'), pw = v('pnew'), rl = id('rnew').value;
  if (!un || !pw) { toast('نام کاربری و رمز الزامی است', 'er'); return; }
  try {
    await api('/admin/users', 'POST', { username: un, password: pw, role: rl });
    toast('کاربر ایجاد شد', 'ok');
    id('unew').value = '';
    id('pnew').value = '';
    loadAdminUsers();
  } catch (e) { toast(e.message, 'er'); }
}

async function delUser(un) {
  if (!confirm(`حذف کاربر "${un}"؟`)) return;
  try {
    await api(`/admin/users/${un}`, 'DELETE');
    toast('حذف شد', 'ok');
    loadAdminUsers();
  } catch (e) { toast(e.message, 'er'); }
}

// ── Settings ─────────────────────────────────────────────────
async function loadAdminSettings() {
  try {
    const s = await api('/admin/settings');
    id('sSiteTitle').value = s.site_title || '';
    id('sSiteSub').value = s.site_subtitle || '';
    id('sWelcome').value = s.welcome_text || '';
    id('sPrimary').value = s.primary_color || '#7c6af7';
    id('sGold').value = s.gold_color || '#e8c97a';
    prevColor('sPrimary', 'cpPrimary');
    prevColor('sGold', 'cpGold');
  } catch (e) { /* ignore */ }
}

export function prevColor(inp, prev) {
  const c = id(inp).value.trim();
  if (/^#[0-9a-fA-F]{6}$/.test(c)) id(prev).style.background = c;
}

export async function saveSettings() {
  const s = {
    site_title: v('sSiteTitle'), site_subtitle: v('sSiteSub'),
    welcome_text: v('sWelcome'),
    primary_color: v('sPrimary'), gold_color: v('sGold'),
  };
  try {
    await api('/admin/settings', 'PUT', { settings: s });
    toast('تنظیمات ذخیره شد', 'ok');
    // refresh public settings
    const event = new CustomEvent('refreshSettings');
    window.dispatchEvent(event);
  } catch (e) { toast(e.message, 'er'); }
}

// ── Logs ─────────────────────────────────────────────────────
async function loadAdminLogs() {
  const el = id('apLogs');
  if (!el) return;
  try {
    const d = await api('/admin/logs?lines=50&level=error');
    if (!d.logs || !d.logs.length) {
      el.innerHTML = '<p style="color:var(--mu);text-align:center">هیچ لاگی وجود ندارد</p>';
      return;
    }
    el.innerHTML = `<div style="background:var(--bg);border-radius:8px;padding:10px;font-size:11px;font-family:monospace;direction:ltr;text-align:left;max-height:400px;overflow-y:auto;white-space:pre-wrap;color:var(--mu)">${d.logs.map(l => esc(l)).join('')}</div>`;
  } catch (e) {
    el.innerHTML = `<p style="color:var(--er)">${e.message}</p>`;
  }
}

// Global handlers for onclick in HTML
window._resolveBug = resolveBug;
window._adminReplyTicket = adminReplyTicket;
window._adminCloseT = adminCloseT;
window._delUser = delUser;
