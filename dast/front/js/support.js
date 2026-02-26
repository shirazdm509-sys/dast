/* support.js - مدیریت تیکت‌ها و پشتیبانی */

import { id, v, esc, toast } from './utils.js';
import { api, role } from './api.js';

let curTid = null;

export function slbl(s) {
  return { open: 'باز', answered: 'پاسخ داده شده', closed: 'بسته' }[s] || s;
}

export async function loadTickets() {
  try {
    const d = await api('/support');
    const list = id('ticketList');
    if (!list) return;
    if (!d.tickets || !d.tickets.length) {
      list.innerHTML = '<p style="font-size:11px;color:var(--mu);text-align:center;padding:10px 0">هیچ تیکتی ندارید</p>';
      return;
    }
    list.innerHTML = d.tickets.map(t => {
      const safeId = esc(t.id);
      return `
      <div class="tkt" data-tid="${safeId}" onclick="window._openTicket(this.dataset.tid)">
        <div class="tkt-sub">
          <span class="tbadge ${t.status}">${slbl(t.status)}</span>${esc(t.subject)}
        </div>
        <div class="tkt-meta">${new Date(t.created_at).toLocaleDateString('fa-IR')} - ${t.messages.length} پیام</div>
      </div>`;
    }).join('');
  } catch (e) { /* ignore */ }
}

export function openNewTicket() {
  curTid = null;
  id('tkTitle').textContent = 'تیکت جدید';
  id('tkNewForm').style.display = 'block';
  id('tkChat').style.display = 'none';
  id('ticketModal').classList.add('open');
}

export async function sendNewTicket() {
  const sub = v('tkSubject'), msg = v('tkMsg');
  if (!sub || !msg) { toast('موضوع و پیام الزامی است', 'er'); return; }
  try {
    await api('/support', 'POST', { subject: sub, message: msg });
    id('ticketModal').classList.remove('open');
    toast('تیکت ارسال شد', 'ok');
    loadTickets();
  } catch (e) { toast(e.message, 'er'); }
}

export async function openTicket(tid) {
  curTid = tid;
  try {
    const t = await api(`/support/${tid}`);
    id('tkTitle').textContent = esc(t.subject);
    id('tkNewForm').style.display = 'none';
    id('tkChat').style.display = 'block';
    id('tkCloseBtn').style.display = (role === 'admin' && t.status !== 'closed') ? 'block' : 'none';
    id('tkMsgs').innerHTML = t.messages.map(m => `
      <div class="smsg ${m.role === 'admin' ? 'admin' : 'user'}">
        <div class="who">${m.role === 'admin' ? 'ادمین' : esc(m.from)} - ${new Date(m.at).toLocaleDateString('fa-IR')}</div>
        ${esc(m.text)}
      </div>`).join('');
    id('ticketModal').classList.add('open');
  } catch (e) { toast(e.message, 'er'); }
}

export async function sendReply() {
  const txt = v('tkReply');
  if (!txt || !curTid) return;
  try {
    await api(`/support/${curTid}/reply`, 'POST', { message: txt });
    id('tkReply').value = '';
    openTicket(curTid);
    loadTickets();
  } catch (e) { toast(e.message, 'er'); }
}

export async function closeTicketStatus() {
  if (!curTid) return;
  await api(`/support/${curTid}/close`, 'PATCH');
  id('ticketModal').classList.remove('open');
  loadTickets();
}

export function closeTicketModal() {
  id('ticketModal').classList.remove('open');
}

export function getCurTid() { return curTid; }

// Register global event listener
window.addEventListener('loadTickets', loadTickets);
// Global handler for onclick in HTML
window._openTicket = openTicket;
