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
