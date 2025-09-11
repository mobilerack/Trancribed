import os
import io
import time
import logging

from flask import Flask, request, jsonify, render_template, Response, session
from flask_cors import CORS
from werkzeug.utils import secure_filename

import yt_dlp
from yt_dlp.utils import DownloadError
import requests
from pornhub_api import PornhubApi
from speechmatics.batch_client import BatchClient
from speechmatics.models import ConnectionSettings
import google.generativeai as genai

# Alap logging beállítása
logging.basicConfig(level=logging.INFO)

app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app)

# A secret key a session-höz (videó címének tárolása) továbbra is kell
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "a-very-secret-key-you-should-change")
app.config["UPLOAD_FOLDER"] = "temp_uploads"
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# ---------------------------
# Routes
# ---------------------------

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/process-media", methods=["POST"])
def process_media():
    data = request.form
    api_key = data.get("apiKey")
    language = data.get("language")
    service = data.get("service", "speechmatics")
    page_url = data.get("page_url")
    media_file = request.files.get("media_file")
    
    audio_path = None
    video_title = "subtitle"

    try:
        if media_file:
            filename = secure_filename(media_file.filename)
            audio_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            media_file.save(audio_path)
            video_title, _ = os.path.splitext(filename)
            session["video_title"] = video_title

        elif page_url:
            audio_path, video_title = download_with_fallback(page_url)
            session["video_title"] = video_title
        
        else:
            return jsonify({"error": "Nincs URL vagy fájl megadva."}), 400

        # Fájl elküldése a választott szolgáltatásnak
        if service == 'whisper':
            result = send_to_whisper(audio_path, language)
            return jsonify(result)
        else: # speechmatics
            job_id = send_to_speechmatics(audio_path, api_key, language)
            # A video_title-t is visszaadjuk, hogy a sessionbe kerüljön
            return jsonify({"job_id": job_id, "video_title": video_title})

    except Exception as e:
        app.logger.error(f"Hiba a feldolgozás során: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
    finally:
        # Mindig töröljük a letöltött/feltöltött fájlt
        if audio_path and os.path.exists(audio_path):
            os.remove(audio_path)

@app.route("/transcription-status/<job_id>")
def transcription_status(job_id):
    api_key = request.args.get("apiKey")
    if not api_key:
        return jsonify({"error": "Hiányzó API kulcs."}), 400

    try:
        settings = ConnectionSettings(url="https://asr.api.speechmatics.com/v2", auth_token=api_key)
        with BatchClient(settings) as client:
            job_details = client.check_job_status(job_id)
            status = job_details.get("job", {}).get("status")
            if status == "done":
                srt_content = client.wait_for_completion(job_id, transcription_format="srt")
                return jsonify({"status": "done", "srt_content": srt_content})
            elif status in ["rejected", "error"]:
                error_msg = job_details.get("job", {}).get("errors", [{}])[0].get("message", "A feladat sikertelen.")
                return jsonify({"status": "error", "error": error_msg})
            else:
                return jsonify({"status": status})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/translate", methods=["POST"])
def translate():
    try:
        # A JS FormData-t küld, ezért request.form-ot használunk
        srt_text = request.form.get("srtText")
        gemini_api_key = request.form.get("geminiApiKey")
        target_language = request.form.get("targetLanguage", "magyar")

        if not all([srt_text, gemini_api_key]):
            return jsonify({"error": "Hiányzó SRT szöveg vagy Gemini API kulcs."}), 400

        genai.configure(api_key=gemini_api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        prompt = (
            f"Feladat: Fordítsd le a megadott SRT feliratot erre a nyelvre: {target_language}. "
            f"A formátumot és az időbélyegeket pontosan tartsd meg, csak a szöveget fordítsd.\n\n"
            f"Stílus: A fordítás legyen gördülékeny, természetes. "
            f"Ha a szöveg szlenget vagy trágár kifejezéseket tartalmaz, ne finomkodj, fordítsd le bátran hasonló stílusban.\n\n"
            f"Eredeti szöveg:\n{srt_text}"
        )
        
        response = model.generate_content(prompt)
        return jsonify({"translated_text": response.text})

    except Exception as e:
        app.logger.error(f"Hiba a Gemini fordítás során: {e}", exc_info=True)
        return jsonify({"error": f"Hiba a Gemini fordítás során: {e}"}), 500
        
@app.route("/download-srt", methods=["POST"])
def download_srt():
    data = request.get_json()
    srt_text = data.get("srtText")
    video_title = session.get("video_title", "subtitle")
    # Biztonságos fájlnév létrehozása
    safe_filename = "".join(c for c in video_title if c.isalnum() or c in (' ', '.', '_')).rstrip()
    filename = f"{safe_filename}.srt"

    return Response(
        srt_text,
        mimetype="text/plain",
        headers={"Content-Disposition": f"attachment;filename=\"{filename}\""},
    )

def download_with_fallback(url):
    """Megpróbálja letölteni a videót yt-dlp-vel, hiba esetén Pornhub API-val."""
    temp_dir = app.config["UPLOAD_FOLDER"]
    ydl_opts = {
        'format': 'bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4][height<=360]',
        'outtmpl': os.path.join(temp_dir, '%(id)s.%(ext)s'),
        'quiet': True,
    }
    
    try:
        app.logger.info(f"Próbálkozás yt-dlp-vel: {url}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return ydl.prepare_filename(info), info.get("title", "subtitle")
    except DownloadError:
        app.logger.warning(f"yt-dlp sikertelen. Ellenőrzés, hogy Pornhub link-e...")
        if 'pornhub.com' in url:
            try:
                app.logger.info("Pornhub link észlelve, próbálkozás a pornhub-api-val...")
                api = PornhubApi()
                video = api.video.get(video_id_from_url=url)
                if not video or not video.download_urls:
                    raise ValueError("A videó nem található vagy nincsenek letöltési linkek.")
                
                download_url = list(video.download_urls.values())[-1]
                filepath = os.path.join(temp_dir, f"{video.video_id}.mp4")

                with requests.get(download_url, stream=True) as r:
                    r.raise_for_status()
                    with open(filepath, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            f.write(chunk)
                return filepath, video.title
            except Exception as ph_e:
                raise Exception(f"A Pornhub-ról sem sikerült letölteni: {ph_e}")
        else:
            raise Exception("A megadott URL nem támogatott és nem Pornhub link.")

def send_to_speechmatics(filepath, api_key, language):
    """Elküldi a fájlt a Speechmatics-nek és visszaadja a job ID-t."""
    if not api_key:
        raise ValueError("A Speechmatics API kulcs hiányzik.")
    settings = ConnectionSettings(url="https://asr.api.speechmatics.com/v2", auth_token=api_key)
    conf = {"type": "transcription", "transcription_config": {"language": language}}
    with BatchClient(settings) as client:
        job_id = client.submit_job(audio=filepath, transcription_config=conf)
        return job_id

def send_to_whisper(filepath, language):
    """Elküldi a fájlt a külső Whisper API szervernek."""
    whisper_url = os.environ.get("WHISPER_API_URL")
    if not whisper_url:
        raise ConnectionError("A WHISPER_API_URL környezeti változó nincs beállítva.")
    
    with open(filepath, 'rb') as f:
        files = {'file': (os.path.basename(filepath), f)}
        data = {'language': language}
        response = requests.post(f"{whisper_url}/transcribe", files=files, data=data, timeout=900)
    
    response.raise_for_status()
    return response.json()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=True)
