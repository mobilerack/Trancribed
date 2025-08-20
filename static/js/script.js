document.addEventListener('DOMContentLoaded', () => {
    const srtEditor = document.getElementById('srtEditor');
    const downloadSrtButton = document.getElementById('downloadSrtButton');
    const uploadDriveButton = document.getElementById('uploadDriveButton');

    // SRT letöltése
    downloadSrtButton.addEventListener('click', async () => {
        const srtText = srtEditor.value;
        const filename = "subtitle.srt";
        const response = await fetch('/download-srt', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ srtText, filename })
        });
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(url);
    });

    // Drive feltöltés
    uploadDriveButton.addEventListener('click', async () => {
        const srtText = srtEditor.value;
        const filename = "subtitle.srt";
        const response = await fetch('/upload-to-drive', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ srtText, filename })
        });
        const data = await response.json();
        if (data.success) {
            alert("Feltöltve a Google Drive-ba!");
        } else {
            alert("Hiba: " + data.error);
        }
    });
});
