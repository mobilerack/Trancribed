import os
import io
import time
import logging
from datetime import timedelta

from flask import Flask, request, jsonify, render_template, redirect, url_for, session, Response
from flask_cors import CORS
from werkzeug.utils import secure_filename

import yt_dlp
from yt_dlp.utils import DownloadError
import requests
from pornhub_api import PornhubApi
from speechmatics.batch_client import BatchClient
from speechmatics.models import ConnectionSettings
import google.generativeai as genai

# Google Auth + Drive
from authlib.integrations.flask_client import OAuth
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# Alap logging beállítása
logging.basicConfig(level=logging.INFO)

app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app)

app.secret_key = os.environ.get("FLASK_SECRET_KEY", "supersecret")
app.config["UPLOAD_FOLDER"] = "temp_uploads"
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# Google OAuth beállítások...
# ... (ez a rész változatlan a korábbi kódból) ...

# ---------------------------
# Routes
# ---------------------------

@app.route("/")
def index():
    user = session.get("user")
    return render_template("index.html", logged_in=bool(user), user_email=user.get("email") if user else None)

# ... (login, authorize, logout routes változatlanok) ...

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
            # Itt jön a fallback logika
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
            return jsonify({"job_id": job_id, "video_title": video_title})

    except Exception as e:
        app.logger.error(f"Hiba a feldolgozás során: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        # Mindig töröljük a letöltött/feltöltött fájlt
        if audio_path and os.path.exists(audio_path):
            os.remove(audio_path)


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
                
                # A legkisebb minőségű link kiválasztása a gyors letöltésért
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
    """Elküldi a fájlt a Speechmatics-nek."""
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
        response = requests.post(f"{whisper_url}/transcribe", files=files, data=data, timeout=900) # 15 perc timeout
    
    response.raise_for_status() # Hibát dob, ha nem 2xx a válasz
    return response.json()


# ... (a többi route: /transcription-status, /translate, /download-srt, /upload-to-drive változatlan) ...

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=True)

