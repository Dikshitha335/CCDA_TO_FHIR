"""C-CDA -> FHIR R5 conversion engine.

The engine contains no resource-specific logic. Every mapping lives in the YAML
files under config/ (see README, "Adding a resource").
"""
import glob
import hashlib
import os
import re
from datetime import datetime, timezone
from xml.etree.ElementTree import ParseError

import yaml
from defusedxml import ElementTree as DET
from defusedxml.common import DefusedXmlException


class ConversionError(Exception):
    """The input document could not be converted."""


class ConfigError(Exception):
    """A YAML mapping file is invalid."""


_SEG = re.compile(r"^([\w*]+)(?:\[(\w+)=([^\]]+)\])?$")
_DATE = re.compile(r"^(\d{4})(\d\d)?(\d\d)?(\d\d)?(\d\d)?(\d\d)?(?:\.\d+)?([+-]\d\d)?(\d\d)?$")


def load_config(config_dir):
    """Read every *.yaml in config_dir; mappings run in (order, filename) order."""
    cfg = {"systems": {}, "maps": {}, "meta": {}, "mappings": []}
    loaded = []
    for path in glob.glob(os.path.join(config_dir, "*.y*ml")):
        name = os.path.basename(path)
        try:
            with open(path, encoding="utf-8") as fh:
                doc = yaml.safe_load(fh) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"{name}: {exc}") from exc
        loaded.append((doc.get("order", 500), name, doc))
    for _, name, doc in sorted(loaded, key=lambda x: (x[0], x[1])):
        cfg["systems"].update(doc.get("systems") or {})
        cfg["maps"].update(doc.get("maps") or {})
        cfg["meta"].update(doc.get("meta") or {})
        for m in doc.get("mappings") or []:
            m["_file"] = name
            cfg["mappings"].append(m)
    return cfg


# ---------- XML helpers ----------
def _ln(e):
    return e.tag.rsplit("}", 1)[-1] if isinstance(e.tag, str) else ""


def _text(e):
    return " ".join("".join(e.itertext()).split())


def _select(ctxs, path):
    out, desc = ctxs, False
    for seg in path.split("/"):
        if seg == "":
            desc = True
            continue
        m = _SEG.match(seg)
        if not m:
            raise ConfigError(f"Bad path segment: {seg}")
        name, fa, fv = m.groups()
        nxt = []
        for c in out:
            pool = [e for e in c.iter() if e is not c] if desc else list(c)
            for e in pool:
                if name != "*" and _ln(e) != name:
                    continue
                if fa:
                    if fa == "templateId":
                        ok = any(_ln(x) == "templateId" and x.get("root") == fv for x in e)
                    else:
                        ok = e.get(fa) == fv
                    if not ok:
                        continue
                nxt.append(e)
        out, desc = nxt, False
    return out


def _first(ctx, path):
    if not path:
        return ctx
    found = _select([ctx], path)
    return found[0] if found else None


def _contains(a, b, parent):
    while b is not None:
        if b is a:
            return True
        b = parent.get(b)
    return False


# ---------- value helpers ----------
def _oid(v, cfg):
    return cfg["systems"].get(v) or f"urn:oid:{v}"


def _date(v):
    m = _DATE.match(v)
    if not m:
        return v
    y, mo, d, h, mi, s, tz, tm = m.groups()
    out = y
    if mo:
        out += "-" + mo
    if d:
        out += "-" + d
    if h and tz:  # FHIR requires a time zone whenever a time is present
        out += f"T{h}:{mi or '00'}:{s or '00'}{tz}:{tm or '00'}"
    return out


def _cc(e, cfg):
    if e is None:
        return None
    nodes = [e] + [c for c in e if _ln(c) == "translation"]
    codings = []
    for x in nodes:
        if not x.get("code"):
            continue
        c = {}
        if x.get("codeSystem"):
            c["system"] = _oid(x.get("codeSystem"), cfg)
        c["code"] = x.get("code")
        if x.get("displayName"):
            c["display"] = x.get("displayName")
        codings.append(c)
    return {"coding": codings} if codings else None


def _ref(rtype, ctx, made, parent, one):
    cands = [x for x in made if rtype == "*" or x[0]["resourceType"] == rtype]
    related = [x for x in cands if _contains(x[1], ctx, parent) or _contains(ctx, x[1], parent)]

    def fmt(x):
        return f"{x[0]['resourceType']}/{x[0]['id']}"

    if one:
        pick = (related or cands or [None])[0]
        return fmt(pick) if pick else None
    chosen = cands if rtype == "*" else related
    return [{"reference": fmt(x)} for x in chosen] or None


def _eval(spec, ctx, cfg, made, parent):
    src, *transforms = [s.strip() for s in str(spec).split("|")]
    if src.startswith("cc:"):
        return _cc(_first(ctx, src[3:]), cfg)
    if src.startswith("ref:"):
        return _ref(src[4:], ctx, made, parent, True)
    if src.startswith("refs:"):
        return _ref(src[5:], ctx, made, parent, False)
    path, _, attr = src.partition("@")
    el = _first(ctx, path)
    value = None
    if el is not None:
        value = (el.get(attr) if "@" in src else _text(el)) or None
    for t in transforms:
        name, _, arg = t.partition(":")
        if name == "default":
            value = arg if value is None else value
            continue
        if value is None:
            continue
        if name == "map":
            value = cfg["maps"].get(arg, {}).get(value, value)
        elif name == "oid":
            value = _oid(value, cfg)
        elif name == "tel":
            value = re.sub(r"^tel:", "", value)
        elif name == "num":
            try:
                num = float(value)
                value = int(num) if num == int(num) else num
            except ValueError:
                value = None
        elif name == "date":
            value = _date(value)
        else:
            raise ConfigError(f"Unknown transform '{name}' in '{spec}'")
    return value


def _set_path(obj, path, value):
    toks = [int(b) if b else a for a, b in re.findall(r"([^.\[\]]+)|\[(\d+)\]", path)]
    for i, k in enumerate(toks):
        last = i == len(toks) - 1
        child = None if last else ([] if isinstance(toks[i + 1], int) else {})
        if isinstance(k, int):
            while len(obj) <= k:
                obj.append(None)
            if last:
                obj[k] = value
            else:
                obj[k] = obj[k] if obj[k] is not None else child
                obj = obj[k]
        elif last:
            obj[k] = value
        else:
            obj = obj.setdefault(k, child)


# ---------- public API ----------
def _stamp(meta, cfg, source):
    """Add the configured meta.tag and the meta.source (origin of the file) to a meta dict."""
    tags = (cfg.get("meta") or {}).get("tag")
    if tags:
        meta["tag"] = [dict(t) for t in tags]
    if source:
        meta["source"] = source
    return meta


def convert(xml, cfg, source=None):
    """Convert C-CDA XML (bytes or str) to a FHIR R5 Bundle (dict).

    source: where the input file lives (e.g. file:///... or gs://...); written to meta.source.
    """
    try:
        root = DET.fromstring(xml, forbid_dtd=True)
    except (ParseError, DefusedXmlException) as exc:
        raise ConversionError(f"Invalid or unsafe XML: {exc}") from exc
    if _ln(root) != "ClinicalDocument":
        raise ConversionError("Root element is not ClinicalDocument")
    raw = xml if isinstance(xml, bytes) else xml.encode("utf-8")
    tag = hashlib.sha1(raw).hexdigest()[:8]  # makes ids stable and unique per document
    parent = {c: p for p in root.iter() for c in p}
    made, counts = [], {}
    scopes = (cfg.get("meta") or {}).get("apply_to") or ["bundle", "resources"]
    for m in cfg["mappings"]:
        rtype = m["resource"]
        nodes = [root] if m.get("foreach") == "." else _select([root], m["foreach"])
        for ctx in nodes:
            counts[rtype] = counts.get(rtype, 0) + 1
            res = {"resourceType": rtype, "id": f"{rtype.lower()}-{tag}-{counts[rtype]}"}
            meta = {"profile": [m["profile"]]} if m.get("profile") else {}
            if "resources" in scopes:
                _stamp(meta, cfg, source)
            if meta:
                res["meta"] = meta
            dynamic, constants = set(), []
            for key, spec in (m.get("fields") or {}).items():
                spec, rk = str(spec), re.split(r"[.\[]", key)[0]
                if spec.startswith("="):
                    constants.append((key, spec[1:], rk))
                    continue
                dynamic.add(rk)
                val = _eval(spec, ctx, cfg, made, parent)
                if val is not None:
                    _set_path(res, key, val)
            # a constant is kept only if its parent element received real data
            for key, const, rk in constants:
                if rk not in dynamic or rk in res:
                    _set_path(res, key, {"true": True, "false": False}.get(const, const))
            if any(res.get(k) is None for k in m.get("require") or []):
                continue
            made.append((res, ctx))
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    bundle_meta = {"lastUpdated": now}
    if "bundle" in scopes:
        _stamp(bundle_meta, cfg, source)
    return {
        "resourceType": "Bundle", "id": f"bundle-{tag}", "meta": bundle_meta,
        "type": "collection", "timestamp": now,
        "entry": [{"fullUrl": f"https://example.org/fhir/{r['resourceType']}/{r['id']}", "resource": r}
                  for r, _ in made],
    }


def split_bundle(bundle):
    """Return the individual resources of a Bundle as a list."""
    return [e["resource"] for e in bundle.get("entry", [])]
