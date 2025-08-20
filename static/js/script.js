document.addEventListener('DOMContentLoaded', () => {
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
  const getLinksButton = document.getElementById('getLinksButton');
  const downloadSpinner = document.getElementById('downloadSpinner');
  const downloadLinksContainer = document.getElementById('downloadLinksContainer');

  let transcriptionJobId = '';
  let currentVideoTitle = '';

  // API kulcs mentés
  saveSpeechmaticsKeyBtn.addEventListener('click', () => {
    localStorage.setItem('speechmaticsApiKey', speechmaticsKeyInput.value);
    alert('Mentve');
  });
  saveGeminiKeyBtn.addEventListener('click', () => {
    localStorage.setItem('geminiApiKey', geminiKeyInput.value);
    alert('Mentve');
  });
  speechmaticsKeyInput.value = localStorage.getItem('speechmaticsApiKey') || '';
  geminiKeyInput.value = localStorage.getItem('geminiApiKey') || '';

  const showStatus = (msg, type="info") => {
    statusDiv.textContent = msg;
    statusDiv.className = `alert alert-${type}`;
  };

  const toggleSpinner = (el, show) => {
    el.classList.toggle('d-none', !show);
  };

  // Átírás
  transcribeButton.addEventListener('click', async () => {
    const page_url = pageUrlInput.value;
    const apiKey = speechmaticsKeyInput.value;
    if (!page_url || !apiKey) return showStatus("Adj meg URL-t és API kulcsot!", "warning");

    toggleSpinner(transcribeSpinner, true);
    transcribeButton.disabled = true;

    try {
      const res = await fetch("/process-page-url", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({page_url, apiKey})
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error);

      transcriptionJobId = data.job_id;
      currentVideoTitle = data.video_title;
      showStatus(`Feladat ID: ${transcriptionJobId}`, "info");
      checkStatusLoop();
    } catch (err) {
      showStatus("Hiba: " + err.message, "danger");
      toggleSpinner(transcribeSpinner, false);
      transcribeButton.disabled = false;
    }
  });

  const checkStatusLoop = () => {
    const interval = setInterval(async () => {
      if (!transcriptionJobId) return clearInterval(interval);
      try {
        const apiKey = speechmaticsKeyInput.value;
        const res = await fetch(`/transcription-status/${transcriptionJobId}?apiKey=${apiKey}`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.error);
        if (data.status === "done") {
          clearInterval(interval);
          srtEditor.value = data.srt_content;
          showStatus("Átírás kész!", "success");
          toggleSpinner(transcribeSpinner, false);
          transcribeButton.disabled = false;
        }
      } catch (err) {
        clearInterval(interval);
        showStatus("Státusz hiba: " + err.message, "danger");
        toggleSpinner(transcribeSpinner, false);
        transcribeButton.disabled = false;
      }
    }, 4000);
  };

  // Fordítás
  translateButton.addEventListener('click', async () => {
    const srtText = srtEditor.value;
    const geminiApiKey = geminiKeyInput.value;
    const targetLanguage = document.getElementById("targetLanguageSelect").value;
    if (!srtText || !geminiApiKey) return showStatus("Hiányzó adat!", "warning");

    toggleSpinner(translateSpinner, true);
    translateButton.disabled = true;

    const formData = new FormData();
    formData.append("srtText", srtText);
    formData.append("geminiApiKey", geminiApiKey);
    formData.append("targetLanguage", targetLanguage);

    try {
      const res = await fetch("/translate", {method:"POST", body:formData});
      const data = await res.json();
      if (!res.ok) throw new Error(data.error);
      srtEditor.value = data.translated_text;
      showStatus("Fordítás kész!", "success");
    } catch (err) {
      showStatus("Fordítási hiba: " + err.message, "danger");
    } finally {
      toggleSpinner(translateSpinner, false);
      translateButton.disabled = false;
    }
  });

  // SRT letöltés
  downloadSrtButton.addEventListener('click', async () => {
    const srtText = srtEditor.value;
    if (!srtText) return alert("Nincs felirat!");

    const res = await fetch("/download-srt", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({srtText, videoTitle: currentVideoTitle})
    });

    if (res.ok) {
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = (currentVideoTitle || "felirat") + ".srt";
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } else {
      const data = await res.json();
      alert("Hiba: " + data.error);
    }
  });

  // Letöltési linkek
  getLinksButton.addEventListener('click', async () => {
    const page_url = document.getElementById('downloadUrlInput').value;
    if (!page_url) return alert("Adj meg URL-t!");

    toggleSpinner(downloadSpinner, true);
    getLinksButton.disabled = true;
    downloadLinksContainer.innerHTML = "<p>Keresés...</p>";

    try {
      const res = await fetch("/get-download-links", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({page_url})
      });
      const formats = await res.json();
      if (!res.ok) throw new Error(formats.error);

      downloadLinksContainer.innerHTML = "";
      formats.forEach(f => {
        const a = document.createElement("a");
        a.href = f.url;
        a.target = "_blank";
        a.className = "list-group-item list-group-item-action";
        a.textContent = `${f.resolution || "N/A"} (${f.ext})`;
        downloadLinksContainer.appendChild(a);
      });
    } catch (err) {
      downloadLinksContainer.innerHTML = `<p class="text-danger">${err.message}</p>`;
    } finally {
      toggleSpinner(downloadSpinner, false);
      getLinksButton.disabled = false;
    }
  });
});
