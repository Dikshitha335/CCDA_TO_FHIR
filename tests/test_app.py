import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app  # noqa: E402

SAMPLE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples", "sample_ccda.xml")


def test_convert_endpoint():
    c = app.test_client()
    with open(SAMPLE, "rb") as fh:
        data = {"files": [(fh, "a.xml"), (io.BytesIO(b"<x/>"), "bad.xml")]}
        r = c.post("/api/convert", data=data, content_type="multipart/form-data")
    j = r.get_json()["results"]
    assert r.status_code == 200 and len(j[0]["resources"]) == 14 and "error" in j[1]


def test_pages():
    c = app.test_client()
    assert c.get("/").status_code == 200
    assert c.get("/api/sample").status_code == 200
    assert c.post("/api/convert").status_code == 400


def test_lists_open_and_process():
    c = app.test_client()
    with open(SAMPLE, "rb") as fh:
        c.post("/api/convert", data={"files": (fh, "listed.xml")}, content_type="multipart/form-data")
    names = [r["name"] for r in c.get("/api/inputs").get_json()["items"]]
    assert "listed.xml" in names
    b = next(r for r in c.get("/api/bundles").get_json()["items"] if r["name"] == "listed.bundle.json")
    assert b["resourceCount"] == 14 and b["source"].startswith("file:")
    assert c.get("/api/bundles/listed.bundle.json").get_json()["meta"]["tag"][0]["code"] == "EXL"
    assert c.get("/api/bundles/..%2Fapp.py").status_code == 404
    assert c.get("/api/inputs/nope.xml").status_code == 404
    from app import store
    (store.input / "dropped.xml").write_bytes(open(SAMPLE, "rb").read())
    r = c.post("/api/process", json={}).get_json()["results"]
    assert [x["name"] for x in r] == ["dropped.xml"] and r[0]["status"] == "processed"
