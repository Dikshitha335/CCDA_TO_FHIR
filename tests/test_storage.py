import json
import os

from ccda2fhir import load_config
from ccda2fhir.storage import Storage, process_file

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
XML = open(os.path.join(ROOT, "samples", "sample_ccda.xml"), "rb").read()
CFG = load_config(os.path.join(ROOT, "config"))


def test_process_saves_bundle_with_local_source(tmp_path):
    st = Storage(tmp_path)
    path = st.save_input("a.xml", XML)
    info, bundle = process_file(path, CFG, st)
    saved = json.loads((st.output / "a.bundle.json").read_text())
    assert info["status"] == "processed" and saved["meta"]["source"] == path.resolve().as_uri()
    assert saved["meta"]["tag"][0]["code"] == "EXL"
    assert st.list_bundles()[0]["resourceCount"] == 14 and st.list_inputs()[0]["status"] == "processed"


def test_gcs_style_source_base(tmp_path):
    st = Storage(tmp_path, "gs://my-bucket/ccda/")
    path = st.save_input("a.xml", XML)
    assert process_file(path, CFG, st)[1]["meta"]["source"] == "gs://my-bucket/ccda/a.xml"


def test_failed_and_pending_and_name_collision(tmp_path):
    st = Storage(tmp_path)
    bad = st.save_input("bad.xml", b"<x/>")
    assert process_file(bad, CFG, st)[0]["status"] == "failed"
    (st.input / "dropped.xml").write_bytes(XML)
    status = {r["name"]: r["status"] for r in st.list_inputs()}
    assert status == {"bad.xml": "failed", "dropped.xml": "pending"}
    a, b = st.save_input("same.xml", XML), st.save_input("same.xml", XML + b" ")
    assert a != b and st.save_input("same.xml", XML) == a
