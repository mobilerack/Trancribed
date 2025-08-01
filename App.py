import os
import asyncio
from flask import Flask, request, jsonify, render_template
from werkzeug.utils import secure_filename
import speechmatics.batch
import google.generativeai as genai
import httpx

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start-transcription', methods=['POST'])
async def handle_start_transcription():
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
        async with speechmatics.batch.AsyncClient(api_key=api_key) as client:
            config = speechmatics.batch.JobConfig(
                type='transcription',
                transcription_config={'language': language}
            )
            job_details = await client.submit_job(filepath, config)
            return jsonify({'job_id': job_details.id})
    except Exception as e:
        app.logger.error(f"Speechmatics hiba: {e}")
        return jsonify({'error': f"Speechmatics API hiba: {e}"}), 500
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)

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
        async with httpx.AsyncClient() as client:
            response = await client.post(api_endpoint, headers=headers, json=config)
            response.raise_for_status()
        job_data = response.json()
        return jsonify({'job_id': job_data.get('id')})
    except httpx.HTTPStatusError as e:
        app.logger.error(f"HTTP hiba Speechmatics felé: {e.response.text}")
        return jsonify({'error': f"Speechmatics API hiba: {e.response.text}"}), e.response.status_code
    except Exception as e:
        app.logger.error(f"Általános hiba az URL-es átírás során: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/transcription-status/<job_id>')
async def handle_transcription_status(job_id):
    api_key = request.args.get('apiKey')
    if not api_key:
        return jsonify({'error': 'Hiányzó Speechmatics API kulcs.'}), 400
    try:
        async with speechmatics.batch.AsyncClient(api_key=api_key) as client:
            job_info = await client.get_job_info(job_id)
            if job_info.status == speechmatics.batch.JobStatus.DONE:
                result = await client.get_transcript(job_id, format_type=speechmatics.batch.FormatType.SRT)
                return jsonify({'status': 'done', 'srt_content': result})
            else:
                return jsonify({'status': job_info.status.value})
    except Exception as e:
        app.logger.error(f"Speechmatics állapot lekérdezési hiba: {e}")
        return jsonify({'error': str(e), 'status': 'error'}), 500

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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
