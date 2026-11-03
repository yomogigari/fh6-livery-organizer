"""November 2026 FH6 Series 7 car metadata, revision 4 and legacy-contract regression."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
ORG = ROOT / 'src' / 'organizer'
METADATA = ORG / 'fh6-vehicle-metadata.json'
MANIFEST = ORG / 'fh6-vehicle-metadata-manifest-current.json'
OLD_META = ORG / 'fh6-vehicle-metadata-rev2.json'
OLD_MANIFEST = ORG / 'fh6-vehicle-metadata-manifest.json'
EXPECTED = {
    '1325': '2011 Alfa Romeo Giulietta Quadrifoglio Verde',
    '4311': '2025 Citroën Ami',
    '3978': '1987 Fiat Panda',
    '4270': '2025 Ford Mustang GTD',
    '3084': '1966 Hillman Imp',
    '2487': '2016 Honda S660 Alpha',
    '3191': '1973 Lamborghini Espada 400 GT',
    '4181': '1983 Nissan 240RS',
    '4086': '2025 Porsche Macan GTS',
    '4282': '2025 Volkswagen Electric Buzz',
}


class FH6Series7MetadataTests(unittest.TestCase):
    def test_package_contract_and_667_rows(self) -> None:
        m, f = json.loads(METADATA.read_text('utf-8')), json.loads(MANIFEST.read_text('utf-8'))
        self.assertEqual((m['package_revision'], m['source']['updated']), (4, '2026-11'))
        self.assertEqual((len(m['records']), f['metadata']['record_count']), (667, 667))
        self.assertEqual((f['metadata']['package_revision'], f['metadata']['source_updated']), (4, '2026-11'))
        self.assertEqual(f['metadata']['file_sha256'], hashlib.sha256(METADATA.read_bytes()).hexdigest())
        self.assertEqual(f['metadata']['file_size'], METADATA.stat().st_size)
        self.assertEqual(f['metadata']['curation'], m['curation'])

    def test_ten_verified_car_ids(self) -> None:
        m = json.loads(METADATA.read_text('utf-8'))
        for id, label in EXPECTED.items():
            with self.subTest(id=id):
                self.assertEqual(m['records'][id]['display_name'], label)

    def test_corrected_labels_and_existing_override(self) -> None:
        records = json.loads(METADATA.read_text('utf-8'))['records']
        self.assertEqual(records['3857'], {
            'year': 1990, 'make': 'Eunos', 'model': 'Cosmo', 'display_name': '1990 Eunos Cosmo'})
        self.assertEqual(records['2487']['model'], 'S660 Alpha')
        self.assertEqual(records['3735']['display_name'], '2022 Subaru BRZS')
        self.assertEqual(len(set(records)), 667)

    def test_rev2_legacy_files_still_pinned(self) -> None:
        old = json.loads(OLD_META.read_text('utf-8'))
        legacy = json.loads(OLD_MANIFEST.read_text('utf-8'))
        self.assertEqual(old['package_revision'], 2)
        self.assertEqual(len(old['records']), 647)
        self.assertEqual(legacy['metadata']['package_revision'], 2)
        self.assertEqual(legacy['metadata']['record_count'], 647)
        self.assertEqual(hashlib.sha256(OLD_META.read_bytes()).hexdigest(),
                         'e86fabd9e07fda7074f88f47227028de99e60ce3b3634bb259add516e912a7c0')


if __name__ == '__main__':
    unittest.main()
