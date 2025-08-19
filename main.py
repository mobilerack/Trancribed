import os
import time
import pathlib
import json
from flask import Flask, request, jsonify, render_template, session
from werkzeug.utils import secure_filename
from flask_cors import CORS

import yt_dlp
from speechmatics.batch_client import BatchClient
from speechmatics.models import ConnectionSettings
from httpx import HTTPStatusError
import google.generativeai as genai

# Google Auth
import google.oauth2.credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Flask app init
app = Flask(__name__, static_folder='static') 
CORS(app)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "supersecret")  # kell a session-höz

UPLOAD_FOLDER = 'temp_uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# -------------------
# Google OAuth2 Setup
# -------------------
CLIENT_SECRETS_FILE = "client_secret.json"   # ezt Google Cloud Console-ból kell letölteni
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
REDIRECT_URI = "http://localhost:10000/oauth2callback"  # deploy esetén domainhez kell igazítani


# -------------------
# Routes
# -------------------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/static/<path:path>')
def send_static(path):
    return app.send_static_file(path)


# -------------------
# Új: Google OAuth2 Login
# -------------------
@app.route("/login")
def login():
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true"
    )
    session["state"] = state
    return jsonify({"auth_url": authorization_url})


@app.route("/oauth2callback")
def oauth2callback():
    state = session.get("state")
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        state=state,
        redirect_uri=REDIRECT_URI
    )
    flow.fetch_token(authorization_response=request.url)

    credentials = flow.credentials
    session['credentials'] = {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": credentials.scopes
    }
    return "✅ Sikeres Google Drive bejelentkezés! Most már feltölthetsz fájlt."


# -------------------
# Fájl feltöltés → Google Drive
# -------------------
@app.route("/upload-to-drive", methods=["POST"])
def upload_to_drive():
    if "credentials" not in session:
        return jsonify({"error": "Nincs Google Drive bejelentkezés."}), 401

    credentials = google.oauth2.credentials.Credentials(**session['credentials'])
    drive_service = build("drive", "v3", credentials=credentials)

    if "file" not in request.files:
        return jsonify({"error": "Nincs fájl a kérésben."}), 400

    file = request.files["file"]
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file.filename))
    file.save(filepath)

    file_metadata = {"name": file.filename}
    media = MediaFileUpload(filepath, resumable=True)
    uploaded_file = drive_service.files().create(
        body=file_metadata, 
        media_body=media, 
        fields="id"
    ).execute()

    # publikus hozzáférés engedélyezése
    drive_service.permissions().create(
        fileId=uploaded_file.get("id"),
        body={"role": "reader", "type": "anyone"}
    ).execute()

    file_url = f"https://drive.google.com/uc?id={uploaded_file.get('id')}&export=download"

    os.remove(filepath)  # törlés a szerverről

    return jsonify({"file_url": file_url})


# -------------------
# Drive → Speechmatics feldolgozás
# -------------------
@app.route("/process-drive-file", methods=["POST"])
def process_drive_file():
    data = request.get_json()
    api_key = data.get("apiKey")
    file_url = data.get("file_url")
    language = data.get("language")

    if not all([api_key, file_url, language]):
        return jsonify({"error": "Hiányzó adat (API kulcs, file_url, language)."}), 400

    try:
        settings = ConnectionSettings(url="https://asr.api.speechmatics.com/v2", auth_token=api_key)
        full_config = {
            "type": "transcription",
            "transcription_config": {"language": language},
            "fetch_data": {"url": file_url}
        }
        with BatchClient(settings) as client:
            job_id = client.submit_job(audio=None, transcription_config=full_config)

        return jsonify({"job_id": job_id})
    except Exception as e:
        app.logger.error(f"Speechmatics hiba: {e}")
        return jsonify({"error": "Nem sikerült elindítani a feldolgozást."}), 500


# -------------------
# Meglévő yt-dlp + Speechmatics
# -------------------
@app.route('/get-download-links', methods=['POST'])
def get_download_links():
    data = request.get_json()
    page_url = data.get('page_url')
    if not page_url:
        return jsonify({"error": "Hiányzó weboldal URL."}), 400

    try:
        app.logger.info(f"Letöltési formátumok keresése: {page_url}")
        ydl_opts = {'quiet': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(page_url, download=False)
        
        formats = []
        for f in info.get('formats', []):
            if f.get('vcodec') != 'none' and f.get('url'):
                formats.append({
                    'format_id': f.get('format_id'),
                    'ext': f.get('ext'),
                    'resolution': f.get('resolution'),
                    'note': f.get('format_note', 'N/A'),
                    'filesize': f.get('filesize') or f.get('filesize_approx'),
                    'url': f.get('url')
                })
        
        unique_formats = {f['resolution']: f for f in sorted(formats, key=lambda x: x.get('filesize') or 0, reverse=True)}.values()
        return jsonify(list(unique_formats))

    except Exception as e:
        app.logger.error(f"Hiba: {e}")
        return jsonify({"error": "Nem sikerült letöltési opciókat találni."}), 500


@app.route('/process-page-url', methods=['POST'])
def process_page_url():
    data = request.get_json()
    page_url = data.get('page_url')
    api_key = data.get('apiKey')
    language = data.get('language')

    if not all([page_url, api_key, language]):
        return jsonify({"error": "Hiányzó weboldal URL, API kulcs vagy nyelv."}), 400

    try:
        app.logger.info(f"Közvetlen link keresése: {page_url}")
        ydl_opts = {'format': 'bestaudio/best', 'quiet': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(page_url, download=False)
            direct_media_url = info.get('url')
        
        if not direct_media_url:
            return jsonify({"error": "Nem sikerült közvetlen média linket kinyerni."}), 500
        
        settings = ConnectionSettings(url="https://asr.api.speechmatics.com/v2", auth_token=api_key)
        full_config = {
            "type": "transcription",
            "transcription_config": {"language": language},
            "fetch_data": {"url": direct_media_url}
        }
        with BatchClient(settings) as client:
            job_id = client.submit_job(audio=None, transcription_config=full_config)
        
        return jsonify({"job_id": job_id}), 200

    except yt_dlp.utils.DownloadError as e:
        return jsonify({"error": "A megadott URL nem támogatott."}), 400
    except HTTPStatusError as e:
        error_details = e.response.json().get("detail") or "Ismeretlen API hiba"
        return jsonify({"error": error_details}), e.response.status_code
    except Exception as e:
        app.logger.error(f"Hiba: {e}")
        return jsonify({"error": "Ismeretlen hiba."}), 500


@app.route('/transcription-status/<job_id>')
def transcription_status(job_id):
    try:
        api_key = request.args.get('apiKey')
        if not api_key:
            return jsonify({"error": "Hiányzó API kulcs."}), 400
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
    except HTTPStatusError as e:
        error_details = e.response.json().get("detail") or "Ismeretlen API hiba"
        return jsonify({"error": error_details}), e.response.status_code
    except Exception as e:
        app.logger.error(f"Státusz hiba: {e}")
        return jsonify({"error": "Ismeretlen szerveroldali hiba."}), 500


# -------------------
# Gemini Translate
# -------------------
@app.route('/translate', methods=['POST'])
def translate():
    try:
        srt_text = request.form.get('srtText')
        gemini_api_key = request.form.get('geminiApiKey')
        target_language = request.form.get('targetLanguage', 'magyar')
        video_file = request.files.get('videoContextFile')

        if not all([srt_text, gemini_api_key]):
            return jsonify({"error": "Hiányzó SRT szöveg vagy Gemini API kulcs."}), 400

        genai.configure(api_key=gemini_api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        prompt_text = (
            f"Célnyelv: {target_language}.\n\n"
            f"Feladat: Fordítsd le a megadott SRT feliratot. "
            f"A formátumot és az időbélyegeket pontosan tartsd meg, csak a szöveget fordítsd."
        )
        prompt_parts = [prompt_text, srt_text]

        if video_file:
            filename = secure_filename(video_file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            video_file.save(filepath)

            video_file_data = genai.upload_file(path=filepath)
            while video_file_data.state.name == "PROCESSING":
                time.sleep(2)
                video_file_data = genai.get_file(video_file_data.name)
            
            if video_file_data.state.name == "FAILED":
                 return jsonify({"error": "A videófájl feltöltése a Geminihez sikertelen."}), 500

            prompt_parts.insert(0, video_file_data)
            prompt_parts.insert(1, "A videó kontextusként szolgál a fordításhoz.\n\n")
            
            response = model.generate_content(prompt_parts)
            os.remove(filepath)
        else:
            response = model.generate_content(prompt_parts)

        return jsonify({"translated_text": response.text})

    except Exception as e:
        app.logger.error(f"Gemini fordítási hiba: {e}")
        return jsonify({"error": f"Hiba a Gemini fordítás során: {e}"}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
