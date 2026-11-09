#!/usr/bin/env python3
"""Batch CLI: python cli.py docs/*.xml -o out/ [--split]"""
import argparse
import json
import os
import sys

from ccda2fhir import ConfigError, ConversionError, convert, load_config, split_bundle

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser(description="Convert C-CDA XML files to FHIR R5 Bundles")
    ap.add_argument("files", nargs="+", help="C-CDA XML files")
    ap.add_argument("-o", "--out", default="out", help="output folder (default: out)")
    ap.add_argument("-c", "--config", default=os.path.join(HERE, "config"), help="YAML mapping folder")
    ap.add_argument("--split", action="store_true", help="also write one JSON file per resource")
    args = ap.parse_args()
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        sys.exit(f"Config error: {exc}")
    os.makedirs(args.out, exist_ok=True)
    failed = 0
    for path in args.files:
        stem = os.path.splitext(os.path.basename(path))[0]
        try:
            with open(path, "rb") as fh:
                bundle = convert(fh.read(), cfg)
        except (ConversionError, ConfigError, OSError) as exc:
            print(f"FAIL {path}: {exc}", file=sys.stderr)
            failed += 1
            continue
        with open(os.path.join(args.out, f"{stem}.bundle.json"), "w", encoding="utf-8") as fh:
            json.dump(bundle, fh, indent=2)
        if args.split:
            folder = os.path.join(args.out, stem)
            os.makedirs(folder, exist_ok=True)
            for res in split_bundle(bundle):
                name = f"{res['resourceType']}-{res['id']}.json"
                with open(os.path.join(folder, name), "w", encoding="utf-8") as fh:
                    json.dump(res, fh, indent=2)
        print(f"OK   {path}: {len(bundle['entry'])} resources")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
