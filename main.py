# Keresd meg a `main.py` fájlodban a `/start-transcription-from-url` végpontot,
# és cseréld le a teljes funkciót erre a javított verzióra.

@app.route('/start-transcription-from-url', methods=['POST'])
def start_transcription_from_url():
    """
    Fogad egy URL-t, és elindítja az átírást.
    JAVÍTVA: Az URL-t a Speechmatics által elvárt szótár formátumban adja tovább.
    """
    try:
        # Adatok beolvasása a kérésből
        data = request.get_json()
        if not data:
            return jsonify({"error": "Érvénytelen kérés formátum."}), 400

        url = data.get('url')
        api_key = data.get('apiKey')
        language = data.get('language', 'hu') # Alapértelmezett nyelv, ha nincs megadva

        if not all([url, api_key]):
            return jsonify({"error": "Hiányzó URL vagy API kulcs."}), 400

        # Kapcsolati beállítások létrehozása
        settings = ConnectionSettings(
            url="https://asr.api.speechmatics.com/v2",
            auth_token=api_key
        )

        # Átírási konfiguráció
        transcription_config = {
            "language": language
        }
        
        # JAVÍTÁS ITT:
        # A `fetch_data` szótárba csomagoljuk az URL-t, ahogy az API elvárja.
        fetch_data = {
            "url": url
        }

        with BatchClient(settings) as client:
            job_id = client.submit_job(
                audio=fetch_data,  # Itt már a helyes formátumot adjuk át
                transcription_config=transcription_config,
            )

        return jsonify({"job_id": job_id}), 200

    except HTTPStatusError as e:
        # Részletesebb hibaüzenet a Speechmatics-től
        error_details = e.response.json().get("detail") or "Ismeretlen API hiba"
        app.logger.error(f"Speechmatics API hiba (HTTPStatusError): {error_details}")
        return jsonify({"error": error_details}), e.response.status_code
    except Exception as e:
        # Általános szerverhiba naplózása
        app.logger.error(f"Ismeretlen hiba az URL átírás közben: {e}")
        return jsonify({"error": "Ismeretlen szerveroldali hiba történt."}), 500


