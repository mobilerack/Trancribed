import os
from flask import Flask, request, jsonify, render_template
from werkzeug.utils import secure_filename
import time

# Speechmatics importok
from speechmatics.batch_client import BatchClient
from speechmatics.models import ConnectionSettings
from httpx import HTTPStatusError

# Gemini importok
import google.generativeai as genai

# --- Flask alkalmazás beállítása ---
app = Flask(__name__)
# Ideiglenes fájlok tárolására szolgáló mappa
UPLOAD_FOLDER = 'temp_uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# --- Főoldal ---
@app.route('/')
def index():
    return render_template('index.html')


# --- Speechmatics végpontok ---

@app.route('/start-transcription', methods=['POST'])
def start_transcription():
    """
    Fájl feltöltését és az átírás indítását kezeli.
    Figyelem: Nagy fájlok esetén memória problémát okozhat a Render ingyenes csomagján.
    """
    try:
        api_key = request.form.get('apiKey')
        language = request.form.get('language', 'hu')
        file = request.files.get('file')

        if not all([api_key, language, file]):
            return jsonify({"error": "Hiányzó API kulcs, nyelv vagy fájl."}), 400

        settings = ConnectionSettings(url="https://asr.api.speechmatics.com/v2", auth_token=api_key)
        transcription_config = {"language": language}

        with BatchClient(settings) as client:
            job_id = client.submit_job(
                audio=file,
                transcription_config=transcription_config,
            )
        return jsonify({"job_id": job_id}), 200

    except HTTPStatusError as e:
        error_details = e.response.json().get("detail") or "Ismeretlen API hiba"
        app.logger.error(f"Speechmatics API hiba (HTTPStatusError): {error_details}")
        return jsonify({"error": error_details}), e.response.status_code
    except Exception as e:
        app.logger.error(f"Fájl átírási hiba: {e}")
        return jsonify({"error": "Ismeretlen szerveroldali hiba történt."}), 500


@app.route('/start-transcription-from-url', methods=['POST'])
def start_transcription_from_url():
    """
    Fogad egy URL-t, és elindítja az átírást.
    JAVÍTVA: Az URL-t a Speechmatics által elvárt szótár formátumban adja tovább.
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Érvénytelen kérés formátum."}), 400

        url = data.get('url')
        api_key = data.get('apiKey')
        language = data.get('language', 'hu')

        if not all([url, api_key]):
            return jsonify({"error": "Hiányzó URL vagy API kulcs."}), 400

        settings = ConnectionSettings(url="https://asr.api.speechmatics.com/v2", auth_token=api_key)
        transcription_config = {"language": language}
        
        # JAVÍTÁS ITT: Az URL-t szótárba csomagoljuk
        fetch_data = {"url": url}

        with BatchClient(settings) as client:
            job_id = client.submit_job(
                audio=fetch_data,
                transcription_config=transcription_config,
            )
        return jsonify({"job_id": job_id}), 200

    except HTTPStatusError as e:
        error_details = e.response.json().get("detail") or "Ismeretlen API hiba"
        app.logger.error(f"Speechmatics API hiba (HTTPStatusError): {error_details}")
        return jsonify({"error": error_details}), e.response.status_code
    except Exception as e:
        app.logger.error(f"URL átírási hiba: {e}")
        return jsonify({"error": "Ismeretlen szerveroldali hiba történt."}), 500


@app.route('/transcription-status/<job_id>')
def transcription_status(job_id):
    """
    Lekérdezi egy adott átírási feladat állapotát és eredményét.
    """
    try:
        api_key = request.args.get('apiKey')
        if not api_key:
            return jsonify({"error": "Hiányzó API kulcs."}), 400

        settings = ConnectionSettings(url="https://asr.api.speechmatics.com/v2", auth_token=api_key)

        with BatchClient(settings) as client:
            job_status = client.check_job_status(job_id)
            status = job_status.get("status")

            if status == "done":
                srt_content = client.get_transcript(job_id, "srt")
                return jsonify({"status": "done", "srt_content": srt_content})
            elif status in ["rejected", "error"]:
                # Job details might contain more info on the error
                job_details = client.get_job_details(job_id)
                error_msg = job_details.get("errors", [{}])[0].get("message", "A feladat sikertelen.")
                return jsonify({"status": "error", "error": error_msg})
            else:
                return jsonify({"status": status})

    except HTTPStatusError as e:
        error_details = e.response.json().get("detail") or "Ismeretlen API hiba"
        app.logger.error(f"Státusz lekérdezési hiba (HTTPStatusError): {error_details}")
        return jsonify({"error": error_details}), e.response.status_code
    except Exception as e:
        app.logger.error(f"Státusz lekérdezési hiba: {e}")
        return jsonify({"error": "Ismeretlen szerveroldali hiba történt."}), 500


# --- Gemini végpont ---

@app.route('/translate', methods=['POST'])
def translate():
    """
    A Gemini API segítségével lefordítja a kapott SRT szöveget,
    opcionálisan videó kontextus felhasználásával.
    """
    try:
        srt_text = request.form.get('srtText')
        gemini_api_key = request.form.get('geminiApiKey')
        target_language = request.form.get('targetLanguage', 'magyarra')
        video_file = request.files.get('videoContextFile')

        if not all([srt_text, gemini_api_key]):
            return jsonify({"error": "Hiányzó SRT szöveg vagy Gemini API kulcs."}), 400

        genai.configure(api_key=gemini_api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')

        prompt_parts = [
            f"Fordítsd le a következő SRT feliratot {target_language}. A formátumot és az időbélyegeket pontosan tartsd meg, csak a szöveget fordítsd. A fordítás legyen természetes és gördülékeny. Eredeti szöveg:\n\n{srt_text}"
        ]

        if video_file:
            filename = secure_filename(video_file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            video_file.save(filepath)
            
            # Várunk, amíg a fájl teljesen kiíródik a lemezre
            time.sleep(1)
            
            video_file_data = genai.upload_file(path=filepath)
            
            # Várunk, amíg a feltöltés feldolgozása befejeződik
            while video_file_data.state.name == "PROCESSING":
                time.sleep(2)
                video_file_data = genai.get_file(video_file_data.name)

            if video_file_data.state.name == "FAILED":
                 return jsonify({"error": "A videófájl feltöltése a Geminihez sikertelen."}), 500

            prompt_parts.insert(0, video_file_data)
            prompt_parts.insert(1, "\nA videó kontextusa segít a pontosabb fordításban.")
            
            response = model.generate_content(prompt_parts)
            
            # A feltöltött fájl törlése a szerverről
            os.remove(filepath)
        else:
            response = model.generate_content(prompt_parts)

        return jsonify({"translated_text": response.text})

    except Exception as e:
        app.logger.error(f"Gemini fordítási hiba: {e}")
        return jsonify({"error": f"Hiba a Gemini fordítás során: {e}"}), 500


# --- Alkalmazás indítása ---
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)


