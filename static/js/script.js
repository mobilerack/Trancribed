    // ---------------- ÚJ: Google Drive integráció ----------------

    const googleLoginBtn = document.getElementById('googleLoginBtn');
    const driveFileInput = document.getElementById('driveFileInput');
    const uploadToDriveBtn = document.getElementById('uploadToDriveBtn');

    // Google bejelentkezés
    googleLoginBtn.addEventListener('click', async () => {
        try {
            const response = await fetch('/login');
            const data = await response.json();
            if (!response.ok) throw new Error(data.error);
            // Új ablakban megnyitjuk a Google auth oldalt
            window.open(data.auth_url, '_blank', 'width=500,height=600');
        } catch (error) {
            alert(`Google bejelentkezési hiba: ${error.message}`);
        }
    });

    // Feltöltés Google Drive-ra és átírás indítása
    uploadToDriveBtn.addEventListener('click', async () => {
        const file = driveFileInput.files[0];
        const apiKey = speechmaticsKeyInput.value;
        const language = document.getElementById('sourceLanguageSelect').value;

        if (!file) {
            return showStatus('Válassz ki egy feltöltendő fájlt!', 'warning');
        }
        if (!apiKey) {
            return showStatus('Add meg a Speechmatics API kulcsot!', 'warning');
        }

        toggleSpinner(transcribeSpinner, true);
        uploadToDriveBtn.disabled = true;
        showStatus('Fájl feltöltése Google Drive-ra...', 'info');

        try {
            const formData = new FormData();
            formData.append('file', file);

            const uploadResponse = await fetch('/upload-to-drive', {
                method: 'POST',
                body: formData,
            });
            const uploadData = await uploadResponse.json();
            if (!uploadResponse.ok) throw new Error(uploadData.error);

            const file_url = uploadData.file_url;
            showStatus('Drive link kész, átírás indítása...', 'info');

            const processResponse = await fetch('/process-drive-file', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ apiKey, file_url, language }),
            });
            const processData = await processResponse.json();
            if (!processResponse.ok) throw new Error(processData.error);

            transcriptionJobId = processData.job_id;
            showStatus(`Feladat elküldve (ID: ${transcriptionJobId}). Státusz lekérdezése...`, 'info');
            checkStatusLoop();

        } catch (error) {
            showStatus(`Hiba: ${error.message}`, 'danger');
            toggleSpinner(transcribeSpinner, false);
            uploadToDriveBtn.disabled = false;
        }
    });
