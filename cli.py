#!/usr/bin/env python3
"""Batch CLI: python cli.py docs/*.xml [--split]

Bundles go to <data-dir>/output/. meta.source is the real location of each input file
(or CCDA_SOURCE_BASE + file name if that is set).
"""
import argparse
import json
import os
import sys
from pathlib import Path

from ccda2fhir import ConfigError, load_config, split_bundle
from ccda2fhir.storage import Storage, process_file

HERE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser(description="Convert C-CDA XML files to FHIR R5 Bundles")
    ap.add_argument("files", nargs="+", help="C-CDA XML files")
    ap.add_argument("-d", "--data-dir", default=os.environ.get("CCDA_DATA_DIR", str(HERE / "data")))
    ap.add_argument("-c", "--config", default=str(HERE / "config"), help="YAML mapping folder")
    ap.add_argument("--split", action="store_true", help="also write one JSON file per resource")
    args = ap.parse_args()
    store = Storage(args.data_dir, os.environ.get("CCDA_SOURCE_BASE"))
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        sys.exit(f"Config error: {exc}")
    failed = 0
    for f in args.files:
        info, bundle = process_file(f, cfg, store)
        if not bundle:
            print(f"FAIL {f}: {info['error']}", file=sys.stderr)
            failed += 1
            continue
        if args.split:
            folder = store.output / Path(f).stem
            folder.mkdir(exist_ok=True)
            for res in split_bundle(bundle):
                (folder / f"{res['resourceType']}-{res['id']}.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
        print(f"OK   {f} -> {info['savedTo']} ({info['resourceCount']} resources)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
