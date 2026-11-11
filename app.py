"""Web app: upload C-CDA files, convert to FHIR R5 Bundles, browse inputs and bundles.

Uploaded files are saved to data/input/, bundles to data/output/ (override with CCDA_DATA_DIR).
Set CCDA_SOURCE_BASE (e.g. gs://my-bucket/ccda/) to write that prefix into meta.source
instead of a local file:// URI.
"""
import os
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory

from ccda2fhir import ConfigError, load_config, split_bundle
from ccda2fhir.storage import Storage, process_file

BASE = Path(__file__).resolve().parent
CONFIG_DIR = os.environ.get("CCDA_CONFIG_DIR", str(BASE / "config"))
store = Storage(os.environ.get("CCDA_DATA_DIR", str(BASE / "data")), os.environ.get("CCDA_SOURCE_BASE"))

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_UPLOAD_MB", "50")) * 1024 * 1024


def _cfg():
    return load_config(CONFIG_DIR)  # re-read per request: new YAML files apply without a restart


@app.get("/")
def index():
    return send_from_directory(BASE / "static", "index.html")


@app.get("/api/sample")
def sample():
    return send_from_directory(BASE / "samples", "sample_ccda.xml", mimetype="application/xml")


@app.get("/api/config")
def config_info():
    return jsonify(mappings=[{"file": m["_file"], "resource": m["resource"], "profile": m.get("profile")}
                             for m in _cfg()["mappings"]])


@app.post("/api/convert")
def api_convert():
    files = request.files.getlist("files")
    if not files:
        return jsonify(error="No files uploaded"), 400
    cfg, results = _cfg(), []
    for f in files:
        path = store.save_input(f.filename, f.read())
        info, bundle = process_file(path, cfg, store)
        if bundle:
            info["bundle"], info["resources"] = bundle, split_bundle(bundle)
        results.append(info)
    return jsonify(results=results)


@app.post("/api/process")
def api_process():
    """Process files already in input/. Body: {"names": [...]} or {} for every pending file."""
    names = (request.get_json(silent=True) or {}).get("names")
    cfg, out = _cfg(), []
    for row in store.list_inputs():
        wanted = row["name"] in names if names else row["status"] == "pending"
        if wanted and Path(row["path"]).is_file():
            out.append(process_file(row["path"], cfg, store)[0])
    return jsonify(results=out)


@app.get("/api/inputs")
def list_inputs():
    return jsonify(location=str(store.input), items=store.list_inputs())


@app.get("/api/bundles")
def list_bundles():
    return jsonify(location=str(store.output), items=store.list_bundles())


@app.get("/api/inputs/<name>")
def get_input(name):
    row = next((r for r in store.list_inputs() if r["name"] == name), None)
    if not row or not Path(row["path"]).is_file():
        return jsonify(error="Not found"), 404
    return send_file(row["path"], mimetype="application/xml", as_attachment=request.args.get("download") == "1")


@app.get("/api/bundles/<name>")
def get_bundle(name):
    path = store.output / name
    if Path(name).name != name or not path.is_file():
        return jsonify(error="Not found"), 404
    return send_file(path, mimetype="application/fhir+json", as_attachment=request.args.get("download") == "1")


@app.errorhandler(ConfigError)
def bad_config(exc):
    return jsonify(error=f"Config error: {exc}"), 500


@app.errorhandler(413)
def too_large(_):
    return jsonify(error="Upload too large"), 413


if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "5000")))
