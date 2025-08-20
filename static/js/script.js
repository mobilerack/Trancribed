document.addEventListener('DOMContentLoaded', () => {
    // DOM elemek
    const speechmaticsKeyInput = document.getElementById('speechmaticsKey');
    const geminiKeyInput = document.getElementById('geminiKey');
    const saveSpeechmaticsKeyBtn = document.getElementById('saveSpeechmaticsKey');
    const saveGeminiKeyBtn = document.getElementById('saveGeminiKey');

    const pageUrlInput = document.getElementById('pageUrlInput');
    const transcribeButton = document.getElementById('transcribeButton');
    const srtEditor = document.getElementById('srtEditor');
    const statusDiv = document.getElementById('status');
    const transcribeSpinner = document.getElementById('transcribeSpinner');

    const translateSpinner = document.getElementById('translateSpinner');
    const translateButton = document.getElementById('translateButton');

    const downloadSrtButton = document.getElementById('downloadSrtButton');

    const downloadUrlInput = document.getElementById('downloadUrlInput');
    const getLinksButton = document.getElementById('getLinksButton');
    const downloadSpinner = document.getElementById('downloadSpinner');
    const downloadLinksContainer = document.getElementById('downloadLinksContainer');
    const downloadModalEl = document.getElementById('downloadModal');
    const downloadModal = downloadModalEl ? new bootstrap.Modal(downloadModalEl) : null;

    let transcriptionJobId = '';
    let currentFilename = 'subtitle.srt';

    // API kulcsok kezelése (localStorage)
    saveSpeechmaticsKeyBtn.addEventListener('click', () => {
        localStorage.setItem('speechmaticsApiKey', speechmaticsKeyInput.value);
        alert('Speechmatics kulcs mentve!');
    });
    saveGeminiKeyBtn.addEventListener('click', () => {
        localStorage.setItem('geminiApiKey', geminiKeyInput.value);
        alert('Gemini kulcs mentve!');
    });
    speechmaticsKeyInput.value = localStorage.getItem('speechmaticsApiKey') || '';
    geminiKeyInput.value = localStorage.getItem('geminiApiKey') || '';

    // helper UI
    const showStatus = (message, type = 'info') => {
        statusDiv.textContent = message;
        statusDiv.className = `alert alert-${type}`;
    };
    const toggleSpinner = (spinner, show) => {
        spinner.classList.toggle('d-none', !show);
    };

    // Átírás indítása
    transcribeButton.addEventListener('click', async () => {
        const page_url = pageUrlInput.value;
        const apiKey = speechmaticsKeyInput.value;
        const language = document.getElementById('sourceLanguageSelect').value;

        if (!page_url || !apiKey) {
            return showStatus('Kérlek, add meg a videó URL-t és a Speechmatics kulcsot!', 'warning');
        }

        toggleSpinner(transcribeSpinner, true);
        transcribeButton.disabled = true;
        showStatus('Közvetlen média link keresése és átírás indítása...', 'info');

        try {
            const response = await fetch('/process-page-url', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ page_url, apiKey, language }),
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Ismeretlen hiba');

            transcriptionJobId = data.job_id;
            currentFilename = data.filename || 'subtitle.srt';

            showStatus(`Feladat elküldve (ID: ${transcriptionJobId}). Státusz lekérdezése...`, 'info');
            checkStatusLoop();
        } catch (error) {
            showStatus(`Hiba: ${error.message}`, 'danger');
            toggleSpinner(transcribeSpinner, false);
            transcribeButton.disabled = false;
        }
    });

    // Státusz lekérdezés ciklus
    const checkStatusLoop = () => {
        const interval = setInterval(async () => {
            if (!transcriptionJobId) return clearInterval(interval);
            try {
                const apiKey = speechmaticsKeyInput.value;
                const response = await fetch(`/transcription-status/${transcriptionJobId}?apiKey=${encodeURIComponent(apiKey)}`);
                const data = await response.json();
                if (!response.ok) throw new Error(data.error || 'Ismeretlen hiba');

                showStatus(`Átírás állapota: ${data.status}`, 'info');

                if (data.status === 'done') {
                    clearInterval(interval);
                    srtEditor.value = data.srt_content || '';
                    showStatus('Átírás sikeresen befejeződött!', 'success');
                    toggleSpinner(transcribeSpinner, false);
                    transcribeButton.disabled = false;
                } else if (data.status === 'error' || data.status === 'rejected') {
                    clearInterval(interval);
                    throw new Error(data.error || 'A feladat sikertelen.');
                }
            } catch (error) {
                clearInterval(interval);
                showStatus(`Hiba a státusz lekérdezésekor: ${error.message}`, 'danger');
                toggleSpinner(transcribeSpinner, false);
                transcribeButton.disabled = false;
            }
        }, 5000);
    };

    // Fordítás (placeholder)
    translateButton.addEventListener('click', async () => {
        const srtText = srtEditor.value;
        const geminiApiKey = geminiKeyInput.value;
        const targetLanguage = document.getElementById('targetLanguageSelect').value;

        if (!srtText || !geminiApiKey) {
            return showStatus('Hiányzó SRT szöveg vagy Gemini API kulcs!', 'warning');
        }

        toggleSpinner(translateSpinner, true);
        translateButton.disabled = true;
        showStatus('Fordítás folyamatban...', 'info');

        const formData = new FormData();
        formData.append('srtText', srtText);
        formData.append('geminiApiKey', geminiApiKey);
        formData.append('targetLanguage', targetLanguage);

        try {
            const response = await fetch('/translate', { method: 'POST', body: formData });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Ismeretlen hiba');
            srtEditor.value = data.translated_text || srtText;
            showStatus('Fordítás kész!', 'success');
        } catch (error) {
            showStatus(`Fordítási hiba: ${error.message}`, 'danger');
        } finally {
            toggleSpinner(translateSpinner, false);
            translateButton.disabled = false;
        }
    });

    // SRT letöltése (kliensoldalról, a cím alapján)
    downloadSrtButton.addEventListener('click', () => {
        const srtText = srtEditor.value;
        if (!srtText) {
            return alert("Nincs elérhető felirat a letöltéshez!");
        }
        const a = document.createElement("a");
        const blob = new Blob([srtText], { type: "text/plain;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        a.href = url;
        a.download = currentFilename || 'subtitle.srt';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    });

    // Letöltési linkek kérése (yt-dlp)
    getLinksButton.addEventListener('click', async () => {
        const page_url = downloadUrlInput.value || pageUrlInput.value;
        if (!page_url) return alert('Kérlek, adj meg egy URL-t!');

        toggleSpinner(downloadSpinner, true);
        getLinksButton.disabled = true;
        downloadLinksContainer.innerHTML = '<p class="text-center">Formátumok keresése...</p>';

        try {
            const response = await fetch('/get-download-links', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ page_url }),
            });
            const formats = await response.json();
            if (!response.ok) throw new Error(formats.error || 'Ismeretlen hiba');

            populateDownloadModal(formats);
            if (downloadModal) downloadModal.show();
        } catch (error) {
            downloadLinksContainer.innerHTML = `<p class="text-danger">${error.message}</p>`;
        } finally {
            toggleSpinner(downloadSpinner, false);
            getLinksButton.disabled = false;
        }
    });

    function populateDownloadModal(formats) {
        downloadLinksContainer.innerHTML = '';
        if (!formats || formats.length === 0) {
            downloadLinksContainer.innerHTML = '<p class="text-center">Nem található letölthető videó formátum.</p>';
            return;
        }

        // Méret formázó
        const formatBytes = (bytes, decimals = 1) => {
            if (!+bytes) return 'N/A';
            const k = 1024, dm = decimals < 0 ? 0 : decimals, sizes = ["B","KB","MB","GB","TB"];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`;
        };

        // nagyobb fájl előre
        formats.sort((a,b) => (b.filesize || 0) - (a.filesize || 0)).forEach(format => {
            const link = document.createElement('a');
            link.href = format.url;
            link.target = '_blank';
            link.className = 'list-group-item list-group-item-action download-link-item';

            const resolution = format.resolution || 'N/A';
            const note = format.note || '';
            const size = formatBytes(format.filesize);

            link.innerHTML = `
                <div class="d-flex w-100 justify-content-between">
                    <h6 class="mb-1">${resolution} (${format.ext || "?"})</h6>
                    <small>${size}</small>
                </div>
                <p class="mb-1 small text-muted">${note}</p>
            `;
            downloadLinksContainer.appendChild(link);
        });
    }
});
