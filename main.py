from flask import Flask, request, jsonify, render_template

# Speechmatics kliens importálása
from speechmatics.batch_client import BatchClient
from speechmatics.models import ConnectionSettings, TranscriptionConfig

# --- Flask alkalmazás beállítása ---
app = Flask(__name__)


# --- Flask végpontok (Routes) ---

@app.route("/")
def index():
    """
    Ez a főoldal, ami megjeleníti a HTML formot,
    ahol a felhasználó megadhatja az API kulcsot és feltöltheti a fájlt.
    """
    return render_template("index.html")


@app.route("/transcribe", methods=["POST"])
def transcribe_audio():
    """
    Ez a végpont a form által küldött adatokat dolgozza fel.
    """
    # Olvassuk ki az API kulcsot a formból
    api_key = request.form.get('api_key')
    if not api_key:
        return jsonify({"error": "Az API kulcs megadása kötelező."}), 400

    # Ellenőrizzük, hogy a kérés tartalmaz-e fájlt
    if 'file' not in request.files:
        return jsonify({"error": "Nincs fájl a kérésben."}), 400

    audio_file = request.files['file']

    # Ellenőrizzük, hogy a fájlnév nem üres-e
    if audio_file.filename == '':
        return jsonify({"error": "Nincs kiválasztott fájl."}), 400

    try:
        # A ConnectionSettings objektumot minden kérésnél újra létrehozzuk
        # azzal az API kulccsal, amit a felhasználó a formban megadott.
        sm_settings = ConnectionSettings(
            url="https://asr.api.speechmatics.com/v2",
            auth_token=api_key,
        )

        # A 'with' blokk gondoskodik a kliens erőforrásainak megfelelő lezárásáról
        with BatchClient(sm_settings) as client:
            conf = TranscriptionConfig(language="hu")

            job_id = client.submit_job(
                audio=audio_file,
                transcription_config=conf,
            )

            # Sikeres esetben adjuk vissza a job azonosítóját
            return jsonify({
                "message": "Fájl sikeresen feltöltve, az átírás elindult.",
                "job_id": job_id
            }), 202

    except Exception as e:
        # A valós hiba a szerver oldali logban fog látszani.
        # A felhasználónak csak egy általános hibaüzenetet mutatunk.
        app.logger.error(f"Speechmatics hiba: {e}")
        return jsonify({"error": "Hiba történt az átírás során. Ellenőrizd az API kulcs helyességét."}), 500


# Indítás helyi teszteléshez
if __name__ == "__main__":
    app.run(debug=True)
