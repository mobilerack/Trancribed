import os
import json
import yt_dlp
import tempfile
import requests
from datetime import timedelta
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file
from flask_session import Session
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import google.auth.transport.requests
from google.oauth2.credentials import Credentials

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "supersecret")

# Session config
app.config["SESSION_TYPE"] = "filesystem"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=1)
Session(app)

# Google OAuth
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = json.loads(os.environ.get("GOOGLE_CLIENT_SECRET", "{}"))["web"]["client_secret"]
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI")
DRIVE_FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID")

os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

flow = Flow.from_client_config(
    {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uris": [GOOGLE_REDIRECT_URI],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token"
        }
    },
    scopes=["https://www.googleapis.com/auth/drive.file", "openid", "email", "profile"],
)

# -------------------
# ROUTES
# -------------------

@app.route("/")
def index():
    return render_template("index.html", logged_in=("credentials" in session))

@app.route("/login")
def login():
    stay_signed_in = request.args.get("stay", "false") == "true"
    session["stay_signed_in"] = stay_signed_in
    flow.redirect_uri = GOOGLE_REDIRECT_URI
    authorization_url, state = flow.authorization_url(access_type="offline", include_granted_scopes="true")
    session["state"] = state
    return redirect(authorization_url)

@app.route("/oauth2callback")
def oauth2callback():
    flow.fetch_token(authorization_response=request.url)
    credentials = flow.credentials
    session["credentials"] = {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": credentials.scopes
    }
    if session.get("stay_signed_in"):
        session.permanent = True
    return redirect(url_for("index"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

# -------------------
# API: Get download links
# -------------------
@app.route("/get-download-links", methods=["POST"])
def get_download_links():
    data = request.json
    page_url = data.get("page_url")
    if not page_url:
        return jsonify({"error": "No URL provided"}), 400

    try:
        ydl_opts = {"quiet": True, "dump_single_json": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(page_url, download=False)
        formats = []
        for f in info.get("formats", []):
            formats.append({
                "url": f.get("url"),
                "ext": f.get("ext"),
                "resolution": f.get("format_note"),
                "filesize": f.get("filesize"),
                "note": f.get("format")
            })
        return jsonify(formats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -------------------
# API: Transcription (stub for now)
# -------------------
@app.route("/process-page-url", methods=["POST"])
def process_page_url():
    data = request.json
    return jsonify({"job_id": "demo123"})

@app.route("/transcription-status/<job_id>")
def transcription_status(job_id):
    return jsonify({"status": "done", "srt_content": "1\n00:00:00,000 --> 00:00:02,000\nHello world!"})

# -------------------
# API: Translate SRT (Gemini)
# -------------------
@app.route("/translate", methods=["POST"])
def translate():
    srt_text = request.form.get("srtText")
    target_language = request.form.get("targetLanguage")

    if not srt_text:
        return jsonify({"error": "Missing SRT text"}), 400

    # Itt a prompt a Te utasításoddal
    prompt = (
        f"Feladat: Fordítsd le a megadott SRT feliratot.\n"
        f"A formátumot és az időbélyegeket pontosan tartsd meg, csak a szöveget fordítsd.\n\n"
        f"Stílus: A fordítás legyen gördülékeny, természetes, és illeszkedjen a videó kontextusához. "
        f"Vágykeltő, és használjon bátran szlenget, valamint trágár kifejezéseket. Ne szó szerint fordíts!\n\n"
        f"Célnyelv: {target_language}\n\n"
        f"Felirat:\n{srt_text}"
    )

    # Ezt itt a Gemini API hívására kell majd cserélni:
    translated = srt_text.replace("Hello world!", "Helló világ! (fordítva)")

    return jsonify({"translated_text": translated})

# -------------------
# API: Save SRT to Google Drive
# -------------------
@app.route("/upload-to-drive", methods=["POST"])
def upload_to_drive():
    if "credentials" not in session:
        return jsonify({"error": "Not logged in"}), 401

    creds = Credentials(**session["credentials"])
    service = build("drive", "v3", credentials=creds)

    srt_text = request.json.get("srtText")
    filename = request.json.get("filename", "subtitles.srt")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".srt") as tmp:
        tmp.write(srt_text.encode("utf-8"))
        tmp.flush()
        media = MediaFileUpload(tmp.name, mimetype="text/plain")
        file_metadata = {"name": filename, "parents": [DRIVE_FOLDER_ID]}
        service.files().create(body=file_metadata, media_body=media, fields="id").execute()

    return jsonify({"success": True})

# -------------------
# API: Download SRT
# -------------------
@app.route("/download-srt", methods=["POST"])
def download_srt():
    srt_text = request.json.get("srtText")
    filename = request.json.get("filename", "subtitles.srt")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".srt") as tmp:
        tmp.write(srt_text.encode("utf-8"))
        tmp.flush()
        return send_file(tmp.name, as_attachment=True, download_name=filename)

# -------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
