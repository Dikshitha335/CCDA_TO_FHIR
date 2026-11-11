# C-CDA to FHIR R5 Converter

Converts C-CDA (CCD) XML documents into FHIR R5 Bundles and splits them into individual
US Core 6.1 resources. Includes a web UI, a REST API and a batch CLI. **All mapping rules
live in YAML files in `config/`**, so new resources are added without touching Python.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py                                          # http://127.0.0.1:5000
```

Open the page, click **Load sample C-CDA** or drop your own `.xml` files. Tabs: Upload,
Bundle output, Individual resources (filter by type, copy or download).

### Batch CLI
```bash
python cli.py docs/*.xml --split              # bundles to data/output/, plus one JSON per resource
```

### Docker
```bash
docker build -t ccda2fhir . && docker run -p 8000:8000 ccda2fhir
```

### REST API
| Method | Path | Description |
|---|---|---|
| POST | `/api/convert` | multipart field `files`. Saves input and bundle, returns `{results:[{name, status, bundle, resources, savedTo, source}]}` |
| POST | `/api/process` | convert files already in `data/input/` (`{"names":[...]}`, or `{}` for all pending) |
| GET | `/api/inputs`, `/api/bundles` | listings with status, size, dates (`/api/inputs/<name>`, `/api/bundles/<name>` fetch one; `?download=1`) |
| GET | `/api/config` | active mappings |
| GET | `/api/sample` | sample C-CDA |

## Input files, bundles and meta tagging
Every conversion is saved in a bucket-style folder layout (default `data/` inside the repo, override with `CCDA_DATA_DIR`):

```
data/input/    uploaded C-CDA files, or drop files here and click "Process pending"
data/output/   <input name>.bundle.json
data/status/   per-file processing result (used by the Input files / Bundles tabs)
```
The **Input files** and **Bundles** tabs list these like the GCS console (name, size, type, last modified,
status, filter, view/download). Click a bundle name to open it in the Bundle output and Individual resources tabs.

Each Bundle and each resource is stamped with `meta.tag` (code `EXL`) and `meta.source` (where the input file lives):
`file:///C:/.../data/input/x.xml` by default. Set `CCDA_SOURCE_BASE=gs://my-bucket/ccda/` to write
`gs://my-bucket/ccda/x.xml` instead, so ids line up with a GCS-to-FHIR-store flow. Change the tag, add a `system`,
or limit it to the Bundle only under `meta:` in `config/core.yaml`. The CLI uses the file's real path as the source.

## Project layout
```
app.py                 Flask web app and API
cli.py                 batch converter
ccda2fhir/converter.py mapping engine (no resource-specific logic)
config/*.yaml          one file per resource (+ core.yaml: code systems and value maps)
static/index.html      web UI
samples/               sample C-CDA
tests/                 pytest suite   (run: python -m pytest)
```

## Included resources
Patient, Organization, Practitioner, PractitionerRole, Location, Encounter, Condition,
Observation (labs, vitals), DiagnosticReport, AllergyIntolerance, MedicationRequest, Procedure,
DocumentReference, Provenance. Each carries its US Core 6.1.0 profile in `meta.profile`
(vitals use the base FHIR vital-signs profile).

## Adding a resource
Create `config/<name>.yaml`. It is picked up on the next request, with no restart and no code change.

```yaml
order: 125                      # lower runs first; resources you reference must run earlier
mappings:
  - resource: Immunization
    profile: http://hl7.org/fhir/us/core/StructureDefinition/us-core-immunization|6.1.0
    foreach: //substanceAdministration[templateId=2.16.840.1.113883.10.20.22.4.52]
    require: [vaccineCode]      # skip the resource if these are missing
    fields:
      status: statusCode@code | map:immStatus | default:completed
      vaccineCode: cc:consumable/manufacturedProduct/manufacturedMaterial/code
      patient.reference: ref:Patient
      occurrenceDateTime: effectiveTime@value | date
maps:                           # optional; may also go in core.yaml
  immStatus: {completed: completed, aborted: not-done}
```

**`foreach`**: path from the `ClinicalDocument` root, one resource per match. `//` means any depth,
`/` a direct child, `[templateId=OID]` or `[attr=value]` filters, `.` is the document itself.

**Field values** (`FHIR.path[0].sub: <spec>`):

| Spec | Meaning |
|---|---|
| `path/to/el@attr` | attribute of the first matching element (no `@attr`: its text) |
| `=value` | constant (`=true`/`=false` become booleans); kept only if sibling fields have data |
| `cc:path` | CodeableConcept from a coded element, including `translation` codings |
| `ref:Type` / `refs:Type` | reference to the nearest generated resource of that type / all contained ones (`refs:*` = all) |
| `... \| date` | HL7 timestamp to FHIR date/dateTime |
| `... \| oid` | OID to URI, using `systems:` in `core.yaml` |
| `... \| tel`, `num`, `map:name`, `default:x` | strip `tel:`, to number, value-map lookup, fallback |

Add terminology OIDs to `systems:` in `core.yaml` (unknown OIDs become `urn:oid:...`).

## Notes for production use
- **Not a validator.** Run output through the HL7 FHIR validator with the US Core package before clinical use.
- **R4 vs R5.** US Core 6.1 is published against FHIR R4. Output uses R5 element names
  (e.g. `Encounter.actualPeriod`, `medication.concept`), so strict US Core validation flags those differences.
- Bundles are `type: collection` (no Composition is generated). Resource ids are derived from a hash of the input, so reruns are stable.
- Timestamps without a time zone are emitted as dates, since FHIR forbids a time without a zone.
- **PHI.** Uploaded files and generated bundles are written to `data/` (PHI: protect or purge that folder; it is git-ignored); nothing is logged, and XML is parsed with
  `defusedxml` (no external entities or DTDs). For production, serve behind HTTPS with authentication,
  e.g. gunicorn behind a reverse proxy; the dev server binds to `127.0.0.1` only. Set `HOST`, `PORT`, `MAX_UPLOAD_MB`, `CCDA_CONFIG_DIR` as needed.
- Not yet mapped: allergy severity, medication frequency/route, procedure body site, immunizations, race/ethnicity, smoking status.
