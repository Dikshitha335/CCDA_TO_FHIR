"""Web app: upload C-CDA files, view the FHIR R5 Bundle and the split resources.

Uploads are converted in memory; nothing is written to disk or logged.
"""
import os

from flask import Flask, jsonify, request, send_from_directory

from ccda2fhir import ConfigError, ConversionError, convert, load_config, split_bundle

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.environ.get("CCDA_CONFIG_DIR", os.path.join(BASE, "config"))

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_UPLOAD_MB", "50")) * 1024 * 1024


@app.get("/")
def index():
    return send_from_directory(os.path.join(BASE, "static"), "index.html")


@app.get("/api/sample")
def sample():
    return send_from_directory(os.path.join(BASE, "samples"), "sample_ccda.xml", mimetype="application/xml")


@app.get("/api/config")
def config_info():
    """List the active mappings (re-read from disk on every call)."""
    try:
        cfg = load_config(CONFIG_DIR)
    except ConfigError as exc:
        return jsonify(error=str(exc)), 500
    return jsonify(mappings=[{"file": m["_file"], "resource": m["resource"], "profile": m.get("profile")}
                             for m in cfg["mappings"]])


@app.post("/api/convert")
def api_convert():
    files = request.files.getlist("files")
    if not files:
        return jsonify(error="No files uploaded"), 400
    try:
        cfg = load_config(CONFIG_DIR)  # reloaded per request: new YAML files apply without a restart
    except ConfigError as exc:
        return jsonify(error=f"Config error: {exc}"), 500
    results = []
    for f in files:
        try:
            bundle = convert(f.read(), cfg)
            results.append({"name": f.filename, "bundle": bundle, "resources": split_bundle(bundle)})
        except (ConversionError, ConfigError) as exc:
            results.append({"name": f.filename, "error": str(exc)})
    return jsonify(results=results)


@app.errorhandler(413)
def too_large(_):
    return jsonify(error="Upload too large"), 413


if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "5000")))
