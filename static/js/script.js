document.addEventListener('DOMContentLoaded', () => {
    // DOM Elemek
    const speechmaticsKeyInput = document.getElementById('speechmaticsKey');
    const geminiKeyInput = document.getElementById('geminiKey');
    const saveSpeechmaticsKeyBtn = document.getElementById('saveSpeechmaticsKey');
    const saveGeminiKeyBtn = document.getElementById('saveGeminiKey');
    const transcribeFile = document.getElementById('transcribeFile');
    const audioUrlInput = document.getElementById('audioUrlInput');
    const transcribeButton = document.getElementById('transcribeButton');
    const transcribeUrlButton = document.getElementById('transcribeUrlButton');
    const srtEditor = document.getElementById('srtEditor');
    const statusDiv = document.getElementById('status');
    const transcribeSpinner = document.getElementById('transcribeSpinner');
    const translateSpinner = document.getElementById('translateSpinner');
    const translateButton = document.getElementById('translateButton');
    const downloadSrtButton = document.getElementById('downloadSrtButton');

    let transcriptionJobId = '';

    // --- API Kulcsok Kezelése (localStorage) ---
    saveSpeechmaticsKeyBtn.addEventListener('click', () => {
        localStorage.setItem('speechmaticsApiKey', speechmaticsKeyInput.value);
        alert('Speechmatics kulcs mentve!');
    });

    saveGeminiKeyBtn.addEventListener('click', () => {
        localStorage.setItem('geminiApiKey', geminiKeyInput.value);
        alert('Gemini kulcs mentve!');
    });

    // Kulcsok betöltése, ha léteznek
    speechmaticsKeyInput.value = localStorage.getItem('speechmaticsApiKey') || '';
    geminiKeyInput.value = localStorage.getItem('geminiApiKey') || '';

    // --- Állapotkezelő Függvények ---
    const showStatus = (message, type = 'info') => {
        statusDiv.textContent = message;
        statusDiv.className = `alert alert-${type}`;
    };

    const toggleSpinner = (spinner, show) => {
        spinner.classList.toggle('d-none', !show);
    };

    // --- Fő Funkciók ---

    // 1. Átírás indítása fájlfeltöltéssel
    transcribeButton.addEventListener('click', async () => {
        if (transcribeFile.files.length === 0) {
            showStatus('Kérlek, válassz egy fájlt a feltöltéshez!', 'warning');
            return;
        }
        const file = transcribeFile.files[0];
        const formData = new FormData();
        formData.append('file', file);

        toggleSpinner(transcribeSpinner, true);
        transcribeButton.disabled = true;
        showStatus('Fájl feltöltése a Google Drive-ra...', 'info');

        try {
            // Fájl feltöltése a szerverre, ami továbbküldi a Drive-ra
            const uploadResponse = await fetch('/upload-to-drive', {
                method: 'POST',
                body: formData,
            });
            const uploadData = await uploadResponse.json();
            if (!uploadResponse.ok) throw new Error(uploadData.error || 'Feltöltési hiba');

            showStatus('Feltöltés sikeres. Átírás indítása a kapott URL-lel...', 'info');
            // Átírás indítása a kapott URL-lel
            startTranscription(uploadData.public_url);

        } catch (error) {
            showStatus(`Hiba: ${error.message}`, 'danger');
            toggleSpinner(transcribeSpinner, false);
            transcribeButton.disabled = false;
        }
    });

    // 2. Átírás indítása URL-ből
    transcribeUrlButton.addEventListener('click', () => {
        const url = audioUrlInput.value;
        if (!url) {
            showStatus('Kérlek, adj meg egy érvényes URL-t!', 'warning');
            return;
        }
        toggleSpinner(transcribeSpinner, true); // Bár ez a spinner a másik gombnál van, jelezhetjük a folyamatot
        transcribeUrlButton.disabled = true;
        showStatus('Átírás indítása a megadott URL-ről...', 'info');
        startTranscription(url);
    });

    // Közös átírás-indító függvény
    const startTranscription = async (mediaUrl) => {
        const apiKey = speechmaticsKeyInput.value;
        const language = document.getElementById('sourceLanguageSelect').value;

        if (!apiKey) {
            showStatus('Add meg a Speechmatics API kulcsot!', 'danger');
            toggleSpinner(transcribeSpinner, false);
            transcribeButton.disabled = false;
            transcribeUrlButton.disabled = false;
            return;
        }

        try {
            const response = await fetch('/start-transcription-from-url', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: mediaUrl, apiKey, language }),
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error);

            transcriptionJobId = data.job_id;
            showStatus(`Feladat elküldve (ID: ${transcriptionJobId}). Státusz lekérdezése...`, 'info');
            checkStatusLoop();
        } catch (error) {
            showStatus(`Hiba az átírás indításakor: ${error.message}`, 'danger');
            toggleSpinner(transcribeSpinner, false);
            transcribeButton.disabled = false;
            transcribeUrlButton.disabled = false;
        }
    };

    // Státusz ellenőrző ciklus
    const checkStatusLoop = () => {
        const interval = setInterval(async () => {
            if (!transcriptionJobId) {
                clearInterval(interval);
                return;
            }
            try {
                const apiKey = speechmaticsKeyInput.value;
                const response = await fetch(`/transcription-status/${transcriptionJobId}?apiKey=${apiKey}`);
                const data = await response.json();
                if (!response.ok) throw new Error(data.error);

                showStatus(`Átírás állapota: ${data.status}`, 'info');

                if (data.status === 'done') {
                    clearInterval(interval);
                    srtEditor.value = data.srt_content;
                    showStatus('Átírás sikeresen befejeződött!', 'success');
                    toggleSpinner(transcribeSpinner, false);
                    transcribeButton.disabled = false;
                    transcribeUrlButton.disabled = false;
                } else if (data.status === 'error' || data.status === 'rejected') {
                    clearInterval(interval);
                    throw new Error(data.error || 'A feladat sikertelen.');
                }
            } catch (error) {
                clearInterval(interval);
                showStatus(`Hiba a státusz lekérdezésekor: ${error.message}`, 'danger');
                toggleSpinner(transcribeSpinner, false);
                transcribeButton.disabled = false;
                transcribeUrlButton.disabled = false;
            }
        }, 5000);
    };
    
    // 3. Fordítás
    translateButton.addEventListener('click', async () => {
        const srtText = srtEditor.value;
        const geminiApiKey = geminiKeyInput.value;
        const targetLanguage = document.getElementById('targetLanguageSelect').value;
        const videoContextFile = document.getElementById('videoContextFile').files[0];

        if (!srtText || !geminiApiKey) {
            showStatus('Hiányzó SRT szöveg vagy Gemini API kulcs!', 'warning');
            return;
        }

        toggleSpinner(translateSpinner, true);
        translateButton.disabled = true;
        showStatus('Fordítás folyamatban a Gemini segítségével...', 'info');

        const formData = new FormData();
        formData.append('srtText', srtText);
        formData.append('geminiApiKey', geminiApiKey);
        formData.append('targetLanguage', targetLanguage);
        if (videoContextFile) {
            formData.append('videoContextFile', videoContextFile);
        }

        try {
            const response = await fetch('/translate', {
                method: 'POST',
                body: formData,
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error);

            srtEditor.value = data.translated_text; // Felülírjuk az eredetit a fordítottal
            showStatus('Fordítás sikeres!', 'success');

        } catch (error) {
            showStatus(`Fordítási hiba: ${error.message}`, 'danger');
        } finally {
            toggleSpinner(translateSpinner, false);
            translateButton.disabled = false;
        }
    });

    // 4. SRT Letöltése
    downloadSrtButton.addEventListener('click', () => {
        const srtContent = srtEditor.value;
        if (!srtContent) {
            alert('Nincs mit letölteni!');
            return;
        }
        const blob = new Blob([srtContent], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `felirat_${new Date().toISOString()}.srt`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    });
});

