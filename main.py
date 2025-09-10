import os
import io
import time
import uuid
from datetime import timedelta

from flask import Flask, request, jsonify, render_template, redirect, url_for, session, Response, send_file
from flask_cors import CORS
from werkzeug.utils import secure_filename

import yt_dlp
from speechmatics.batch_client import BatchClient
from speechmatics.models import ConnectionSettings
from httpx import HTTPStatusError
import google.generativeai as genai

# Google Auth + Drive
from authlib.integrations.flask_client import OAuth
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# --- VÁLASZTHATÓ SZOLGÁLTATÁS LOGIKA ---

ACTIVE_SERVICE = os.environ.get("TRANSCRIPTION_SERVICE", "speechmatics")
transcriber = None

if ACTIVE_SERVICE == "whisper":
    try:
        from transformers import pipeline
        import torch
        
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
        torch_dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        
        print(f"Whisper modellt használunk a következő eszközön: {device}")
        transcriber = pipeline(
            "automatic-speech-recognition",
            model="openai/whisper-large-v3",
            torch_dtype=torch_dtype,
            device=device,
        )
        print("Whisper modell sikeresen betöltve.")
    except ImportError:
        print("Hiba: A Whisper használatához telepíteni kell a 'torch' és 'transformers' csomagokat.")
        transcriber = None
    except Exception as e:
        print(f"Hiba a Whisper modell betöltése közben: {e}")
        transcriber = None

def format_whisper_to_srt(result):
    srt_content = []
    if 'chunks' in result:
        for i, chunk in enumerate(result['chunks']):
            start_time_s, end_time_s = chunk['timestamp']
            
            start_td = timedelta(seconds=start_time_s or 0)
            end_td = timedelta(seconds=end_time_s or 0)

            start_str = f"0{start_td}"[:-3].replace('.', ',')
            end_str = f"0{end_td}"[:-3].replace('.', ',')

            srt_content.append(str(i + 1))
            srt_content.append(f"{start_str} --> {end_str}")
            srt_content.append(chunk['text'].strip())
            srt_content.append("")
    else:
        # Fallback for older transformers versions or different outputs
        text = result.get('text', "Az átirat üres.")
        srt_content.extend(["1", "00:00:00,000 --> 00:00:10,000", text, ""])
        
    return "\n".join(srt_content)

app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app)

app.secret_key = os.environ.get("FLASK_SECRET_KEY", "supersecret")
app.config["UPLOAD_FOLDER"] = "temp_uploads"
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

oauth = OAuth(app)
# ... A Google OAuth beállítások változatlanok ...
oauth.register(
    name="google",
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    access_token_url="https://oauth2.googleapis.com/token",
    authorize_url="https://accounts.google.com/o/oauth2/auth",
    api_base_url="https://www.googleapis.com/oauth2/v1/",
    client_kwargs={
        "scope": "openid email profile https://www.googleapis.com/auth/drive.file"
    },
)

# ---------------------------
# Routes
# ---------------------------

@app.route("/")
def index():
    logged_in = "google_token" in session
    return render_template("index.html", 
                           logged_in=logged_in, 
                           user_email=session.get("user_email"),
                           transcription_service=ACTIVE_SERVICE)

@app.route("/login")
def login():
    # ... Változatlan ...
    redirect_uri = url_for("authorize", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)

@app.route("/oauth2callback")
def authorize():
    # ... Változatlan ...
    token = oauth.google.authorize_access_token()
    user_info = oauth.google.get("userinfo").json()
    session["google_token"] = token
    session["user_email"] = user_info.get("email")
    return redirect(url_for("index"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/process-page-url", methods=["POST"])
def process_page_url():
    data = request.get_json()
    page_url = data.get("page_url")
    language = data.get("language")
    api_key = data.get("apiKey") if ACTIVE_SERVICE == 'speechmatics' else 'N/A'
    
    if not all([page_url, language]) or (ACTIVE_SERVICE == 'speechmatics' and not api_key):
        return jsonify({"error": "Hiányzó weboldal URL, API kulcs vagy nyelv."}), 400

    filepath = ""
    try:
        video_id = str(uuid.uuid4())
        download_path = os.path.join(app.config["UPLOAD_FOLDER"], f"{video_id}.%(ext)s")

        ydl_opts = {
            'format': 'bestaudio/best[height<=240]',
            'outtmpl': download_path, 'quiet': True,
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}],
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(page_url, download=True)
            video_title = info.get("title", "subtitle")
            filepath = os.path.splitext(ydl.prepare_filename(info))[0] + '.mp3'

        if not os.path.exists(filepath):
            return jsonify({"error": "Nem sikerült letölteni a médiafájlt."}), 500

        session["video_title"] = video_title

        if ACTIVE_SERVICE == 'speechmatics':
            settings = ConnectionSettings(url="https://asr.api.speechmatics.com/v2", auth_token=api_key)
            conf = {"type": "transcription", "transcription_config": {"language": language}}
            with BatchClient(settings) as client:
                with open(filepath, "rb") as audio_file:
                    job_id = client.submit_job(audio=audio_file, transcription_config=conf)
            return jsonify({"job_id": job_id, "video_title": video_title, "service": "speechmatics"}), 200

        elif ACTIVE_SERVICE == 'whisper':
            if transcriber is None:
                return jsonify({"error": "Whisper modell nincs betöltve a szerveren."}), 500
            result = transcriber(filepath, generate_kwargs={"language": language}, return_timestamps="chunk")
            srt_content = format_whisper_to_srt(result)
            return jsonify({"status": "done", "srt_content": srt_content, "video_title": video_title, "service": "whisper"}), 200

    finally:
        if filepath and os.path.exists(filepath):
            os.remove(filepath)

@app.route("/transcription-status/<job_id>")
def transcription_status(job_id):
    # ... Változatlan (ezt csak a Speechmatics használja) ...
    try:
        api_key = request.args.get("apiKey")
        if not api_key: return jsonify({"error": "Hiányzó API kulcs."}), 400
        settings = ConnectionSettings(url="https://asr.api.speechmatics.com/v2", auth_token=api_key)
        with BatchClient(settings) as client:
            job_details = client.check_job_status(job_id)
            status = job_details.get("job", {}).get("status")
            if status == "done":
                srt_content = client.wait_for_completion(job_id, transcription_format="srt")
                return jsonify({"status": "done", "srt_content": srt_content})
            elif status in ["rejected", "error"]:
                return jsonify({"status": "error", "error": "A feladat sikertelen."})
            else:
                return jsonify({"status": status})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/translate", methods=["POST"])
def translate():
    # ... Változatlan ...
    try:
        srt_text = request.form.get("srtText")
        gemini_api_key = request.form.get("geminiApiKey")
        genai.configure(api_key=gemini_api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt_text = (f"Feladat: Fordítsd le a megadott SRT feliratot magyarra. A formátumot és az időbélyegeket pontosan tartsd meg, csak a szöveget fordítsd.\n\nStílus: A fordítás legyen gördülékeny, természetes, és illeszkedjen egy videó kontextusához. Használj szlenget, ne szó szerint fordíts.\n\nEredeti szöveg:\n\n{srt_text}")
        response = model.generate_content([prompt_text])
        return jsonify({"translated_text": response.text})
    except Exception as e:
        return jsonify({"error": f"Hiba a Gemini fordítás során: {e}"}), 500

@app.route("/download-srt", methods=["POST"])
def download_srt():
    # ... Változatlan ...
    data = request.get_json()
    srt_text = data.get("srtText")
    video_title = session.get("video_title", "subtitle")
    filename = f"{video_title}.srt"
    return Response(srt_text, mimetype="text/plain", headers={"Content-Disposition": f"attachment;filename={filename}"})

@app.route("/upload-to-drive", methods=["POST"])
def upload_to_drive():
    # ... Változatlan ...
    if "google_token" not in session: return jsonify({"error": "Nincs Google bejelentkezés."}), 401
    creds = get_credentials() # Ehhez kell egy get_credentials segédfüggvény
    service = build("drive", "v3", credentials=creds)
    data = request.get_json()
    srt_text = data.get("srtText")
    video_title = session.get("video_title", "subtitle")
    filename = f"{video_title}.srt"
    file_metadata = {"name": filename, "parents": [os.getenv("DRIVE_FOLDER_ID")]}
    media = MediaIoBaseUpload(io.BytesIO(srt_text.encode("utf-8")), mimetype="text/plain")
    service.files().create(body=file_metadata, media_body=media, fields="id").execute()
    return jsonify({"success": True})

def get_credentials():
    # ... Változatlan ...
    from google.oauth2.credentials import Credentials
    token = session.get("google_token")
    return Credentials(token["access_token"], refresh_token=token.get("refresh_token"), client_id=os.getenv("GOOGLE_CLIENT_ID"), client_secret=os.getenv("GOOGLE_CLIENT_SECRET"), token_uri="https://oauth2.googleapis.com/token")

@app.route("/download-video")
def download_video():
    page_url = request.args.get("page_url")
    resolution = request.args.get("resolution", "720")
    if not page_url: return "Hiányzó videó URL.", 400
    filepath = ""
    try:
        video_id = str(uuid.uuid4())
        download_path = os.path.join(app.config["UPLOAD_FOLDER"], f"{video_id}.%(ext)s")
        ydl_opts = {'format': f'bestvideo[height<={resolution}][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best', 'outtmpl': download_path}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(page_url, download=True)
            filepath = ydl.prepare_filename(info)
        return send_file(filepath, as_attachment=True, download_name=f"{info.get('title', 'video')}.mp4")
    finally:
        if filepath and os.path.exists(filepath):
            os.remove(filepath)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

