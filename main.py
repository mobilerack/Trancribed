import os
from flask import Flask, request, jsonify
from faster_whisper import WhisperModel
import logging
import time

# Logging beállítása
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

# --- MODELL BETÖLTÉSE ---
# Figyelem: A 'large-v3' modell letöltése első alkalommal sok időt vehet igénybe!
# GPU használathoz: device="cuda", compute_type="float16" (vagy "int8_float16")
# CPU használathoz: device="cpu", compute_type="int8" (lassabb)
MODEL_SIZE = "large-v3"
DEVICE = "cuda" 
COMPUTE_TYPE = "float16"

logging.info(f"Whisper modell ({MODEL_SIZE}) betöltése a következő beállításokkal: device={DEVICE}, compute_type={COMPUTE_TYPE}")
try:
    model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)
    logging.info("Whisper modell sikeresen betöltve.")
except Exception as e:
    logging.error(f"Hiba a modell betöltése közben: {e}")
    model = None

def format_time(seconds):
    """Helper függvény SRT időbélyeg formázáshoz."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"

@app.route('/health', methods=['GET'])
def health_check():
    """Jelzi, hogy a szerver fut-e és a modell be van-e töltve."""
    if model:
        return "OK", 200
    else:
        return "Model not loaded", 503

@app.route('/transcribe', methods=['POST'])
def transcribe_audio():
    if not model:
        return jsonify({"error": "A modell nem áll rendelkezésre."}), 503
        
    if 'file' not in request.files:
        return jsonify({"error": "Nincs 'file' a kérésben."}), 400

    file = request.files['file']
    language = request.form.get('language', 'en') # Alapértelmezett nyelv az angol

    temp_path = f"temp_whisper_audio_{int(time.time())}"
    file.save(temp_path)
    
    logging.info(f"Átírás indítása a '{temp_path}' fájlhoz, nyelv: {language}")
    srt_content = ""
    try:
        segments, info = model.transcribe(
            temp_path,
            beam_size=5,
            language=language if language != 'auto' else None
        )

        for i, segment in enumerate(segments):
            start = format_time(segment.start)
            end = format_time(segment.end)
            text = segment.text.strip()
            srt_content += f"{i + 1}\n{start} --> {end}\n{text}\n\n"
        
        logging.info(f"Átírás sikeresen befejezve. ({info.duration}s)")
    except Exception as e:
        logging.error(f"Hiba az átírás során: {e}")
        return jsonify({"error": f"Whisper hiba: {e}"}), 500
    finally:
        os.remove(temp_path)

    return jsonify({"status": "done", "srt_content": srt_content})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5001)))
