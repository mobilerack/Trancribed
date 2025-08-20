import os
import io
import time
from datetime import timedelta

from flask import Flask, request, jsonify, render_template, redirect, url_for, session, Response
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

app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app)

app.secret_key = os.environ.get("FLASK_SECRET_KEY", "supersecret")
app.config["UPLOAD_FOLDER"] = "temp_uploads"
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# Google OAuth
oauth = OAuth(app)
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
    if "google_token" not in session:
        return render_template("index.html", logged_in=False)
    return render_template("index.html", logged_in=True, user_email=session.get("user_email"))

@app.route("/login")
def login():
    stay_logged_in = request.args.get("stay_logged_in", "false") == "true"
    session["stay_logged_in"] = stay_logged_in
    redirect_uri = url_for("authorize", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)

@app.route("/oauth2callback")
def authorize():
    token = oauth.google.authorize_access_token()
    user_info = oauth.google.get("userinfo").json()
    session["google_token"] = token
    session["user_email"] = user_info.get("email")

    if session.get("stay_logged_in"):
        session.permanent = True
        app.permanent_session_lifetime = timedelta(days=30)
    else:
        session.permanent = False

    return redirect(url_for("index"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

# ---------------------------
# yt-dlp: közvetlen link + cím
# ---------------------------
@app.route("/process-page-url", methods=["POST"])
def process_page_url():
    data = request.get_json()
    page_url = data.get("page_url")
    api_key = data.get("apiKey")
    language = data.get("language")

    if not all([page_url, api_key, language]):
        return jsonify({"error": "Hiányzó weboldal URL, API kulcs vagy nyelv."}), 400

    try:
        ydl_opts = {"format": "bestaudio/best", "quiet": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(page_url, download=False)
            direct_media_url = info.get("url")
            video_title = info.get("title", "subtitle")

        if not direct_media_url:
            return jsonify({"error": "Nem sikerült közvetlen média linket kinyerni az URL-ből."}), 500

        session["video_title"] = video_title

        settings = ConnectionSettings(url="https://asr.api.speechmatics.com/v2", auth_token=api_key)
        full_config = {
            "type": "transcription",
            "transcription_config": {"language": language},
            "fetch_data": {"url": direct_media_url},
        }
        with BatchClient(settings) as client:
            job_id = client.submit_job(audio=None, transcription_config=full_config)

        return jsonify({"job_id": job_id, "video_title": video_title}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------------------------
# Speechmatics státusz
# ---------------------------
@app.route("/transcription-status/<job_id>")
def transcription_status(job_id):
    try:
        api_key = request.args.get("apiKey")
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
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------------------------
# Gemini fordítás
# ---------------------------
@app.route("/translate", methods=["POST"])
def translate():
    try:
        srt_text = request.form.get("srtText")
        gemini_api_key = request.form.get("geminiApiKey")
        target_language = request.form.get("targetLanguage", "magyar")
        video_file = request.files.get("videoContextFile")

        if not all([srt_text, gemini_api_key]):
            return jsonify({"error": "Hiányzó SRT szöveg vagy Gemini API kulcs."}), 400

        genai.configure(api_key=gemini_api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")

        prompt_text = (
            f"Feladat: Fordítsd le a megadott SRT feliratot. "
            f"A formátumot és az időbélyegeket pontosan tartsd meg, csak a szöveget fordítsd.\n\n"
            f"Stílus: A fordítás legyen gördülékeny, természetes, és illeszkedjen a videó kontextusához. "
            f"Vágykeltő, és használjon bátran szlenget, valamint trágár kifejezéseket. Ne szó szerint fordíts!\n\n"
            f"Eredeti szöveg:\n\n{srt_text}"
        )

        prompt_parts = [prompt_text]

        if video_file:
            filename = secure_filename(video_file.filename)
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            video_file.save(filepath)

            video_file_data = genai.upload_file(path=filepath)
            while video_file_data.state.name == "PROCESSING":
                time.sleep(2)
                video_file_data = genai.get_file(video_file_data.name)

            if video_file_data.state.name == "FAILED":
                return jsonify({"error": "A videófájl feltöltése a Geminihez sikertelen."}), 500

            prompt_parts.insert(0, video_file_data)
            prompt_parts.insert(1, "A videó kontextusként szolgál a pontosabb és stílusban megfelelő fordításhoz.\n\n")

            response = model.generate_content(prompt_parts)
            os.remove(filepath)
        else:
            response = model.generate_content(prompt_parts)

        return jsonify({"translated_text": response.text})

    except Exception as e:
        return jsonify({"error": f"Hiba a Gemini fordítás során: {e}"}), 500

# ---------------------------
# SRT letöltés
# ---------------------------
@app.route("/download-srt", methods=["POST"])
def download_srt():
    data = request.get_json()
    srt_text = data.get("srtText")
    video_title = session.get("video_title", "subtitle")
    filename = f"{video_title}.srt"

    return Response(
        srt_text,
        mimetype="text/plain",
        headers={"Content-Disposition": f"attachment;filename={filename}"},
    )

# ---------------------------
# Drive feltöltés
# ---------------------------
def get_credentials():
    token = session.get("google_token")
    from google.oauth2.credentials import Credentials
    return Credentials(
        token["access_token"],
        refresh_token=token.get("refresh_token"),
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        token_uri="https://oauth2.googleapis.com/token",
    )

@app.route("/upload-to-drive", methods=["POST"])
def upload_to_drive():
    if "google_token" not in session:
        return jsonify({"error": "Nincs Google bejelentkezés."}), 401

    data = request.get_json()
    srt_text = data.get("srtText")
    video_title = session.get("video_title", "subtitle")
    filename = f"{video_title}.srt"

    creds = get_credentials()
    service = build("drive", "v3", credentials=creds)
    file_metadata = {"name": filename, "parents": [os.getenv("DRIVE_FOLDER_ID")]}
    media = MediaIoBaseUpload(io.BytesIO(srt_text.encode("utf-8")), mimetype="text/plain")
    uploaded_file = service.files().create(body=file_metadata, media_body=media, fields="id").execute()
    return jsonify({"success": True, "file_id": uploaded_file.get("id")})

# ---------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
