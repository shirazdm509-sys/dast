/* admin-app.js - اپلیکیشن پنل مدیریت */

const API = 'https://ai.dastgheibqoba.info/api';
const token = localStorage.getItem('tk');
const role = localStorage.getItem('rl');

// بررسی دسترسی ادمین
if (!token || role !== 'admin') {
  alert('فقط ادمین دسترسی دارد');
  window.location.href = '/';
}

function esc(t) {
  return (t || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
    .replace(/\n/g, '<br>');
}

async function api(path, method = 'GET', body = null) {
  const opts = { method, headers: { 'Authorization': `Bearer ${token}` } };
  if (body) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(API + path, opts);
  if (r.status === 401) { localStorage.clear(); window.location.href = '/'; return; }
  if (r.status === 403) { alert('دسترسی ندارید'); return; }
  const d = await r.json();
  if (!r.ok) throw new Error(d.detail || 'خطا');
  return d;
}

function showToast(msg) {
  const t = document.createElement('div');
  t.style.cssText = 'position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:var(--s2);border:1px solid var(--ok);color:var(--ok);padding:8px 20px;border-radius:25px;font-size:13px;z-index:999;';
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3000);
}

// ── Section Navigation ──────────────────────────────────────
window.showSection = function(name) {
  document.querySelectorAll('.admin-section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('sec-' + name)?.classList.add('active');
  event.target.classList.add('active');

  const loaders = {
    dashboard: loadDashboard,
    bugs: loadBugs,
    tickets: loadTickets,
    users: loadUsers,
    settings: loadSettings,
    logs: () => loadLogs('all'),
    broadcast: loadBroadcastHistory,
  };
  loaders[name]?.();
};

// ── Dashboard ───────────────────────────────────────────────
async function loadDashboard() {
  const el = document.getElementById('dashContent');
  try {
    const d = await api('/admin/analytics');
    let html = `
      <div class="dash-grid">
        <div class="dash-card"><div class="num">${d.total_users}</div><div class="lbl">کاربران</div></div>
        <div class="dash-card"><div class="num">${d.questions_today}</div><div class="lbl">سوالات امروز</div></div>
        <div class="dash-card"><div class="num">${d.questions_total}</div><div class="lbl">کل سوالات</div></div>
        <div class="dash-card"><div class="num">${d.open_bugs}</div><div class="lbl">باگ باز</div></div>
        <div class="dash-card"><div class="num">${d.open_tickets}</div><div class="lbl">تیکت باز</div></div>
        <div class="dash-card"><div class="num">${d.total_bugs}</div><div class="lbl">کل باگ‌ها</div></div>
      </div>`;

    // Chart
    if (d.daily_questions && Object.keys(d.daily_questions).length) {
      const entries = Object.entries(d.daily_questions);
      const max = Math.max(...entries.map(e => e[1]), 1);
      html += `<div class="chart-container"><h3>سوالات 7 روز اخیر</h3><div class="chart-bars">`;
      for (const [date, count] of entries) {
        const h = Math.max((count / max) * 80, 2);
        html += `<div class="bar-col">
          <div style="height:80px;display:flex;align-items:flex-end;justify-content:center">
            <div class="bar" style="height:${h}px"></div>
          </div>
          <div class="bar-date">${date.slice(5)}</div>
          <div class="bar-count">${count}</div>
        </div>`;
      }
      html += `</div></div>`;
    }

    // Keywords
    if (d.top_keywords && Object.keys(d.top_keywords).length) {
      html += `<div class="chart-container"><h3>کلمات پرتکرار</h3><div class="keywords-wrap">`;
      for (const [word, count] of Object.entries(d.top_keywords)) {
        html += `<span class="kw-tag">${esc(word)} (${count})</span>`;
      }
      html += `</div></div>`;
    }

    el.innerHTML = html;
  } catch (e) { el.innerHTML = `<p style="color:var(--er)">${e.message}</p>`; }
}

// ── Bugs ─────────────────────────────────────────────────────
async function loadBugs() {
  const el = document.getElementById('bugsContent');
  try {
    const d = await api('/bugs');
    if (!d.bugs?.length) { el.innerHTML = '<p style="color:var(--mu)">هیچ گزارشی نیست</p>'; return; }
    el.innerHTML = `<p style="font-size:12px;color:var(--mu);margin-bottom:12px">مجموع: ${d.total} | باز: ${d.open}</p>` +
      d.bugs.map(b => `
        <div class="admin-card">
          <div class="card-header">
            <div class="card-title">${esc(b.title)}</div>
            <span class="badge ${b.status}">${b.status === 'open' ? 'باز' : 'حل‌شده'}</span>
          </div>
          <div class="card-meta">${esc(b.username)} - ${new Date(b.created_at).toLocaleDateString('fa-IR')}</div>
          <div class="card-body">${esc(b.description)}</div>
          ${b.question ? `<div style="font-size:11px;color:var(--mu);background:var(--s3);padding:8px;border-radius:7px;margin-top:8px">${esc(b.question)}</div>` : ''}
          ${b.status === 'open' ? `<button class="action-btn green" data-id="${esc(b.id)}" onclick="resolveBug(this.dataset.id)">حل‌شده</button>` : ''}
        </div>`).join('');
  } catch (e) { el.innerHTML = `<p style="color:var(--er)">${e.message}</p>`; }
}

window.resolveBug = async function(bid) {
  await api(`/bugs/${bid}?status=resolved`, 'PATCH');
  showToast('باگ حل شد');
  loadBugs();
};

// ── Tickets ──────────────────────────────────────────────────
async function loadTickets() {
  const el = document.getElementById('ticketsContent');
  try {
    const d = await api('/support');
    if (!d.tickets?.length) { el.innerHTML = '<p style="color:var(--mu)">هیچ تیکتی نیست</p>'; return; }
    const statusLabel = { open: 'باز', answered: 'پاسخ داده شده', closed: 'بسته' };
    el.innerHTML = d.tickets.map(t => `
      <div class="admin-card">
        <div class="card-header">
          <div class="card-title">${esc(t.subject)}</div>
          <span class="badge ${t.status}">${statusLabel[t.status] || t.status}</span>
        </div>
        <div class="card-meta">${esc(t.username)} - ${t.messages.length} پیام - ${new Date(t.created_at).toLocaleDateString('fa-IR')}</div>
        <div class="card-body" style="max-height:100px;overflow:hidden">${esc(t.messages[t.messages.length-1]?.text || '')}</div>
        <button class="action-btn purple" data-id="${esc(t.id)}" onclick="viewTicket(this.dataset.id)">مشاهده</button>
        ${t.status !== 'closed' ? `<button class="action-btn red" data-id="${esc(t.id)}" onclick="closeTicket(this.dataset.id)">بستن</button>` : ''}
      </div>`).join('');
  } catch (e) { el.innerHTML = `<p style="color:var(--er)">${e.message}</p>`; }
}

window.viewTicket = async function(tid) {
  try {
    const t = await api(`/support/${tid}`);
    const el = document.getElementById('ticketsContent');
    el.innerHTML = `
      <button class="action-btn purple" onclick="loadTickets()" style="margin-bottom:12px">بازگشت به لیست</button>
      <h3 style="font-size:14px;margin-bottom:12px">${esc(t.subject)}</h3>
      <div style="display:flex;flex-direction:column;gap:8px;margin-bottom:12px">
        ${t.messages.map(m => `
          <div style="padding:10px 14px;border-radius:10px;font-size:13px;line-height:1.7;max-width:88%;white-space:pre-wrap;
            ${m.role === 'admin' ? 'background:rgba(124,106,247,.1);border:1px solid rgba(124,106,247,.3);align-self:flex-end' : 'background:var(--s3);border:1px solid var(--br);align-self:flex-start'}">
            <div style="font-size:10px;color:var(--mu);margin-bottom:4px">${m.role === 'admin' ? 'ادمین' : esc(m.from)} - ${new Date(m.at).toLocaleDateString('fa-IR')}</div>
            ${esc(m.text)}
          </div>`).join('')}
      </div>
      <div style="display:flex;gap:8px">
        <textarea id="ticketReply" rows="3" placeholder="پاسخ..." style="flex:1;background:var(--s2);border:1px solid var(--br);border-radius:9px;color:var(--tx);font-family:'Vazirmatn',sans-serif;font-size:13px;padding:10px;outline:none;resize:none"></textarea>
        <button class="action-btn purple" data-id="${esc(t.id)}" onclick="replyTicket(this.dataset.id)" style="align-self:flex-end;padding:10px 20px">ارسال</button>
      </div>`;
  } catch (e) { alert(e.message); }
};

window.replyTicket = async function(tid) {
  const txt = document.getElementById('ticketReply')?.value?.trim();
  if (!txt) return;
  await api(`/support/${tid}/reply`, 'POST', { message: txt });
  showToast('پاسخ ارسال شد');
  viewTicket(tid);
};

window.closeTicket = async function(tid) {
  if (!confirm('بستن این تیکت؟')) return;
  await api(`/support/${tid}/close`, 'PATCH');
  showToast('تیکت بسته شد');
  loadTickets();
};

// ── Users ────────────────────────────────────────────────────
async function loadUsers() {
  const el = document.getElementById('usersContent');
  try {
    const d = await api('/admin/users');
    el.innerHTML = `<table class="users-table">
      <thead><tr><th>کاربری</th><th>نقش</th><th>تاریخ</th><th>عملیات</th></tr></thead>
      <tbody>${d.users.map(u => `
        <tr>
          <td>${esc(u.username)}</td>
          <td><span class="badge" style="background:${u.role === 'admin' ? 'var(--gold);color:#1a1200' : 'var(--s3);color:var(--mu)'}">${u.role === 'admin' ? 'ادمین' : 'کاربر'}</span></td>
          <td>${u.created_at ? new Date(u.created_at).toLocaleDateString('fa-IR') : '—'}</td>
          <td>${u.username !== 'admin' ? `<button class="action-btn red" data-uname="${esc(u.username)}" onclick="deleteUser(this.dataset.uname)">حذف</button>` : '—'}</td>
        </tr>`).join('')}</tbody>
    </table>`;
  } catch (e) { el.innerHTML = `<p style="color:var(--er)">${e.message}</p>`; }
}

window.addUser = async function() {
  const un = document.getElementById('newUser')?.value?.trim();
  const pw = document.getElementById('newPass')?.value?.trim();
  const rl = document.getElementById('newRole')?.value;
  if (!un || !pw) { alert('نام کاربری و رمز الزامی است'); return; }
  try {
    await api('/admin/users', 'POST', { username: un, password: pw, role: rl });
    showToast('کاربر ایجاد شد');
    document.getElementById('newUser').value = '';
    document.getElementById('newPass').value = '';
    loadUsers();
  } catch (e) { alert(e.message); }
};

window.deleteUser = async function(uname) {
  if (!confirm(`حذف کاربر "${uname}"؟`)) return;
  try {
    await api(`/admin/users/${uname}`, 'DELETE');
    showToast('حذف شد');
    loadUsers();
  } catch (e) { alert(e.message); }
};

// ── Settings ─────────────────────────────────────────────────
async function loadSettings() {
  const el = document.getElementById('settingsContent');
  try {
    const s = await api('/admin/settings');
    el.innerHTML = `
      <div class="settings-row"><label>عنوان سایت</label><input id="sTitle" value="${esc(s.site_title || '')}"/></div>
      <div class="settings-row"><label>زیرعنوان</label><input id="sSub" value="${esc(s.site_subtitle || '')}"/></div>
      <div class="settings-row"><label>متن خوش‌آمدگویی</label><input id="sWelcome" value="${esc(s.welcome_text || '')}"/></div>
      <div class="settings-row">
        <label>رنگ اصلی <span class="color-preview" id="cp1" style="background:${s.primary_color || '#7c6af7'}"></span></label>
        <input id="sColor1" value="${s.primary_color || '#7c6af7'}" oninput="document.getElementById('cp1').style.background=this.value"/>
      </div>
      <div class="settings-row">
        <label>رنگ طلایی <span class="color-preview" id="cp2" style="background:${s.gold_color || '#e8c97a'}"></span></label>
        <input id="sColor2" value="${s.gold_color || '#e8c97a'}" oninput="document.getElementById('cp2').style.background=this.value"/>
      </div>
      <button class="save-btn" onclick="saveSettings()">ذخیره تنظیمات</button>`;
  } catch (e) { el.innerHTML = `<p style="color:var(--er)">${e.message}</p>`; }
}

window.saveSettings = async function() {
  const settings = {
    site_title: document.getElementById('sTitle')?.value,
    site_subtitle: document.getElementById('sSub')?.value,
    welcome_text: document.getElementById('sWelcome')?.value,
    primary_color: document.getElementById('sColor1')?.value,
    gold_color: document.getElementById('sColor2')?.value,
  };
  try {
    await api('/admin/settings', 'PUT', { settings });
    showToast('تنظیمات ذخیره شد');
  } catch (e) { alert(e.message); }
};

// ── Broadcast ────────────────────────────────────────────────
window.sendBroadcast = async function() {
  const title = document.getElementById('bcTitle')?.value?.trim() || '';
  const message = document.getElementById('bcMessage')?.value?.trim();
  if (!message) { alert('متن پیام الزامی است'); return; }
  try {
    await api('/admin/broadcast', 'POST', { title, message });
    showToast('پیام ارسال شد');
    document.getElementById('bcTitle').value = '';
    document.getElementById('bcMessage').value = '';
    loadBroadcastHistory();
  } catch (e) { alert(e.message); }
};

async function loadBroadcastHistory() {
  const el = document.getElementById('broadcastHistory');
  if (!el) return;
  try {
    const b = await api('/broadcast/latest');
    if (!b) { el.innerHTML = '<p style="color:var(--mu)">هیچ پیامی ارسال نشده</p>'; return; }
    el.innerHTML = `<div class="admin-card">
      <div class="card-header"><div class="card-title">${esc(b.title || 'بدون عنوان')}</div></div>
      <div class="card-meta">${new Date(b.created_at).toLocaleDateString('fa-IR')}</div>
      <div class="card-body">${esc(b.message)}</div>
    </div>`;
  } catch (e) { /* ignore */ }
}

// ── Logs ─────────────────────────────────────────────────────
window.loadLogs = async function(level = 'all') {
  const el = document.getElementById('logsContent');
  try {
    const d = await api(`/admin/logs?lines=100&level=${level}`);
    if (!d.logs?.length) { el.innerHTML = '<p style="color:var(--mu)">لاگی وجود ندارد</p>'; return; }
    el.innerHTML = `<div class="log-viewer">${d.logs.map(l => esc(l)).join('')}</div>`;
  } catch (e) { el.innerHTML = `<p style="color:var(--er)">${e.message}</p>`; }
};

// ── Initial Load ────────────────────────────────────────────
loadDashboard();
