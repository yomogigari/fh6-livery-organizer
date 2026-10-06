from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
METADATA = ROOT / "src" / "organizer" / "fh6-vehicle-metadata.json"
MANIFEST = ROOT / "src" / "organizer" / "fh6-vehicle-metadata-manifest-current.json"

APPROVED_SERIES5 = {
    "4067": "2025 Bentley Continental GT Speed",
    "3958": "2023 Dodge Challenger SRT Demon 170",
    "3429": "2019 Ginetta G40 Junior",
    "1534": "1990 Jaguar XJ-S",
    "4354": "1990 Jaguar XJ-S Forza Edition",
    "2235": "2015 Jaguar XKR-S GT",
    "335": "2002 Lotus Esprit V8",
    "4118": "2025 McLaren W1",
    "3624": "1987 Porsche Carrera Coupe 'Luftauto 002'",
    "3980": "1998 Renault Sport Spider",
    "278": "2006 Vauxhall Astra VXR",
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_current_metadata_package_identity() -> None:
    metadata = _load(METADATA)
    manifest = _load(MANIFEST)

    assert metadata["package_revision"] == 3
    assert metadata["source"]["updated"] == "2026-10"
    assert metadata["generated_from"] == "Vehicle DB Generator for FH6 0.6.3"
    assert len(metadata["records"]) == 657

    manifest_metadata = manifest["metadata"]
    assert manifest_metadata["package_revision"] == 3
    assert manifest_metadata["source_updated"] == "2026-10"
    assert manifest_metadata["record_count"] == 657
    assert manifest_metadata["records_sha256"] == (
        "0d4b201f4949e34407f32af073bc9245413ca858d6e515948178dafe3c1c7a6c"
    )


def test_all_human_approved_series5_mappings_are_bundled() -> None:
    records = _load(METADATA)["records"]
    actual = {
        car_id: records[car_id]["display_name"]
        for car_id in APPROVED_SERIES5
    }
    assert actual == APPROVED_SERIES5


def test_existing_brzs_curation_remains_active() -> None:
    metadata = _load(METADATA)
    assert metadata["records"]["3735"]["display_name"] == "2022 Subaru BRZS"
    assert metadata["curation"]["in_game_vehicle_name_overrides"]["record_count"] == 1
