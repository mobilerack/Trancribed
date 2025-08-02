import os
from flask import Flask, request, jsonify, render_template

# A szükséges Speechmatics modulok importálása
from speechmatics.batch_client import BatchClient
from speechmatics.models import ConnectionSettings, TranscriptionConfig

# Flask alkalmazás létrehozása
app = Flask(__name__)


@app.route("/")
def index():
    """
    A főoldal, ami betölti a 'templates/index.html' fájlt.
    Ez a HTML fájl tartalmazza a feltöltő űrlapot.
    """
    return render_template("index.html")


@app.route("/transcribe", methods=["POST"])
def transcribe_audio():
    """
    Fogadja az űrlapról beküldött API kulcsot és hangfájlt,
    majd elindítja az átírási folyamatot.
    """
    # Adatok kiolvasása a beküldött űrlapból
    api_key = request.form.get('api_key')
    audio_file = request.files.get('file')

    # Ellenőrzés: Az API kulcs megadása kötelező
    if not api_key:
        return jsonify({"error": "Az API kulcs megadása kötelező."}), 400

    # Ellenőrzés: Fájl feltöltése kötelező
    if not audio_file:
        return jsonify({"error": "Nincs feltöltött fájl."}), 400

    try:
        # 1. Kapcsolati beállítások létrehozása minden kérésnél,
        #    a felhasználó által frissen megadott API kulccsal.
        settings = ConnectionSettings(
            url="https://asr.api.speechmatics.com/v2",
            auth_token=api_key,
        )

        # 2. A kliens létrehozása a 'with' blokkon belül,
        #    amely biztosítja az erőforrások megfelelő kezelését.
        with BatchClient(settings) as client:
            # Átírási konfiguráció (pl. nyelv beállítása)
            config = TranscriptionConfig(language="hu")

            # A feladat elküldése a Speechmatics felé
            job_id = client.submit_job(
                audio=audio_file,
                transcription_config=config,
            )

        # Sikeres feladatküldés esetén visszaadjuk a feladat azonosítóját
        return jsonify({
            "message": "Feladat sikeresen elküldve.",
            "job_id": job_id
        }), 202

    except Exception as e:
        # Hiba esetén naplózzuk a pontos hibaüzenetet a szerver oldalon,
        # és egy általános hibaüzenetet küldünk vissza a felhasználónak.
        app.logger.error(f"Speechmatics API hiba: {e}")
        return jsonify({"error": "Hiba történt az átírás során. Ellenőrizze az API kulcs helyességét."}), 500


# Alkalmazás indítása helyi fejlesztéshez
if __name__ == "__main__":
    app.run(debug=True)
