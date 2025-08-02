document.addEventListener('DOMContentLoaded', () => {
    // UI Elemek
    const sKeyInput = document.getElementById('speechmaticsKey');
    const gKeyInput = document.getElementById('geminiKey');
    const saveSKeyBtn = document.getElementById('saveSpeechmaticsKey');
    const saveGKeyBtn = document.getElementById('saveGeminiKey');
    const transcribeBtn = document.getElementById('transcribeButton');
    const transcribeUrlBtn = document.getElementById('transcribeUrlButton');
    const translateBtn = document.getElementById('translateButton');
    const downloadBtn = document.getElementById('downloadSrtButton');
    const statusDiv = document.getElementById('status');
    const srtEditor = document.getElementById('srtEditor');
    const transcribeSpinner = document.getElementById('transcribeSpinner');
    const translateSpinner = document.getElementById('translateSpinner');
    const transcribeFileInput = document.getElementById('transcribeFile');

    // API kulcsok betöltése a böngésző tárolójából
    sKeyInput.value = localStorage.getItem('speechmaticsApiKey') || '';
    gKeyInput.value = localStorage.getItem('geminiApiKey') || '';

    // Eseménykezelők
    saveSKeyBtn.addEventListener('click', () => saveKey('speechmaticsApiKey', sKeyInput.value));
    saveGKeyBtn.addEventListener('click', () => saveKey('geminiApiKey', gKeyInput.value));
    transcribeBtn.addEventListener('click', startTranscription);
    transcribeUrlBtn.addEventListener('click', startTranscriptionFromUrl);
    translateBtn.addEventListener('click', startTranslation);
    downloadBtn.addEventListener('click', downloadSrt);
    transcribeFileInput.addEventListener('change', handleSrtUpload);

    // --- FUNKCIÓK ---

    function saveKey(keyName, value) {
        localStorage.setItem(keyName, value);
        alert(`${keyName.split('Api')[0]} kulcs mentve!`);
    }

    function updateStatus(message, type = 'info') {
        statusDiv.textContent = message;
        statusDiv.className = `alert alert-${type}`;
    }
    
    function toggleSpinnersAndButtons(show) {
        const buttons = [transcribeBtn, transcribeUrlBtn, translateBtn];
        buttons.forEach(btn => { if (btn) btn.disabled = show; });
        
        // A spinnereket külön kezeljük, hogy a megfelelő jelenjen meg
        if (show) {
            if (event.target.id === 'transcribeButton' || event.target.id === 'transcribeUrlButton') {
                transcribeSpinner.classList.remove('d-none');
            } else if (event.target.id === 'translateButton') {
                translateSpinner.classList.remove('d-none');
            }
        } else {
            transcribeSpinner.classList.add('d-none');
            translateSpinner.classList.add('d-none');
        }
    }

    async function startTranscription() {
        const file = document.getElementById('transcribeFile').files[0];
        const language = document.getElementById('sourceLanguageSelect').value;
        const apiKey = localStorage.getItem('speechmaticsApiKey');

        if (!apiKey) {
            return updateStatus('Hiba: A Speechmatics API kulcs megadása kötelező!', 'danger');
        }
        if (!file) {
            return updateStatus('Hiba: Válassz egy fájlt az átíráshoz!', 'danger');
        }

        toggleSpinnersAndButtons(true);
        updateStatus('Fájl feltöltése és átírása... Ez a fájl hosszától függően több percig is tarthat.', 'info');

        const formData = new FormData();
        formData.append('file', file);
        formData.append('apiKey', apiKey);
        formData.append('language', language);

        try {
            const response = await fetch('/start-transcription', { method: 'POST', body: formData });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || `Szerverhiba: ${response.status}`);
            
            updateStatus('Átírás sikeresen befejeződött!', 'success');
            srtEditor.value = data.srt_content;
            
        } catch (error) {
            updateStatus(`Hiba: ${error.message}`, 'danger');
        } finally {
            toggleSpinnersAndButtons(false);
        }
    }

    async function startTranscriptionFromUrl() {
        const audioUrl = document.getElementById('audioUrlInput').value;
        const language = document.getElementById('sourceLanguageSelect').value;
        const apiKey = localStorage.getItem('speechmaticsApiKey');

        if (!apiKey) {
            return updateStatus('Hiba: A Speechmatics API kulcs megadása kötelező!', 'danger');
        }
        if (!audioUrl) {
            return updateStatus('Hiba: Illessz be egy URL-t az átíráshoz!', 'danger');
        }

        toggleSpinnersAndButtons(true);
        updateStatus('Átírás indítása URL-ből... Ez a fájl hosszától függően több percig is tarthat.', 'info');

        try {
            const response = await fetch('/start-transcription-from-url', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: audioUrl, apiKey: apiKey, language: language })
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || `Szerverhiba: ${response.status}`);
            
            updateStatus('Átírás URL-ből sikeresen befejeződött!', 'success');
            srtEditor.value = data.srt_content;

        } catch (error) {
            updateStatus(`Hiba: ${error.message}`, 'danger');
        } finally {
            toggleSpinnersAndButtons(false);
        }
    }
    
    async function startTranslation() {
        const srtText = srtEditor.value;
        const geminiApiKey = localStorage.getItem('geminiApiKey');
        const videoFile = document.getElementById('videoContextFile').files[0];
        const targetLanguage = document.getElementById('targetLanguageSelect').value;

        if (!geminiApiKey) {
            return updateStatus('Hiba: A Gemini API kulcs megadása kötelező!', 'danger');
        }
        if (!srtText) {
            return updateStatus('Hiba: Az átirat mező nem lehet üres!', 'danger');
        }
        
        toggleSpinnersAndButtons(true);
        updateStatus('Fordítás folyamatban a Gemini segítségével...', 'info');

        const formData = new FormData();
        formData.append('srtText', srtText);
        formData.append('geminiApiKey', geminiApiKey);
        formData.append('targetLanguage', targetLanguage);
        if (videoFile) {
            formData.append('videoContextFile', videoFile);
        }

        try {
            const response = await fetch('/translate', { method: 'POST', body: formData });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || `Szerverhiba: ${response.status}`);
            srtEditor.value = data.translated_text;
            updateStatus('A fordítás sikeresen elkészült!', 'success');
        } catch (error) {
            updateStatus(`Hiba a fordítás során: ${error.message}`, 'danger');
        } finally {
            toggleSpinnersAndButtons(false);
        }
    }

    function downloadSrt() {
        const srtContent = srtEditor.value;
        if (!srtContent) {
            alert('Nincs mit letölteni!');
            return;
        }
        const blob = new Blob([srtContent], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'forditott_felirat.srt';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }
    
    function handleSrtUpload(event) {
        const file = event.target.files[0];
        if (file && file.name.endsWith('.srt')) {
            const reader = new FileReader();
            reader.onload = (e) => {
                srtEditor.value = e.target.result;
                updateStatus(`${file.name} betöltve a szerkesztőbe.`, 'success');
            };
            reader.readAsText(file);
        }
    }
});
