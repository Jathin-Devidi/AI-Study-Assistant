const thread = document.getElementById('thread');
const q = document.getElementById('q');
const send = document.getElementById('send');
const docId = thread.dataset.doc;
const statusChip = document.getElementById('status');

function add(cls, text) {
  const el = document.createElement('div');
  el.className = 'msg ' + cls;
  const t = document.createElement('div');
  t.className = 'text';
  t.textContent = text;
  el.appendChild(t);
  thread.appendChild(el);
  el.scrollIntoView({ behavior: 'smooth', block: 'end' });
  return el;
}

function enable() { q.disabled = false; send.disabled = false; q.focus(); }

async function ask() {
  const question = q.value.trim();
  if (!question) return;
  document.getElementById('empty')?.remove();
  q.value = ''; q.disabled = true; send.disabled = true;
  const qEl = add('q', question);
  qEl.textContent = question;
  const pending = add('a pending', 'Searching your notes…');
  try {
    const res = await fetch('/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ documentId: docId, question }) });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error);
    pending.classList.remove('pending');
    pending.querySelector('.text').textContent = data.answer;
    if (data.found && data.sources.length) {
      const tabs = document.createElement('div');
      tabs.className = 'tabs';
      data.sources.forEach(p => { const s = document.createElement('span'); s.className = 'tab'; s.textContent = 'p. ' + p; tabs.appendChild(s); });
      pending.appendChild(tabs);
    }
  } catch (e) {
    pending.classList.remove('pending'); pending.classList.add('err');
    pending.querySelector('.text').textContent = e.message;
  }
  enable();
}

send.addEventListener('click', ask);
q.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask(); } });

// Poll while the document is still being processed
if (thread.dataset.status === 'processing') {
  const timer = setInterval(async () => {
    const r = await fetch(`/api/documents/${docId}/status`);
    const d = await r.json();
    if (d.status !== 'processing') {
      clearInterval(timer);
      statusChip.textContent = d.status;
      statusChip.className = 'chip ' + d.status;
      document.getElementById('processing').hidden = true;
      if (d.status === 'ready') { const n = document.createElement('div'); n.className = 'notice'; n.id = 'empty'; n.textContent = 'Ready. Ask anything the document covers.'; thread.appendChild(n); enable(); }
      else { const n = document.createElement('div'); n.className = 'notice error-box'; n.textContent = 'Reading failed: ' + d.error; thread.appendChild(n); }
    }
  }, 2000);
}
thread.lastElementChild?.scrollIntoView();
