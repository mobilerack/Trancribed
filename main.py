import os
from flask import Flask, request, jsonify, render_template
from werkzeug.utils import secure_filename
import speechmatics.client # Ez a jó, 'c' betűvel
import google.generativeai as genai
import httpx # Ezt meghagyjuk az URL-es verzióhoz

# --- Flask App Inicializálása ---
app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# --- Főoldal betöltése ---
@app.route('/')
def index():
    return render_template('index.html')


# --- Átírás FÁJLBÓL (Egyszerűsített, Szinkron) ---
@app.route('/start-transcription', methods=['POST'])
def handle_start_transcription():
    if 'file' not in request.files or 'apiKey' not in request.form or 'language' not in request.form:
        return jsonify({'error': 'Hiányzó adatok (fájl, apiKulcs, nyelv).'}), 400
    
    file = request.files['file']
    api_key = request.form['apiKey']
    language = request.form['language']

    if file.filename == '':
        return jsonify({'error': 'Nincs kiválasztott fájl.'}), 400

    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    try:
        settings = {'auth_token': api_key}
        
        # A szinkron BatchClient használata
        with speechmatics.client.BatchClient(settings) as client:
            conf = {
                "type": "transcription",
                "transcription_config": {
                    "language": language
                }
            }
            # A run_batch egyben elküldi a fájlt és megvárja az eredményt
            transcript = client.run_batch(filepath, conf, transcription_format="srt")
            
            # Mivel ez a függvény már megvárja az eredményt,
            # nincs szükség külön státusz lekérdezésre és job_id-ra.
            # Azonnal a kész SRT szöveget küldjük vissza.
            return jsonify({'status': 'done', 'srt_content': transcript})

    except Exception as e:
        app.logger.error(f"Speechmatics hiba: {e}")
        return jsonify({'error': f"Speechmatics API hiba: {str(e)}"}), 500
    finally:
        # A végén mindenképp töröljük az ideiglenes fájlt
        if os.path.exists(filepath):
            os.remove(filepath)

# --- Átírás URL-BŐL (Ez maradhat aszinkron, mert az httpx jól kezeli) ---
@app.route('/start-transcription-from-url', methods=['POST'])
async def handle_start_transcription_from_url():
    data = request.get_json()
    if not data or 'url' not in data or 'apiKey' not in data or 'language' not in data:
        return jsonify({'error': 'Hiányzó adatok a kérésben (url, apiKey, language).'}), 400
    
    audio_url = data['url']
    api_key = data['apiKey']
    language = data['language']
    
    api_endpoint = "https://asr.api.speechmatics.com/v2/jobs"
    headers = {"Authorization": f"Bearer {api_key}"}
    config = {
        "type": "transcription",
        "fetch_data": {"url": audio_url},
        "transcription_config": {"language": language}
    }
    
    try:
        # Ehhez kell az async és a httpx, de a pollingot innen is kivesszük
        async with httpx.AsyncClient(timeout=600.0) as client: # Hosszabb időkorlát
            # Feladat elküldése
            post_response = await client.post(api_endpoint, headers=headers, json=config)
            post_response.raise_for_status()
            job_data = post_response.json()
            job_id = job_data.get('id')
            
            # Polling (várakozás az eredményre)
            status_url = f"{api_endpoint}/{job_id}"
            while True:
                await asyncio.sleep(5)
                status_response = await client.get(status_url, headers={"Authorization": f"Bearer {api_key}"})
                status_data = status_response.json()
                if status_data['job']['status'] == 'done':
                    transcript_url = f"{status_url}/transcript?format=srt"
                    transcript_response = await client.get(transcript_url, headers={"Authorization": f"Bearer {api_key}"})
                    return jsonify({'status': 'done', 'srt_content': transcript_response.text})
                elif status_data['job']['status'] in ['rejected', 'deleted', 'expired']:
                    raise Exception(f"A feladat sikertelen: {status_data['job']['errors']}")

    except Exception as e:
        app.logger.error(f"Hiba az URL-es átírás során: {e}")
        return jsonify({'error': str(e)}), 500


# --- Fordítás (Gemini) ---
@app.route('/translate', methods=['POST'])
async def handle_translate():
    if 'geminiApiKey' not in request.form or 'srtText' not in request.form or 'targetLanguage' not in request.form:
        return jsonify({'error': 'Hiányzó adatok (geminiApiKey, srtText, targetLanguage).'}), 400
    
    gemini_api_key = request.form['geminiApiKey']
    srt_to_translate = request.form['srtText']
    target_language = request.form['targetLanguage']
    video_file_obj = request.files.get('videoContextFile')
    
    try:
        genai.configure(api_key=gemini_api_key)
        model = genai.GenerativeModel('gemini-1.5-pro-latest')
        
        prompt_parts = []
        video_filepath = None
        
        if video_file_obj:
            filename = secure_filename(video_file_obj.filename)
            video_filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            video_file_obj.save(video_filepath)
            video_file_for_api = genai.upload_file(path=video_filepath)
            prompt_parts.append(video_file_for_api)
            
        prompt_text = f"""Fordítsd le {target_language} ezt az SRT feliratot a megadott videó kontextusa alapján. Tartsd be az alábbi szabályokat:
1.  Az időbélyegzők és a sorszámok pontosan, karakterre megegyezően maradjanak változatlanok.
2.  Használj természetes, gördülékeny nyelvet. Ha a kontextus engedi, használhatsz szlenget.
3.  A trágár kifejezéseket ne cenzúrázd, fordítsd le őket a megfelelő magyar megfelelőjükre.
4.  A fordítás legyen értelmes és kövesse a videón látható eseményeket.
5.  A végeredmény egy tiszta, valid SRT formátumú szöveg legyen, mindenféle extra magyarázat vagy kommentár nélkül.

Eredeti SRT:
---
{srt_to_translate}
---
Lefordított SRT:
"""
        prompt_parts.append(prompt_text)
        
        response = await model.generate_content_async(prompt_parts)
        return jsonify({'translated_text': response.text})
        
    except Exception as e:
        app.logger.error(f"Gemini API hiba: {e}")
        return jsonify({'error': f"Gemini API hiba: {e}"}), 500
    finally:
        if video_filepath and os.path.exists(video_filepath):
            os.remove(video_filepath)


# --- Alkalmazás Indítása ---
if __name__ == '__main__':
    # Ezt a részt a Replit vagy a Gunicorn kezeli, de hibakereséshez hasznos lehet
    app.run(host='0.0.0.0', port=8080)
