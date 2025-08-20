// static/js/script.js

// ====== LocalStorage kulcsok ======
const LS_KEYS = {
  speechmatics: 'speechmaticsApiKey',
  gemini: 'geminiApiKey',
};

// ====== Helper UI ======
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

// ====== API kulcsok: betöltés és mentés ======
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
    smInput.addEventListener('change', () => {
      localStorage.setItem(LS_KEYS.speechmatics, smInput.value.trim());
    });
    smInput.addEventListener('blur', () => {
      localStorage.setItem(LS_KEYS.speechmatics, smInput.value.trim());
    });
  }
  if (gmInput) {
    gmInput.addEventListener('change', () => {
      localStorage.setItem(LS_KEYS.gemini, gmInput.value.trim());
    });
    gmInput.addEventListener('blur', () => {
      localStorage.setItem(LS_KEYS.gemini, gmInput.value.trim());
    });
  }
}

// ====== Globális állapot ======
let currentJobId = null;
let statusInterval = null;

// ====== Átirat indítása ======
async function startTranscription() {
  try {
    const urlInput = document.getElementById('videoUrl');
    const langSel = document.getElementById('language');
    const smInput = document.getElementById('speechmaticsApiKey');

    const page_url = (urlInput?.value || '').trim();
    const language = (langSel?.value || '').trim();
    const apiKey = (smInput?.value || '').trim();

    if (!page_url) {
      setStatus('Kérlek add meg a videó URL-jét!', 'warn');
      return;
    }
    if (!apiKey) {
      setStatus('Kérlek add meg a Speechmatics API kulcsot!', 'warn');
      return;
    }
    if (!language) {
      setStatus('Válaszd ki a videó nyelvét!', 'warn');
      return;
    }

    setStatus('Közvetlen média link keresése és átirat indítása...', 'info');

    const res = await fetch('/process-page-url', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ page_url, apiKey, language }),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data?.error || 'Ismeretlen hiba a feldolgozásnál.');
    }

    currentJobId = data.job_id;
    setStatus(`Feladat elküldve (ID: ${escapeHtml(currentJobId)}). Állapot lekérdezése...`, 'info');

    // indítjuk a státusz poll-olást
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
  if (!currentJobId) {
    clearInterval(statusInterval);
    return;
  }
  try {
    const smInput = document.getElementById('speechmaticsApiKey');
    const apiKey = (smInput?.value || '').trim();
    if (!apiKey) {
      throw new Error('Hiányzik a Speechmatics API kulcs a státusz lekérdezéshez.');
    }

    const res = await fetch(`/transcription-status/${encodeURIComponent(currentJobId)}?apiKey=${encodeURIComponent(apiKey)}`);
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data?.error || 'Ismeretlen hiba a státusz lekérdezésnél.');
    }

    const status = data.status;
    setStatus(`Átírás állapota: ${escapeHtml(status)}`, 'info');

    if (status === 'done') {
      clearInterval(statusInterval);
      const srtEditor = document.getElementById('srtText');
      if (srtEditor) {
        srtEditor.value = data.srt_content || '';
      }
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

// ====== SRT letöltés ======
async function downloadSrt() {
  try {
    const srtEditor = document.getElementById('srtText');
    const srtText = srtEditor?.value || '';
    if (!srtText.trim()) {
      setStatus('Nincs letölthető SRT tartalom.', 'warn');
      return;
    }
    const res = await fetch('/download-srt', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ srtText }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data?.error || 'Letöltési hiba.');
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);

    // a fájlnév a backendben a session alapján a videó címéből jön
    const a = document.createElement('a');
    a.href = url;
    a.download = 'subtitle.srt'; // a szerver felülírja Content-Disposition-nel
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    setStatus('SRT letöltve.', 'success');
  } catch (err) {
    setStatus('Hiba SRT letöltéskor: ' + escapeHtml(err.message || String(err)), 'error');
  }
}

// ====== Feltöltés Google Drive-ra ======
async function uploadToDrive() {
  try {
    const srtEditor = document.getElementById('srtText');
    const srtText = srtEditor?.value || '';
    if (!srtText.trim()) {
      setStatus('Nincs feltölthető SRT tartalom.', 'warn');
      return;
    }
    const res = await fetch('/upload-to-drive', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ srtText }),
    });
    const data = await res.json();
    if (!res.ok || !data?.success) {
      throw new Error(data?.error || 'Feltöltési hiba.');
    }
    setStatus('SRT feltöltve a Google Drive-ra. Fájl azonosító: ' + escapeHtml(data.file_id), 'success');
  } catch (err) {
    if (String(err).includes('401')) {
      setStatus('Be kell jelentkezni Google-lel a feltöltéshez.', 'warn');
    } else {
      setStatus('Hiba Drive feltöltéskor: ' + escapeHtml(err.message || String(err)), 'error');
    }
  }
}

// ====== Fordítás Gemini-vel ======
async function translateSrt() {
  try {
    const srtEditor = document.getElementById('srtText');
    const translatedText = document.getElementById('translatedText');
    const targetLanguage = document.getElementById('targetLanguage');
    const geminiInput = document.getElementById('geminiApiKey');

    const srt = srtEditor?.value || '';
    const lang = targetLanguage?.value || 'hu';
    const geminiKey = (geminiInput?.value || '').trim();

    if (!srt.trim()) {
      setStatus('Nincs lefordítható SRT tartalom.', 'warn');
      return;
    }
    if (!geminiKey) {
      setStatus('Kérlek add meg a Gemini API kulcsot!', 'warn');
      return;
    }

    setStatus('Fordítás folyamatban...', 'info');

    const fd = new FormData();
    fd.append('srtText', srt);
    fd.append('targetLanguage', lang);
    fd.append('geminiApiKey', geminiKey);

    const res = await fetch('/translate', { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data?.error || 'Fordítási hiba.');
    }
    if (translatedText) translatedText.value = data.translated_text || '';
    setStatus('Fordítás kész.', 'success');
  } catch (err) {
    setStatus('Hiba fordítás közben: ' + escapeHtml(err.message || String(err)), 'error');
  }
}

// ====== Globálisra téve a HTML inline onclick-hez ======
window.startTranscription = startTranscription;
window.downloadSrt = downloadSrt;
window.uploadToDrive = uploadToDrive;
window.translateSrt = translateSrt;

// ====== Init ======
document.addEventListener('DOMContentLoaded', () => {
  loadApiKeys();
  setupKeyAutosave();
  setStatus('Készen állok.', 'info');
});
