import os
from flask import Flask, request, jsonify, render_template
from werkzeug.utils import secure_filename
import time

from flask_cors import CORS
import yt_dlp
from speechmatics.batch_client import BatchClient
from speechmatics.models import ConnectionSettings
from httpx import HTTPStatusError
import google.generativeai as genai

app = Flask(__name__, static_folder='static') 
CORS(app)

UPLOAD_FOLDER = 'temp_uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/static/<path:path>')
def send_static(path):
    return app.send_static_file(path)

# --- ÚJ VÉGPONT: Letöltési linkek és formátumok lekérése ---
@app.route('/get-download-links', methods=['POST'])
def get_download_links():
    data = request.get_json()
    page_url = data.get('page_url')
    if not page_url:
        return jsonify({"error": "Hiányzó weboldal URL."}), 400

    try:
        app.logger.info(f"Letöltési formátumok keresése a következőhöz: {page_url}")
        ydl_opts = {'quiet': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(page_url, download=False)
        
        formats = []
        # A 'formats' listából kinyerjük a releváns adatokat
        for f in info.get('formats', []):
            # Csak a videóval rendelkező, letölthető formátumokat listázzuk
            if f.get('vcodec') != 'none' and f.get('url'):
                formats.append({
                    'format_id': f.get('format_id'),
                    'ext': f.get('ext'),
                    'resolution': f.get('resolution'),
                    'note': f.get('format_note', 'N/A'),
                    'filesize': f.get('filesize') or f.get('filesize_approx'),
                    'url': f.get('url')
                })
        
        # Eltávolítjuk a duplikált felbontásokat, a jobbat tartjuk meg
        unique_formats = {f['resolution']: f for f in sorted(formats, key=lambda x: x.get('filesize') or 0, reverse=True)}.values()

        return jsonify(list(unique_formats))

    except Exception as e:
        app.logger.error(f"Hiba a letöltési linkek kinyerésekor: {e}")
        return jsonify({"error": "Nem sikerült letöltési opciókat találni a megadott URL-hez."}), 500


@app.route('/process-page-url', methods=['POST'])
def process_page_url():
    data = request.get_json()
    page_url = data.get('page_url')
    api_key = data.get('apiKey')
    language = data.get('language')

    if not all([page_url, api_key, language]):
        return jsonify({"error": "Hiányzó weboldal URL, API kulcs vagy nyelv."}), 400

    try:
        app.logger.info(f"Közvetlen link keresése a következőhöz: {page_url}")
        ydl_opts = {'format': 'bestaudio/best', 'quiet': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(page_url, download=False)
            direct_media_url = info.get('url')
        
        if not direct_media_url:
            return jsonify({"error": "Nem sikerült közvetlen média linket kinyerni az URL-ből."}), 500
        
        app.logger.info(f"Sikeresen kinyert link: {direct_media_url[:50]}...")

        settings = ConnectionSettings(url="https://asr.api.speechmatics.com/v2", auth_token=api_key)
        full_config = {
            "type": "transcription",
            "transcription_config": {"language": language},
            "fetch_data": {"url": direct_media_url}
        }
        with BatchClient(settings) as client:
            job_id = client.submit_job(audio=None, transcription_config=full_config)
        
        app.logger.info(f"Speechmatics feladat elküldve, Job ID: {job_id}")
        return jsonify({"job_id": job_id}), 200

    except yt_dlp.utils.DownloadError as e:
        app.logger.error(f"yt-dlp hiba: {e}")
        return jsonify({"error": "A megadott URL nem támogatott vagy nem található."}), 400
    except HTTPStatusError as e:
        error_details = e.response.json().get("detail") or "Ismeretlen API hiba"
        app.logger.error(f"Speechmatics API hiba: {error_details}")
        return jsonify({"error": error_details}), e.response.status_code
    except Exception as e:
        app.logger.error(f"Általános hiba a feldolgozás során: {e}")
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

