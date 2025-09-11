// ====== LocalStorage kulcsok ======
const LS_KEYS = {
  speechmatics: 'speechmaticsApiKey',
  gemini: 'geminiApiKey',
};

// ====== Helper UI ======
function setStatus(msg, type = 'info') {
  const box = document.getElementById('statusBox');
  if (!box) return;
  const typeClass = type === 'success' ? 'status-success' : type === 'warn' ? 'status-warn' : type === 'error' ? 'status-error' : 'status-info';
  box.innerHTML = `<div class="status ${typeClass}">${msg}</div>`;
  // Üzenet eltávolítása egy idő után, kivéve a hibát
  if (type !== 'error') {
    setTimeout(() => {
        if (box.innerHTML.includes(msg)) {
            box.innerHTML = '';
        }
    }, 6000);
  }
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.innerText = text ?? '';
  return div.innerHTML;
}

// ====== API kulcsok: betöltés és mentés ======
function loadApiKeys() {
  document.getElementById('speechmaticsApiKey').value = localStorage.getItem(LS_KEYS.speechmatics) || '';
  document.getElementById('geminiApiKey').value = localStorage.getItem(LS_KEYS.gemini) || '';
}
function setupKeyAutosave() {
  document.getElementById('speechmaticsApiKey').addEventListener('input', (e) => localStorage.setItem(LS_KEYS.speechmatics, e.target.value.trim()));
  document.getElementById('geminiApiKey').addEventListener('input', (e) => localStorage.setItem(LS_KEYS.gemini, e.target.value.trim()));
}

// ====== Globális állapot ======
let currentJobId = null;
let statusInterval = null;

// ====== Átirat indítása ======
async function startTranscription() {
  try {
    const urlInput = document.getElementById('videoUrl');
    const fileInput = document.getElementById('videoFile');
    const langSel = document.getElementById('language');
    const smInput = document.getElementById('speechmaticsApiKey');
    const serviceSel = document.getElementById('transcriptionService');

    const page_url = urlInput.value.trim();
    const video_file = fileInput.files[0];
    const language = langSel.value;
    const apiKey = smInput.value.trim();
    const service = serviceSel.value;

    if (!page_url && !video_file) {
      setStatus('Kérlek adj meg egy URL-t vagy válassz egy fájlt!', 'warn');
      return;
    }
    if (service === 'speechmatics' && !apiKey) {
      setStatus('A Speechmatics használatához add meg az API kulcsot!', 'warn');
      return;
    }

    // Előző eredmények törlése
    document.getElementById('srtText').value = '';
    document.getElementById('translatedText').value = '';
    
    // Gomb letiltása a dupla kattintás elkerülésére
    const startButton = document.querySelector('.primary-button');
    startButton.disabled = true;
    startButton.textContent = 'Feldolgozás...';

    const formData = new FormData();
    formData.append('language', language);
    formData.append('service', service);
    formData.append('apiKey', apiKey); // Akkor is elküldjük, ha nem kell, a szerver majd eldönti

    if (video_file) {
      formData.append('media_file', video_file);
    } else {
      formData.append('page_url', page_url);
    }

    setStatus('Feldolgozás indítása a szerveren...', 'info');

    const res = await fetch('/process-media', {
      method: 'POST',
      body: formData,
    });
    
    const data = await res.json();

    if (!res.ok) {
      throw new Error(data?.error || `Ismeretlen hiba (${res.status})`);
    }

    // Kezeljük a választ a szolgáltatótól függően
    if (service === 'whisper') {
        // A Whisper API szinkronban adja vissza az eredményt
        document.getElementById('srtText').value = data.srt_content || '';
        setStatus('Átírás kész (Whisper)!', 'success');
        openTab(null, 'transcription'); // Váltás az átirat fülre
    } else {
        // A Speechmatics aszinkron, poll-olni kell
        currentJobId = data.job_id;
        setStatus(`Feladat elküldve (ID: ${escapeHtml(currentJobId)}). Állapot lekérdezése...`, 'info');
        beginStatusPolling();
    }

  } catch (err) {
    setStatus('Hiba: ' + escapeHtml(err.message || String(err)), 'error');
  } finally {
    // Gomb visszaállítása
    const startButton = document.querySelector('.primary-button');
    startButton.disabled = false;
    startButton.textContent = '🚀 Átirat Indítása';
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
    const apiKey = document.getElementById('speechmaticsApiKey').value.trim();
    if (!apiKey) throw new Error('Hiányzik a Speechmatics API kulcs a státusz lekérdezéshez.');

    const res = await fetch(`/transcription-status/${encodeURIComponent(currentJobId)}?apiKey=${encodeURIComponent(apiKey)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data?.error || 'Ismeretlen hiba a státusz lekérdezésnél.');

    const status = data.status;
    setStatus(`Átírás állapota: ${escapeHtml(status)}`, 'info');

    if (status === 'done') {
      clearInterval(statusInterval);
      document.getElementById('srtText').value = data.srt_content || '';
      setStatus('Átírás kész (Speechmatics)!', 'success');
      openTab(null, 'transcription');
    } else if (status === 'error' || status === 'rejected') {
      clearInterval(statusInterval);
      throw new Error(data?.error || 'A feladat sikertelen.');
    }
  } catch (err) {
    clearInterval(statusInterval);
    setStatus('Hiba a státusz lekérdezésekor: ' + escapeHtml(err.message || String(err)), 'error');
  }
}

// ====== Fordítás, letöltés, feltöltés (változatlan) ======

async function translateSrt() {
  try {
    const srtText = document.getElementById('srtText').value;
    const targetLanguage = document.getElementById('targetLanguage').value;
    const geminiApiKey = document.getElementById('geminiApiKey').value.trim();

    if (!srtText.trim()) {
      setStatus('Nincs mit lefordítani.', 'warn');
      return;
    }
    if (!geminiApiKey) {
      setStatus('Add meg a Gemini API kulcsot a fordításhoz!', 'warn');
      return;
    }
    
    setStatus('Fordítás folyamatban a Gemini segítségével...', 'info');

    const fd = new FormData();
    fd.append('srtText', srtText);
    fd.append('targetLanguage', targetLanguage);
    fd.append('geminiApiKey', geminiApiKey);

    const res = await fetch('/translate', { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.error || 'Fordítási hiba.');
    
    document.getElementById('translatedText').value = data.translated_text || '';
    setStatus('Fordítás kész.', 'success');
  } catch (err) {
    setStatus('Hiba fordítás közben: ' + escapeHtml(err.message || String(err)), 'error');
  }
}

async function downloadSrt(isTranslated = true) {
  try {
    const content = isTranslated 
      ? document.getElementById('translatedText').value 
      : document.getElementById('srtText').value;
      
    const srtText = content || '';
    if (!srtText.trim()) {
      setStatus('Nincs letölthető tartalom.', 'warn');
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
    
    const a = document.createElement('a');
    a.href = url;
    // A szerver adja a fájlnevet a Content-Disposition headerben
    a.download = 'subtitle.srt';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    setStatus('SRT fájl letöltve.', 'success');
  } catch (err) {
    setStatus('Hiba az SRT letöltésekor: ' + escapeHtml(err.message || String(err)), 'error');
  }
}

async function uploadToDrive() {
  // A feltöltéshez mindig a fordított szöveget használjuk, ha van
  const srtText = document.getElementById('translatedText').value.trim() || document.getElementById('srtText').value.trim();
  if (!srtText) {
      setStatus('Nincs feltölthető tartalom.', 'warn');
      return;
  }
  
  setStatus('Feltöltés a Google Drive-ra...', 'info');

  try {
    const res = await fetch('/upload-to-drive', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ srtText }),
    });
    const data = await res.json();
    if (!res.ok || !data?.success) {
      // Ha 401 a hiba, az a bejelentkezés hiányát jelenti
      if(res.status === 401){
          setStatus('A feltöltéshez be kell jelentkezned Google fiókkal!', 'warn');
          window.location.href = '/login'; // Irányítsuk át a bejelentkezéshez
      } else {
          throw new Error(data?.error || 'Feltöltési hiba.');
      }
    } else {
      setStatus('SRT sikeresen feltöltve a Google Drive-ra.', 'success');
    }
  } catch (err) {
    setStatus('Hiba a Drive feltöltéskor: ' + escapeHtml(err.message || String(err)), 'error');
  }
}

// ====== UI Funkciók ======
function openTab(evt, tabName) {
  document.querySelectorAll('.tab-content').forEach(tab => tab.classList.remove('active'));
  document.querySelectorAll('.tab-link').forEach(link => link.classList.remove('active'));
  document.getElementById(tabName).classList.add('active');
  if (evt) evt.currentTarget.classList.add('active');
  else document.querySelector(`.tab-link[onclick*="${tabName}"]`).classList.add('active');
}

// ====== Init ======
document.addEventListener('DOMContentLoaded', () => {
  loadApiKeys();
  setupKeyAutosave();
  setStatus('Készen állok a munkára.', 'info');
  openTab(null, 'transcription');
});
