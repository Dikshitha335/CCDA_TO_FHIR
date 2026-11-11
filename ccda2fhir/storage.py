"""Local folder storage laid out like a GCS bucket.

data/input/   C-CDA files (uploaded, or dropped here by hand)
data/output/  generated Bundles, <input name>.bundle.json
data/status/  one small JSON per input file recording the result of processing
"""
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from werkzeug.utils import secure_filename

from .converter import ConversionError, convert


def _iso(ts=None):
    d = datetime.fromtimestamp(ts, timezone.utc) if ts else datetime.now(timezone.utc)
    return d.isoformat(timespec="seconds").replace("+00:00", "Z")


def _atomic_write(path, data):
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)


class Storage:
    def __init__(self, root, source_base=None):
        """source_base: optional prefix such as gs://my-bucket/ccda/ used for meta.source."""
        self.root = Path(root).resolve()
        self.input, self.output, self.status = (self.root / n for n in ("input", "output", "status"))
        for d in (self.input, self.output, self.status):
            d.mkdir(parents=True, exist_ok=True)
        self.source_base = source_base

    def source_uri(self, path):
        """The value written to meta.source: a file:// URI, or source_base + relative path."""
        path = Path(path).resolve()
        if self.source_base:
            try:
                rel = path.relative_to(self.input).as_posix()
            except ValueError:
                rel = path.name
            return self.source_base.rstrip("/") + "/" + rel
        return path.as_uri()

    def save_input(self, filename, data):
        name = secure_filename(filename or "") or "upload.xml"
        dest = self.input / name
        if dest.exists() and dest.read_bytes() != data:  # same name, different content
            dest = dest.with_name(f"{dest.stem}-{hashlib.sha1(data).hexdigest()[:8]}{dest.suffix}")
        if not dest.exists():
            _atomic_write(dest, data)
        return dest

    def save_bundle(self, input_path, bundle):
        out = self.output / f"{Path(input_path).stem}.bundle.json"
        _atomic_write(out, json.dumps(bundle, indent=2).encode("utf-8"))
        return out

    def record(self, path, **info):
        path = Path(path)
        st = path.stat()
        row = {"name": path.name, "path": str(path), "size": st.st_size, "updated": _iso(st.st_mtime),
               "processedAt": _iso(), **info}
        _atomic_write(self.status / (path.name + ".json"), json.dumps(row).encode("utf-8"))
        return row

    def _statuses(self):
        rows = []
        for p in self.status.glob("*.json"):
            try:
                rows.append(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass
        return rows

    def list_inputs(self):
        """Every processed input, plus files sitting in input/ that are still pending."""
        rows = {s["name"]: s for s in self._statuses()}
        for p in self.input.iterdir():
            if p.is_file() and p.name not in rows:
                st = p.stat()
                rows[p.name] = {"name": p.name, "path": str(p), "size": st.st_size, "status": "pending",
                                "updated": _iso(st.st_mtime), "source": self.source_uri(p)}
        return sorted(rows.values(), key=lambda r: r.get("updated", ""), reverse=True)

    def list_bundles(self):
        by_bundle = {s["bundle"]: s for s in self._statuses() if s.get("bundle")}
        items = []
        for p in self.output.glob("*.json"):
            st, s = p.stat(), by_bundle.get(p.name, {})
            items.append({"name": p.name, "path": str(p), "size": st.st_size, "updated": _iso(st.st_mtime),
                          "resourceCount": s.get("resourceCount"), "source": s.get("source"), "input": s.get("name")})
        return sorted(items, key=lambda r: r["updated"], reverse=True)


def process_file(path, cfg, store):
    """Convert one input file, save the Bundle to output/, record the outcome.

    Returns (summary dict, bundle or None). Raises ConfigError if the YAML config is broken.
    """
    path = Path(path)
    source = store.source_uri(path)
    base = {"name": path.name, "source": source, "inputPath": str(path)}
    try:
        bundle = convert(path.read_bytes(), cfg, source=source)
    except (ConversionError, OSError) as exc:
        store.record(path, status="failed", error=str(exc), source=source)
        return {**base, "status": "failed", "error": str(exc)}, None
    out = store.save_bundle(path, bundle)
    count = len(bundle["entry"])
    store.record(path, status="processed", bundle=out.name, savedTo=str(out), resourceCount=count, source=source)
    return {**base, "status": "processed", "bundleFile": out.name, "savedTo": str(out), "resourceCount": count}, bundle
