import os
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from flask import Flask, request, jsonify, render_template
from werkzeug.utils import secure_filename
import time

# Speechmatics importok
from speechmatics.batch_client import BatchClient
from speechmatics.models import ConnectionSettings
from httpx import HTTPStatusError

# Gemini importok
import google.generativeai as genai

# --- Flask és Storj/S3 beállítások ---
app = Flask(__name__)
UPLOAD_FOLDER = 'temp_uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

S3_ENDPOINT_URL = os.getenv('S3_ENDPOINT_URL')
S3_ACCESS_KEY_ID = os.getenv('S3_ACCESS_KEY_ID')
S3_SECRET_ACCESS_KEY = os.getenv('S3_SECRET_ACCESS_KEY')
S3_BUCKET_NAME = os.getenv('S3_BUCKET_NAME')

required_env_vars = {
    "S3_ENDPOINT_URL": S3_ENDPOINT_URL,
    "S3_ACCESS_KEY_ID": S3_ACCESS_KEY_ID,
    "S3_SECRET_ACCESS_KEY": S3_SECRET_ACCESS_KEY,
    "S3_BUCKET_NAME": S3_BUCKET_NAME
}
missing_vars = [key for key, value in required_env_vars.items() if value is None]
if missing_vars:
    raise ValueError(f"Hiányzó környezeti változók: {', '.join(missing_vars)}.")

s3_client = boto3.client(
    's3',
    endpoint_url=S3_ENDPOINT_URL,
    aws_access_key_id=S3_ACCESS_KEY_ID,
    aws_secret_access_key=S3_SECRET_ACCESS_KEY,
    config=Config(signature_version='s3v4')
)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate-upload-url', methods=['POST'])
def generate_upload_url():
    """ Generál egy biztonságos URL-t a fájl közvetlen feltöltéséhez a Storj-ra. """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Érvénytelen kérés formátum."}), 400

        filename = data.get('filename')
        content_type = data.get('contentType')

        # JAVÍTÁS ITT: Ha a böngésző nem küld típust, adunk neki egy alapértelmezettet.
        if not content_type:
            app.logger.warning(f"A böngésző nem küldött 'contentType'-ot a '{filename}' fájlhoz. Alapértelmezett 'application/octet-stream' használata.")
            content_type = 'application/octet-stream'
        
        if not filename:
            return jsonify({"error": "Hiányzó fájlnév."}), 400

        object_name = f"{int(time.time())}-{secure_filename(filename)}"

        upload_url = s3_client.generate_presigned_url(
            'put_object',
            Params={'Bucket': S3_BUCKET_NAME, 'Key': object_name, 'ContentType': content_type},
            ExpiresIn=3600
        )
        
        public_url = f"{S3_ENDPOINT_URL}/{S3_BUCKET_NAME}/{object_name}"

        return jsonify({
            'upload_url': upload_url,
            'public_url': public_url
        })

    except ClientError as e:
        app.logger.error(f"S3 hiba a link generálásakor: {e}")
        return jsonify({"error": "Nem sikerült feltöltési linket generálni."}), 500
    except Exception as e:
        app.logger.error(f"Általános hiba a link generálásakor: {e}")
        return jsonify({"error": "Szerveroldali hiba történt."}), 500

# ... A többi végpont változatlan ...
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
        full_config = {"type": "transcription", "transcription_config": {"language": language}, "fetch_data": {"url": url}}
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
        app.logger.error(f"Státusz lekérdezési hiba: {error_details}")
        return jsonify({"error": error_details}), e.response.status_code
    except Exception as e:
        app.logger.error(f"Státusz lekérdezési hiba: {e}")
        return jsonify({"error": "Ismeretlen szerveroldali hiba történt."}), 500

@app.route('/translate', methods=['POST'])
def translate():
    try:
        srt_text = request.form.get('srtText')
        gemini_api_key = request.form.get('geminiApiKey')
        target_language = request.form.get('targetLanguage', 'magyarra')
        video_file = request.files.get('videoContextFile')
        if not all([srt_text, gemini_api_key]):
            return jsonify({"error": "Hiányzó SRT szöveg vagy Gemini API kulcs."}), 400
        genai.configure(api_key=gemini_api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt_parts = [f"Fordítsd le a következő SRT feliratot erre a nyelvre: {target_language}. A formátumot és az időbélyegeket pontosan tartsd meg, csak a szöveget fordítsd. A fordítás legyen természetes és gördülékeny. Eredeti szöveg:\n\n{srt_text}"]
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
            prompt_parts.insert(1, "\nA videó kontextusa segít a pontosabb fordításban.")
            response = model.generate_content(prompt_parts)
            os.remove(filepath)
        else:
            response = model.generate_content(prompt_parts)
        return jsonify({"translated_text": response.text})
    except Exception as e:
        app.logger.error(f"Gemini fordítási hiba: {e}")
        return jsonify({"error": f"Hiba a Gemini fordítás során: {e}"}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)

