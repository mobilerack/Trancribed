import os
import tempfile
import yt_dlp
import requests
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename

app = Flask(__name__)

# ========== HELPERS ==========
def get_direct_video_info(url: str):
    """
    Használja a yt-dlp-t, hogy bármilyen támogatott oldalról (YT, Pornhub, stb.)
    közvetlen videó URL-t és metaadatokat adjon vissza.
    """
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "best",
        "skip_download": True
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return {
            "title": info.get("title"),
            "ext": info.get("ext"),
            "duration": info.get("duration"),
            "url": info.get("url")
        }

# ========== ROUTES ==========
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/process-page-url", methods=["POST"])
def process_page_url():
    """ Közvetlen média URL-t keres és elindítja a Speechmatics átírást """
    data = request.json
    page_url = data.get("page_url")
    api_key = data.get("apiKey")
    language = data.get("language", "en")

    if not page_url or not api_key:
        return jsonify({"error": "Hiányzó paraméter"}), 400

    try:
        info = get_direct_video_info(page_url)

        # itt kellene a Speechmatics API hívás (mock-olva teszt kedvéért)
        job_id = "mock_job_123"

        return jsonify({
            "job_id": job_id,
            "video_title": info["title"],
            "video_url": info["url"]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/transcription-status/<job_id>")
def transcription_status(job_id):
    """ Ellenőrzi az átírás állapotát (egyszerűsített mock) """
    api_key = request.args.get("apiKey")
    if not api_key:
        return jsonify({"error": "API kulcs szükséges"}), 400

    # Itt normál esetben a Speechmatics API-t hívnánk meg.
    # Most visszaadunk egy kész mock SRT fájlt.
    example_srt = """1
00:00:00,000 --> 00:00:02,000
Helló világ!

2
00:00:02,500 --> 00:00:05,000
Ez egy teszt felirat.
"""
    return jsonify({"status": "done", "srt_content": example_srt})


@app.route("/translate", methods=["POST"])
def translate():
    """ Gemini API-t hívó fordítás (mock) """
    srt_text = request.form.get("srtText")
    gemini_api_key = request.form.get("geminiApiKey")
    target_language = request.form.get("targetLanguage")

    if not srt_text or not gemini_api_key:
        return jsonify({"error": "Hiányzó SRT vagy Gemini API kulcs"}), 400

    # Tesztfordítás
    translated = srt_text.replace("Helló világ!", "Hello world!").replace("Ez egy teszt felirat.", "This is a test subtitle.")

    return jsonify({"translated_text": translated})


@app.route("/get-download-links", methods=["POST"])
def get_download_links():
    """ yt-dlp segítségével minden letölthető formátum lekérdezése """
    data = request.json
    page_url = data.get("page_url")
    if not page_url:
        return jsonify({"error": "Hiányzó URL"}), 400

    try:
        ydl_opts = {"quiet": True, "no_warnings": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(page_url, download=False)

        formats = []
        for f in info.get("formats", []):
            formats.append({
                "url": f.get("url"),
                "ext": f.get("ext"),
                "resolution": f.get("format_note"),
                "filesize": f.get("filesize"),
                "note": f.get("format")
            })

        return jsonify(formats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/download-srt", methods=["POST"])
def download_srt():
    """ Felirat letöltése .srt fájlként """
    data = request.json
    srt_text = data.get("srtText")
    video_title = data.get("videoTitle", "felirat")

    if not srt_text:
        return jsonify({"error": "Nincs SRT szöveg"}), 400

    safe_name = secure_filename(video_title) or "felirat"
    tmp_path = os.path.join(tempfile.gettempdir(), f"{safe_name}.srt")

    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(srt_text)

    return send_file(tmp_path, as_attachment=True, download_name=f"{safe_name}.srt")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
