/* sidebar.js - مدیریت sidebar و فایل‌ها */

import { id, esc } from './utils.js';
import { api } from './api.js';

export function toggleSB() {
  const sb = id('sb'), isMob = window.innerWidth <= 768;
  const open = sb.classList.toggle('open');
  if (isMob) {
    const ov = id('mobOverlay');
    ov.style.display = open ? 'block' : 'none';
  }
}

export function closeSB() {
  id('sb').classList.remove('open');
  id('mobOverlay').style.display = 'none';
}

export function stab(name) {
  document.querySelectorAll('.stab').forEach((t, i) => {
    t.classList.toggle('on', ['bug', 'sup'][i] === name);
  });
  ['tbug', 'tsup'].forEach(x => id(x).classList.remove('on'));
  id('t' + name).classList.add('on');
  if (name === 'sup') {
    // loadTickets will be called from support.js
    const event = new CustomEvent('loadTickets');
    window.dispatchEvent(event);
  }
}

export async function loadFiles() {
  try {
    const [d, st] = await Promise.all([api('/files'), api('/stats')]);
    const stChunks = id('stChunks');
    const stFiles = id('stFiles');
    const list = id('fileList');
    if (stChunks) stChunks.textContent = st.total_chunks || 0;
    if (stFiles) stFiles.textContent = st.total_files || 0;
    if (!list) return;
    if (!d.files || !d.files.length) {
      list.innerHTML = '<p style="font-size:11px;color:var(--mu);text-align:center;padding:10px 0">هیچ فایلی یافت نشد</p>';
      return;
    }
    list.innerHTML = d.files.map(f => `
      <div class="fitem">
        <span style="font-size:18px">${f.filename.endsWith('.pdf') ? '&#128196;' : '&#128221;'}</span>
        <div class="finfo">
          <div class="fname">${esc(f.filename)}</div>
          <div class="fmeta">${f.chunks} بخش</div>
        </div>
      </div>`).join('');
  } catch (e) { /* ignore */ }
}
