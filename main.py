import os
import time
from flask import Flask, request, jsonify, render_template
from werkzeug.utils import secure_filename
from speechmatics.batch import BatchClient # CORRECTED IMPORT
import google.generativeai as genai
import httpx

# --- Flask App Initialization ---
app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# --- Main Page ---
@app.route('/')
def index():
    return render_template('index.html')


# --- Transcribe from FILE ---
@app.route('/start-transcription', methods=['POST'])
def handle_start_transcription():
    if 'file' not in request.files or 'apiKey' not in request.form or 'language' not in request.form:
        return jsonify({'error': 'Missing data (file, apiKey, language).'}), 400
    
    file = request.files['file']
    api_key = request.form['apiKey']
    language = request.form['language']

    if file.filename == '':
        return jsonify({'error': 'No file selected.'}), 400

    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    try:
        # CORRECTED INITIALIZATION
        with BatchClient(api_key=api_key) as client:
            conf = {
                "type": "transcription",
                "transcription_config": {
                    "language": language
                }
            }
            job_id = client.submit_job(
                audio=filepath,
                config=conf,
            )
            transcript = client.wait_for_job_result(job_id, transcription_format="srt")
            return jsonify({'status': 'done', 'srt_content': transcript})

    except Exception as e:
        app.logger.error(f"Speechmatics error: {e}")
        return jsonify({'error': f"Speechmatics API error: {str(e)}"}), 500
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)

# --- Transcribe from URL ---
@app.route('/start-transcription-from-url', methods=['POST'])
def handle_start_transcription_from_url():
    data = request.get_json()
    if not data or 'url' not in data or 'apiKey' not in data or 'language' not in data:
        return jsonify({'error': 'Missing data in request (url, apiKey, language).'}), 400
    
    audio_url = data['url']
    api_key = data['apiKey']
    language = data['language']
    
    try:
        # CORRECTED INITIALIZATION
        with BatchClient(api_key=api_key) as client:
            conf = {
                "type": "transcription",
                "transcription_config": {
                    "language": language
                }
            }
            # The URL is passed directly to the submit_job function
            job_id = client.submit_job(
                audio=audio_url,
                config=conf
            )
            transcript = client.wait_for_job_result(job_id, transcription_format="srt")
            return jsonify({'status': 'done', 'srt_content': transcript})

    except Exception as e:
        app.logger.error(f"Error during URL transcription: {e}")
        return jsonify({'error': str(e)}), 500

# --- Translate (Gemini) ---
@app.route('/translate', methods=['POST'])
def handle_translate():
    if 'geminiApiKey' not in request.form or 'srtText' not in request.form or 'targetLanguage' not in request.form:
        return jsonify({'error': 'Missing data (geminiApiKey, srtText, targetLanguage).'}), 400
    
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
        
        response = model.generate_content(prompt_parts)
        return jsonify({'translated_text': response.text})
        
    except Exception as e:
        app.logger.error(f"Gemini API error: {e}")
        return jsonify({'error': f"Gemini API error: {str(e)}"}), 500
    finally:
        if video_filepath and os.path.exists(video_filepath):
            os.remove(video_filepath)

# --- Application Start ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)

