// static/js/script.js

const LS_KEYS = {
  speechmatics: 'speechmaticsApiKey',
  gemini: 'geminiApiKey',
};

function setStatus(msg, type = 'info') {
  const box = document.getElementById('statusBox');
  if (!box) return;
  box.innerHTML = `<div class="status ${type}">${msg}</div>`;
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.innerText = text ?? '';
  return div.innerHTML;
}

function loadApiKeys() {
  const sm = localStorage.getItem(LS_KEYS.speechmatics) || '';
  const gm = localStorage.getItem(LS_KEYS.gemini) || '';
  const smInput = document.getElementById('speechmaticsApiKey');
  const gmInput = document.getElementById('geminiApiKey');
  if (smInput) smInput.value = sm;
  if (gmInput) gmInput.value = gm;
}
function setupKeyAutosave() {
  const smInput = document.getElementById('speechmaticsApiKey');
  const gmInput = document.getElementById('geminiApiKey');
  if (smInput) {
    smInput.addEventListener('change', () => localStorage.setItem(LS_KEYS.speechmatics, smInput.value.trim()));
  }
  if (gmInput) {
    gmInput.addEventListener('change', () => localStorage.setItem(LS_KEYS.gemini, gmInput.value.trim()));
  }
}

let currentJobId = null;
let statusInterval = null;
let currentVideoUrl = '';

async function startTranscription() {
  try {
    const urlInput = document.getElementById('videoUrl');
    const langSel = document.getElementById('language');
    const smInput = document.getElementById('speechmaticsApiKey');
    const activeService = document.getElementById('activeService').value;

    const page_url = (urlInput?.value || '').trim();
    currentVideoUrl = page_url;
    const language = (langSel?.value || '').trim();
    const apiKey = smInput ? (smInput.value || '').trim() : '';

    if (!page_url) { setStatus('Kérlek add meg a videó URL-jét!', 'warn'); return; }
    if (activeService === 'speechmatics' && !apiKey) { setStatus('Kérlek add meg a Speechmatics API kulcsot!', 'warn'); return; }
    if (!language) { setStatus('Válaszd ki a videó nyelvét!', 'warn'); return; }

    setStatus('Feldolgozás indítása... Ez több percig is eltarthat.', 'info');

    const res = await fetch('/process-page-url', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ page_url, apiKey: activeService === 'speechmatics' ? apiKey : null, language }),
    });
    
    const data = await res.json();
    if (!res.ok) throw new Error(data?.error || 'Ismeretlen hiba.');

    document.getElementById('srtText').value = '';
    document.getElementById('translatedText').value = '';

    if (data.service === 'whisper' && data.status === 'done') {
      const srtEditor = document.getElementById('srtText');
      if (srtEditor) srtEditor.value = data.srt_content || '';
      setStatus(`Átírás kész (${escapeHtml(data.video_title)})!`, 'success');
      return;
    }

    currentJobId = data.job_id;
    setStatus(`Feladat elküldve (${escapeHtml(data.video_title)}). Állapot lekérdezése...`, 'info');
    beginStatusPolling();

  } catch (err) {
    setStatus('Hiba: ' + escapeHtml(err.message || String(err)), 'error');
  }
}

function beginStatusPolling() {
  clearInterval(statusInterval);
  statusInterval = setInterval(checkTranscriptionStatus, 5000);
}

async function checkTranscriptionStatus() {
  if (!currentJobId) { clearInterval(statusInterval); return; }
  try {
    const smInput = document.getElementById('speechmaticsApiKey');
    const apiKey = (smInput?.value || '').trim();
    if (!apiKey) throw new Error('Hiányzik a Speechmatics API kulcs a státusz lekérdezéshez.');

    const res = await fetch(`/transcription-status/${encodeURIComponent(currentJobId)}?apiKey=${encodeURIComponent(apiKey)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data?.error || 'Ismeretlen hiba.');

    const status = data.status;
    setStatus(`Átírás állapota: ${escapeHtml(status)}`, 'info');

    if (status === 'done') {
      clearInterval(statusInterval);
      const srtEditor = document.getElementById('srtText');
      if (srtEditor) srtEditor.value = data.srt_content || '';
      setStatus('Átírás kész!', 'success');
    } else if (status === 'error' || status === 'rejected') {
      clearInterval(statusInterval);
      throw new Error(data?.error || 'A feladat sikertelen.');
    }
  } catch (err) {
    clearInterval(statusInterval);
    setStatus('Hiba a státusz lekérdezésekor: ' + escapeHtml(err.message || String(err)), 'error');
  }
}

async function downloadSrt() {
  try {
    const srtEditor = document.getElementById('translatedText');
    const srtText = srtEditor?.value || '';
    if (!srtText.trim()) { setStatus('Nincs letölthető lefordított tartalom.', 'warn'); return; }
    const res = await fetch('/download-srt', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ srtText }),
    });
    if (!res.ok) throw new Error((await res.json()).error || 'Letöltési hiba.');
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'subtitle.srt';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    setStatus('SRT letöltve.', 'success');
  } catch (err) {
    setStatus('Hiba SRT letöltéskor: ' + escapeHtml(err.message || String(err)), 'error');
  }
}

async function uploadToDrive() {
  try {
    const srtEditor = document.getElementById('translatedText');
    const srtText = srtEditor?.value || '';
    if (!srtText.trim()) { setStatus('Nincs feltölthető lefordított tartalom.', 'warn'); return; }
    const res = await fetch('/upload-to-drive', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ srtText }),
    });
    const data = await res.json();
    if (!res.ok || !data?.success) throw new Error(data?.error || 'Feltöltési hiba.');
    setStatus('SRT feltöltve a Google Drive-ra.', 'success');
  } catch (err) {
    setStatus('Hiba Drive feltöltéskor: ' + escapeHtml(err.message || String(err)), 'error');
  }
}

async function translateSrt() {
  try {
    const srtEditor = document.getElementById('srtText');
    const translatedText = document.getElementById('translatedText');
    const geminiInput = document.getElementById('geminiApiKey');

    const srt = srtEditor?.value || '';
    const geminiKey = (geminiInput?.value || '').trim();

    if (!srt.trim()) { setStatus('Nincs lefordítható SRT tartalom.', 'warn'); return; }
    if (!geminiKey) { setStatus('Kérlek add meg a Gemini API kulcsot!', 'warn'); return; }

    setStatus('Fordítás folyamatban...', 'info');

    const fd = new FormData();
    fd.append('srtText', srt);
    fd.append('geminiApiKey', geminiKey);

    const res = await fetch('/translate', { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.error || 'Fordítási hiba.');
    if (translatedText) translatedText.value = data.translated_text || '';
    setStatus('Fordítás kész.', 'success');
  } catch (err) {
    setStatus('Hiba fordítás közben: ' + escapeHtml(err.message || String(err)), 'error');
  }
}

async function downloadVideo() {
  if (!currentVideoUrl) { setStatus('Előbb indíts el egy átiratot!', 'warn'); return; }
  
  const resolutionSelect = document.getElementById('resolution');
  const resolution = resolutionSelect.value;
  setStatus(`Videó letöltésének előkészítése ${resolution}p felbontásban...`, 'info');
  
  window.open(`/download-video?page_url=${encodeURIComponent(currentVideoUrl)}&resolution=${encodeURIComponent(resolution)}`, '_blank');
}

window.startTranscription = startTranscription;
window.downloadSrt = downloadSrt;
window.uploadToDrive = uploadToDrive;
window.translateSrt = translateSrt;
window.downloadVideo = downloadVideo;

document.addEventListener('DOMContentLoaded', () => {
  loadApiKeys();
  setupKeyAutosave();
  setStatus('Készen állok.', 'info');
});
