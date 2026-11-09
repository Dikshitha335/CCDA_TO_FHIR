import os
import shutil

import pytest

from ccda2fhir import ConversionError, convert, load_config, split_bundle

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(ROOT, "samples", "sample_ccda.xml")
TYPES = {"Patient", "Organization", "Practitioner", "PractitionerRole", "Location", "Encounter",
         "Condition", "Observation", "DiagnosticReport", "AllergyIntolerance", "MedicationRequest",
         "Procedure", "DocumentReference", "Provenance"}


@pytest.fixture
def cfg():
    return load_config(os.path.join(ROOT, "config"))


@pytest.fixture
def xml():
    with open(SAMPLE, "rb") as fh:
        return fh.read()


def refs(o):
    if isinstance(o, dict):
        for k, v in o.items():
            if k == "reference" and isinstance(v, str):
                yield v
            else:
                yield from refs(v)
    elif isinstance(o, list):
        for x in o:
            yield from refs(x)


def test_bundle_shape(cfg, xml):
    b = convert(xml, cfg)
    types = [e["resource"]["resourceType"] for e in b["entry"]]
    assert b["resourceType"] == "Bundle" and b["type"] == "collection"
    assert set(types) == TYPES and types[-1] == "Provenance"


def test_patient_and_profile(cfg, xml):
    p = split_bundle(convert(xml, cfg))[0]
    assert p["resourceType"] == "Patient"
    assert p["gender"] == "female" and p["birthDate"] == "1980-02-14"
    assert p["meta"]["profile"][0].endswith("us-core-patient|6.1.0")
    assert p["telecom"][0]["value"] == "+1-410-555-0100"


def test_all_references_resolve(cfg, xml):
    b = convert(xml, cfg)
    ids = {f"{e['resource']['resourceType']}/{e['resource']['id']}" for e in b["entry"]}
    found = list(refs(b))
    assert found and all(r in ids for r in found)


def test_report_links_observation(cfg, xml):
    res = split_bundle(convert(xml, cfg))
    obs = next(r for r in res if r["resourceType"] == "Observation")
    rep = next(r for r in res if r["resourceType"] == "DiagnosticReport")
    assert rep["result"] == [{"reference": f"Observation/{obs['id']}"}]
    assert obs["valueQuantity"]["value"] == 112


def test_ids_are_stable(cfg, xml):
    assert [r["id"] for r in split_bundle(convert(xml, cfg))] == [r["id"] for r in split_bundle(convert(xml, cfg))]


@pytest.mark.parametrize("bad", [
    b"<foo/>", b"<x",
    b'<!DOCTYPE d [<!ENTITY e "a">]><ClinicalDocument xmlns="urn:hl7-org:v3">&e;</ClinicalDocument>',
])
def test_bad_input_rejected(cfg, bad):
    with pytest.raises(ConversionError):
        convert(bad, cfg)


def test_new_yaml_file_adds_resource(tmp_path, xml):
    shutil.copytree(os.path.join(ROOT, "config"), tmp_path / "config")
    (tmp_path / "config" / "basic.yaml").write_text(
        "mappings:\n  - resource: Basic\n    foreach: .\n    fields:\n      code.text: title\n")
    b = convert(xml, load_config(str(tmp_path / "config")))
    basic = [r for r in split_bundle(b) if r["resourceType"] == "Basic"]
    assert basic and basic[0]["code"]["text"] == "Continuity of Care Document"
