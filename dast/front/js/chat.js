/* chat.js - مدیریت چت و ارسال پیام */

import { id, v, esc, toast, resize } from './utils.js';
import { API, token } from './api.js';

let busy = false;
let sid = null;

// session_id ثابت برای حافظه مکالمه
let sessionId = localStorage.getItem('session_id');
if (!sessionId) {
  sessionId = Date.now().toString(36) + Math.random().toString(36).slice(2);
  localStorage.setItem('session_id', sessionId);
}

export function onKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMsg();
  }
}

export function resizeInput(el) {
  resize(el);
}

export async function sendMsg() {
  const q = v('qi').trim();
  if (!q || busy) return;
  busy = true;
  id('bsend').disabled = true;
  id('bstop').style.display = 'flex';
  id('qi').value = '';
  id('qi').style.height = 'auto';

  const msgs = id('msgs');
  id('welcomeEl')?.remove();

  // پاکسازی ID‌های فعال قبلی (رفع باگ crash)
  ['activeBwrap', 'activeBubble', 'activeSt'].forEach(activeId => {
    const el = id(activeId);
    if (el) el.removeAttribute('id');
  });

  // سوال کاربر
  const uDiv = document.createElement('div');
  uDiv.className = 'msg user';
  uDiv.innerHTML = `<div class="av">&#128100;</div><div class="bwrap"><div class="bubble">${esc(q)}</div></div>`;
  msgs.appendChild(uDiv);

  // bubble ربات
  const bDiv = document.createElement('div');
  bDiv.className = 'msg bot';
  bDiv.innerHTML = `
    <div class="av">&#129302;</div>
    <div class="bwrap" id="activeBwrap">
      <div class="stline" id="activeSt"><span class="sdot"></span>در حال تحلیل...</div>
      <div class="bubble" id="activeBubble" style="display:none"></div>
    </div>`;
  msgs.appendChild(bDiv);
  msgs.scrollTop = msgs.scrollHeight;

  sid = sessionId;
  let fullAns = '', sources = [], keywords = [], found = false;

  try {
    const r = await fetch(`${API}/ask`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: q, session_id: sid })
    });

    if (!r.ok) {
      const e = await r.json();
      const st = id('activeSt');
      if (st) st.remove();
      const b = id('activeBubble');
      if (b) {
        b.textContent = e.detail || 'خطا در سرور';
        b.classList.add('nf');
        b.style.display = 'block';
      }
      finish([], [], false);
      return;
    }

    const reader = r.body.getReader(), dec = new TextDecoder();

    outer: while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      for (const line of dec.decode(value).split('\n')) {
        if (!line.startsWith('data:')) continue;
        try {
          const chunk = JSON.parse(line.slice(5));
          if (chunk.type === 'status') {
            const st = id('activeSt');
            if (st) st.innerHTML = `<span class="sdot"></span>${esc(chunk.content)}`;
          } else if (chunk.type === 'answer') {
            const st = id('activeSt');
            if (st) st.remove();
            const b = id('activeBubble');
            if (b) {
              b.style.display = 'block';
              fullAns += chunk.content;
              b.textContent = fullAns;
              msgs.scrollTop = msgs.scrollHeight;
            }
          } else if (chunk.type === 'done') {
            sources = chunk.sources || [];
            keywords = chunk.keywords || [];
            found = chunk.found_in_docs || false;
            finish(sources, keywords, found);
            break outer;
          } else if (chunk.type === 'cancelled' || chunk.type === 'error') {
            if (chunk.content) {
              const b = id('activeBubble');
              if (b) { b.textContent = chunk.content; b.style.display = 'block'; }
            }
            finish([], [], false);
            break outer;
          }
        } catch (parseErr) { /* ignore parse errors */ }
      }
    }
  } catch (fetchErr) {
    const st = id('activeSt');
    if (st) st.remove();
    const b = id('activeBubble');
    if (b) {
      b.textContent = 'خطا در اتصال به سرور.';
      b.classList.add('nf');
      b.style.display = 'block';
    }
    finish([], [], false);
  }

  function finish(src, kws, fnd) {
    const bwrap = id('activeBwrap');
    if (bwrap) {
      if (kws.length) {
        const kd = document.createElement('div');
        kd.className = 'kwrap';
        kd.innerHTML = kws.map(k => `<span class="ktag">${esc(k)}</span>`).join('');
        const bubble = id('activeBubble');
        if (bubble) bwrap.insertBefore(kd, bubble);
      }
      if (src.length) {
        const sd = document.createElement('div');
        sd.className = 'swrap';
        sd.innerHTML = src.map(s =>
          `<span class="stag">${esc(s.label || 'مسئله ' + s.page)}${s.section ? ' - ' + esc(s.section.split(' > ')[0]) : ''}</span>`
        ).join('');
        bwrap.appendChild(sd);
      }
      const b = id('activeBubble');
      if (b && !fnd) b.classList.add('nf');

      // پاکسازی تمام ID‌های فعال
      bwrap.removeAttribute('id');
      if (b) b.removeAttribute('id');
      const stEl = id('activeSt');
      if (stEl) stEl.removeAttribute('id');
    }
    busy = false;
    id('bsend').disabled = false;
    id('bstop').style.display = 'none';
    id('qi')?.focus();
    sid = null;
  }
}

export async function stopStream() {
  if (sid) {
    try {
      await fetch(`${API}/ask/cancel/${sid}`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` }
      });
    } catch (e) { /* ignore */ }
    sid = null;
  }
}

export function clearChat() {
  const welcomeText = id('welcomeTxt')?.textContent || 'سوال فقهی خود را بپرسید.';
  id('msgs').innerHTML = `
    <div class="welcome" id="welcomeEl">
      <div class="wico">&#127807;</div>
      <h2>رساله آیت‌الله سید علی محمد دستغیب</h2>
      <p id="welcomeTxt">${esc(welcomeText)}</p>
    </div>`;

  // ریست session برای حافظه مکالمه
  sessionId = Date.now().toString(36) + Math.random().toString(36).slice(2);
  localStorage.setItem('session_id', sessionId);
}
