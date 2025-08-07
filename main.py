import os
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from flask import Flask, request, jsonify, render_template, url_for
from werkzeug.utils import secure_filename
import time

# CORS import
from flask_cors import CORS

# Google Drive importok
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

# Speechmatics importok
from speechmatics.batch_client import BatchClient
from speechmatics.models import ConnectionSettings
from httpx import HTTPStatusError

# Gemini importok
import google.generativeai as genai

# Flask és beállítások
app = Flask(__name__, static_folder='static') 
CORS(app)

UPLOAD_FOLDER = 'temp_uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Google Drive beállítások
SCOPES = ['https://www.googleapis.com/auth/drive.file']
SERVICE_ACCOUNT_FILE = 'service_account.json'
# A Drive ID-t a Render környezeti változójából olvassuk!
DRIVE_FOLDER_ID = os.getenv('DRIVE_FOLDER_ID') 

# Google Drive Service inicializálása
try:
    if not DRIVE_FOLDER_ID:
        raise ValueError("A DRIVE_FOLDER_ID környezeti változó nincs beállítva a Renderen!")
        
    drive_credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    drive_service = build('drive', 'v3', credentials=drive_credentials)
except FileNotFoundError:
    drive_service = None
    app.logger.warning("service_account.json nem található. A Google Drive feltöltés nem fog működni.")
except Exception as e:
    drive_service = None
    app.logger.error(f"Hiba a Google Drive szolgáltatás inicializálásakor: {e}")


@app.route('/')
def index():
    """ A főoldalt jeleníti meg. """
    return render_template('index.html')

@app.route('/static/<path:path>')
def send_static(path):
    return app.send_static_file(path)

@app.route('/upload-to-drive', methods=['POST'])
def upload_to_drive():
    if not drive_service:
        return jsonify({"error": "A Google Drive szolgáltatás nincs konfigurálva a szerveren."}), 500
        
    if 'file' not in request.files:
        return jsonify({"error": "Nincs fájl a kérésben."}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Nincs kiválasztott fájl."}), 400

    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    
    try:
        file.save(filepath)
        file_metadata = {'name': filename, 'parents': [DRIVE_FOLDER_ID]}
        media = MediaFileUpload(filepath, resumable=True)
        
        uploaded_file = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webContentLink'
        ).execute()

        file_id = uploaded_file.get('id')
        permission = {'type': 'anyone', 'role': 'reader'}
        drive_service.permissions().create(fileId=file_id, body=permission).execute()
        
        updated_file = drive_service.files().get(fileId=file_id, fields='webContentLink').execute()
        public_url = updated_file.get('webContentLink')

        return jsonify({'public_url': public_url})

    except HttpError as e:
        app.logger.error(f"Google Drive API hiba: {e}")
        return jsonify({"error": f"Hiba a Google Drive API-val: {e.content.decode()}"}), 500
    except Exception as e:
        app.logger.error(f"Feltöltési hiba: {e}")
        return jsonify({"error": "Szerveroldali hiba a feltöltés során."}), 500
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)

@app.route('/start-transcription-from-url', methods=['POST'])
def start_transcription_from_url():
    try:
        data = request.get_json()
        url = data.get('url')
        api_key = data.get('apiKey')
        language = data.get('language', 'hu')
        if not all([url, api_key]):
            return jsonify({"error": "Hiányzó URL vagy API kulcs."}), 400
        settings = ConnectionSettings(url="https://asr.api.speechmatics.com/v2", auth_token=api_key)
        full_config = {
            "type": "transcription",
            "transcription_config": {"language": language},
            "fetch_data": {"url": url}
        }
        with BatchClient(settings) as client:
            job_id = client.submit_job(audio=None, transcription_config=full_config)
        return jsonify({"job_id": job_id}), 200
    except HTTPStatusError as e:
        error_details = e.response.json().get("detail") or "Ismeretlen API hiba"
        app.logger.error(f"Speechmatics API hiba: {error_details}")
        return jsonify({"error": error_details}), e.response.status_code
    except Exception as e:
        app.logger.error(f"URL átírási hiba: {e}")
        return jsonify({"error": "Ismeretlen szerveroldali hiba történt."}), 500

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
        app.logger.error(f"Státusz lekérdezési hiba: {e}")
        return jsonify({"error": "Ismeretlen szerveroldali hiba történt."}), 500

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
            f"Feladat: Fordítsd le a megadott SRT feliratot. A formátumot és az időbélyegeket pontosan tartsd meg, csak a szöveget fordítsd.\n\n"
            f"Stílus: A fordítás legyen gördülékeny, természetes, és illeszkedjen a videó kontextusához. A stílus legyen szexuálisan túlfűtött, "
            f"vágykeltő, és használjon bátran szlenget, valamint trágár kifejezéseket, hogy a párbeszéd életszerű és mocskos legyen. Ne szó szerint fordíts!\n\n"
            f"Eredeti szöveg:\n\n{srt_text}"
        )
        prompt_parts = [prompt_text]

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
            prompt_parts.insert(1, "A videó kontextusként szolgál a pontosabb és stílusban megfelelő fordításhoz.\n\n")
            
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
