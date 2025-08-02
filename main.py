import os
import time  # Időzítés importálása a szimulációhoz
from flask import Flask, request, render_template, Response

# A szükséges Speechmatics modulok importálása
from speechmatics.batch_client import BatchClient
from speechmatics.models import ConnectionSettings, TranscriptionConfig

# Flask alkalmazás létrehozása
app = Flask(__name__)


@app.route("/")
def index():
    """ A főoldal, ami betölti a 'templates/index.html' fájlt. """
    return render_template("index.html")


@app.route("/transcribe", methods=["POST"])
def transcribe_audio():
    """
    Fogadja az űrlap adatait és egy eseményfolyamot (logot) küld vissza a böngészőnek.
    """
    # A 'yield' kulcsszó miatt ez a funkció egy "generátor" lesz.
    # Minden 'yield' egy újabb adatcsomagot küld a nyitva tartott kapcsolaton.
    def generate_log_stream():
        try:
            # --- 1. Adatok beolvasása és validálása ---
            api_key = request.form.get('api_key')
            audio_file = request.files.get('file')
            
            yield "data: Napló indítása...\n\n"
            time.sleep(0.5)

            if not api_key:
                yield "data: Hiba: Az API kulcs megadása kötelező.\n\n"
                return  # Leállítjuk a folyamatot

            if not audio_file:
                yield "data: Hiba: Nincs feltöltött fájl.\n\n"
                return

            yield f"data: Fájl fogadva: {audio_file.filename}\n\n"
            time.sleep(0.5)

            # --- 2. Kapcsolódás a Speechmaticshez ---
            yield "data: Kapcsolódás a Speechmatics API-hoz...\n\n"
            time.sleep(0.5)

            settings = ConnectionSettings(
                url="https://asr.api.speechmatics.com/v2",
                auth_token=api_key,
            )

            with BatchClient(settings) as client:
                yield "data: Kapcsolat sikeres. Feladat elküldése...\n\n"
                time.sleep(1)

                config = TranscriptionConfig(language="hu")

                job_id = client.submit_job(
                    audio=audio_file,
                    transcription_config=config,
                )

                yield f"data: Feladat sikeresen elküldve! Job ID: {job_id}\n\n"
                time.sleep(0.5)
                yield "data: KÉSZ! A folyamat befejeződött.\n\n"

        except Exception as e:
            # Hiba esetén a pontos hibaüzenetet is beírjuk a logba
            app.logger.error(f"Speechmatics API hiba: {e}")
            yield f"data: Hiba történt: {e}\n\n"
            yield "data: A folyamat hibával leállt.\n\n"

    # A Flask Response objektumot a generátorral hozzuk létre.
    # A 'text/event-stream' mimetype jelzi a böngészőnek, hogy SSE kapcsolatról van szó.
    return Response(generate_log_stream(), mimetype='text/event-stream')


# Alkalmazás indítása helyi fejlesztéshez
if __name__ == "__main__":
    app.run(debug=True)

