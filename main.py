import os
import json
import tempfile
import requests
import yt_dlp
from flask import Flask, request, jsonify, send_file, render_template

app = Flask(__name__, static_folder="static", template_folder="templates")

SPEECHMATICS_BASE = "https://asr.api.speechmatics.com/v2"


def safe_filename(name: str, default="subtitle"):
    if not name:
        return default
    # egyszerű tisztítás: szóköz -> _, tiltottak ki
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name).strip("_.")
    return safe or default


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/process-page-url", methods=["POST"])
def process_page_url():
    """
    1) yt-dlp-vel metaadatok + közvetlen stream URL kinyerése (univerzális: YT, Pornhub, stb.)
    2) Speechmatics transcribe indítása a kiválasztott nyelvvel
    3) Visszaadjuk a job_id-t és a javasolt SRT fájlnevet (videó címe alapján)
    """
    try:
        data = request.get_json(force=True)
        page_url = data.get("page_url")
        api_key = data.get("apiKey")
        language = data.get("language", "en")

        if not page_url or not api_key:
            return jsonify({"error": "Hiányzó paraméter(ek): page_url, apiKey"}), 400

        # 1) Videó URL + cím kinyerése
        ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True, "format": "bestaudio/best"}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(page_url, download=False)

        direct_media_url = info.get("url")
        title = info.get("title") or "video"
        filename = f"{safe_filename(title)}.srt"

        if not direct_media_url:
            return jsonify({"error": "Nem sikerült közvetlen média URL-t kinyerni."}), 500

        # 2) Speechmatics job indítása
        headers = {"Authorization": f"Bearer {api_key}"}
        payload = {
            "type": "transcription",
            "transcription_config": {"language": language},
            "fetch_data": {"url": direct_media_url},  # fontos: fetch_data objektum
        }
        resp = requests.post(f"{SPEECHMATICS_BASE}/jobs", headers=headers, json=payload)

        if resp.status_code not in (200, 201):
            # próbáljuk érthető hibával visszaadni
            try:
                return jsonify({"error": resp.json()}), resp.status_code
            except Exception:
                return jsonify({"error": resp.text}), resp.status_code

        job_id = resp.json().get("id")
        return jsonify({"job_id": job_id, "filename": filename})

    except Exception as e:
        return jsonify({"error": f"Szerver hiba: {e}"}), 500


@app.route("/transcription-status/<job_id>")
def transcription_status(job_id):
    """
    Speechmatics státusz lekérdezés.
    Ha kész, akkor SRT formátumban letöltjük és visszaadjuk a tartalmat.
    """
    try:
        api_key = request.args.get("apiKey")
        if not api_key:
            return jsonify({"error": "Hiányzó API kulcs (apiKey)."}), 400

        headers = {"Authorization": f"Bearer {api_key}"}

        status_resp = requests.get(f"{SPEECHMATICS_BASE}/jobs/{job_id}", headers=headers)
        if status_resp.status_code != 200:
            return jsonify({"error": status_resp.text}), status_resp.status_code

        status_data = status_resp.json()
        status = status_data.get("job", {}).get("status")

        if status == "done":
            srt_resp = requests.get(f"{SPEECHMATICS_BASE}/jobs/{job_id}/transcript?format=srt", headers=headers)
            if srt_resp.status_code != 200:
                return jsonify({"error": srt_resp.text}), srt_resp.status_code

            return jsonify({"status": "done", "srt_content": srt_resp.text})

        elif status in ("error", "rejected"):
            err_msg = status_data.get("job", {}).get("errors", [{}])[0].get("message", "A feladat sikertelen.")
            return jsonify({"status": "error", "error": err_msg})

        else:
            return jsonify({"status": status})

    except Exception as e:
        return jsonify({"error": f"Szerver hiba: {e}"}), 500


@app.route("/translate", methods=["POST"])
def translate():
    """
    Placeholder fordítás endpoint – a beküldött szöveget visszaadja címkézve.
    Ha tényleges Gemini integráció kell, külön megírom (API kulcs, modellek, stb.).
    """
    try:
        srt_text = request.form.get("srtText")
        gemini_key = request.form.get("geminiApiKey")
        target_lang = request.form.get("targetLanguage", "magyar")

        if not srt_text or not gemini_key:
            return jsonify({"error": "Hiányzó SRT vagy Gemini API kulcs."}), 400

        translated = f"[{target_lang} fordítás]\n{srt_text}"
        return jsonify({"translated_text": translated})
    except Exception as e:
        return jsonify({"error": f"Szerver hiba: {e}"}), 500


@app.route("/get-download-links", methods=["POST"])
def get_download_links():
    """
    yt-dlp-vel a lehetséges letöltési formátumok listázása.
    """
    try:
        data = request.get_json(force=True)
        page_url = data.get("page_url")
        if not page_url:
            return jsonify({"error": "Hiányzó URL."}), 400

        ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(page_url, download=False)

        formats = []
        for f in info.get("formats", []):
            if not f.get("url"):
                continue
            formats.append({
                "url": f.get("url"),
                "ext": f.get("ext"),
                "resolution": f.get("resolution") or f.get("format_note"),
                "filesize": f.get("filesize") or f.get("filesize_approx"),
                "note": f.get("format_note") or f.get("format"),
            })
        return jsonify(formats)
    except Exception as e:
        return jsonify({"error": f"Linkek lekérése sikertelen: {e}"}), 500


@app.route("/download-srt", methods=["POST"])
def download_srt():
    """
    SRT fájl letöltése szerveren keresztül (ha nem akarsz client-oldalon menteni).
    A kliens átadja az SRT szöveget és a fájlnevet.
    """
    try:
        data = request.get_json(force=True)
        srt_text = data.get("srtText")
        filename = safe_filename(data.get("videoTitle") or "subtitle") + ".srt"

        if not srt_text:
            return jsonify({"error": "Nincs SRT szöveg."}), 400

        tmp_path = os.path.join(tempfile.gettempdir(), filename)
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(srt_text)

        return send_file(tmp_path, as_attachment=True, download_name=filename, mimetype="text/plain")
    except Exception as e:
        return jsonify({"error": f"Letöltés hiba: {e}"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
