import logging
import os
import threading

from flask import Flask, abort, jsonify, request, send_file, send_from_directory

import config
from services.pipeline import JOBS, new_job, run_pipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder="static", static_url_path="")
app.config["SECRET_KEY"] = config.FLASK_SECRET_KEY


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/generate", methods=["POST"])
def api_generate():
    data = request.get_json(silent=True) or {}
    topic = (data.get("topic") or "").strip()

    if not topic:
        return jsonify({"error": "주제(topic)를 입력해주세요."}), 400
    if len(topic) > 200:
        return jsonify({"error": "주제는 200자 이내로 입력해주세요."}), 400

    job_id = new_job()
    thread = threading.Thread(target=run_pipeline, args=(job_id, topic), daemon=True)
    thread.start()

    return jsonify({"job_id": job_id}), 202


@app.route("/api/status/<job_id>", methods=["GET"])
def api_status(job_id):
    job = JOBS.get(job_id)
    if job is None:
        return jsonify({"error": "존재하지 않는 job_id 입니다."}), 404

    scenes = [
        {
            **scene,
            "image_url": f"/api/media/{job_id}/{scene['image_file']}",
            "video_url": f"/api/media/{job_id}/{scene['video_file']}",
        }
        for scene in job["scenes"]
    ]

    return jsonify({
        "status": job["status"],
        "stage": job["stage"],
        "progress": job["progress"],
        "message": job["message"],
        "error": job["error"],
        "title": job["title"],
        "full_script": job["full_script"],
        "scenes": scenes,
        "zip_url": f"/api/download/{job_id}" if job["status"] == "done" else None,
    })


@app.route("/api/media/<job_id>/<path:filename>", methods=["GET"])
def api_media(job_id, filename):
    job = JOBS.get(job_id)
    if job is None:
        abort(404)
    job_dir = os.path.join(config.OUTPUT_DIR, job_id)
    return send_from_directory(job_dir, filename)


@app.route("/api/download/<job_id>", methods=["GET"])
def api_download(job_id):
    job = JOBS.get(job_id)
    if job is None:
        return jsonify({"error": "존재하지 않는 job_id 입니다."}), 404
    if job["status"] != "done" or not job["zip_path"] or not os.path.exists(job["zip_path"]):
        return jsonify({"error": "아직 산출물이 준비되지 않았습니다."}), 409

    return send_file(job["zip_path"], as_attachment=True, download_name=f"sources_{job_id}.zip")


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "찾을 수 없는 경로입니다."}), 404


@app.errorhandler(500)
def server_error(e):
    logger.exception("서버 내부 오류")
    return jsonify({"error": "서버 내부 오류가 발생했습니다."}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.PORT, debug=config.FLASK_DEBUG)
