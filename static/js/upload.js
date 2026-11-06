const drop = document.getElementById('drop');
const input = document.getElementById('file');
const err = document.getElementById('error');
const title = document.getElementById('dropTitle');

async function send(file) {
  err.textContent = '';
  if (!file) return;
  if (file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) { err.textContent = 'Only PDF files are allowed.'; return; }
  if (file.size > 10 * 1024 * 1024) { err.textContent = 'File is larger than 10 MB.'; return; }
  drop.classList.add('busy');
  title.textContent = 'Uploading ' + file.name + '…';
  const fd = new FormData();
  fd.append('pdf', file);
  try {
    const res = await fetch('/upload', { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error);
    window.location.href = '/ask/' + data.id;
  } catch (e) {
    err.textContent = e.message || 'Upload failed. Try again.';
    drop.classList.remove('busy');
    title.textContent = 'Drop your notes here, or click to choose';
  }
}

drop.addEventListener('click', () => input.click());
drop.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') input.click(); });
input.addEventListener('change', () => send(input.files[0]));
['dragenter', 'dragover'].forEach(t => drop.addEventListener(t, e => { e.preventDefault(); drop.classList.add('over'); }));
['dragleave', 'drop'].forEach(t => drop.addEventListener(t, e => { e.preventDefault(); drop.classList.remove('over'); }));
drop.addEventListener('drop', e => send(e.dataTransfer.files[0]));
