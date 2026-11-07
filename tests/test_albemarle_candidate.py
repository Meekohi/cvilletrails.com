import copy
import unittest

from maintenance.albemarle_candidate import reconcile, trim_covered, verify_cleanup_tiles
from maintenance.common import digest
from maintenance.geo import fingerprint
from tests.test_albemarle import collection, feature, HAS_GEO


@unittest.skipUnless(HAS_GEO, 'Optional geometry dependencies not installed')
class CountyCandidateTests(unittest.TestCase):
    def setUp(self):
        incoming = feature(10, park_id='biscuit-run', source_feature_id='upstream', TrailName='Blue')
        incoming['id'] = 'albemarle:upstream'
        self.source = collection(incoming)
        self.old = collection(feature(1), feature(2))
        self.other = collection(feature(3), feature(4))
        self.style = {'layers': []}
        self.manifest = {'authorization': 'ship it', 'publication_authorized': True,
            'source_hash': digest(self.source), 'county_hash': fingerprint(self.old),
            'strava_hash': fingerprint(self.other), 'style_hash': digest(self.style),
            'accepted_source_ids': ['albemarle:upstream'],
            'county_dispositions': {1: {'action': 'replace', 'source_ids': ['albemarle:upstream'], 'reason': 'Reviewed replacement'},
                2: {'action': 'retain', 'reason': 'Unmatched trail'}},
            'strava_dispositions': {3: {'action': 'replace', 'source_ids': ['albemarle:upstream'], 'reason': 'Reviewed rough Biscuit track'}},
            'legacy_ids': {'albemarle:upstream': 1}}

    def test_full_candidate_reuses_identity_and_preserves_unmatched_and_other_data(self):
        saved = copy.deepcopy((self.source, self.old, self.other))
        county, other, detail = reconcile(self.source, self.old, self.other, self.manifest, self.style)
        self.assertEqual([f['id'] for f in county['features']], ['1', '2'])
        self.assertEqual(county['features'][0]['properties']['source_feature_id'], 'upstream')
        self.assertEqual(county['features'][1]['geometry'], self.old['features'][1]['geometry'])
        self.assertEqual(county['features'][1]['properties'], self.old['features'][1]['properties'])
        self.assertEqual([f['id'] for f in other['features']], ['4'])
        self.assertEqual(other['features'][0]['properties'], self.other['features'][1]['properties'])
        self.assertEqual((self.source, self.old, self.other), saved)
        self.assertEqual(detail['legacy_ids_reused'], 1)

    def test_snapshot_scope_and_legacy_identity_fail_closed(self):
        for edit, message in [
            (lambda m: m.update(county_hash='stale'), 'input changed'),
            (lambda m: m.update(accepted_source_ids=[]), 'every accepted'),
            (lambda m: m['county_dispositions'].pop(2), 'Every existing'),
            (lambda m: m['legacy_ids'].update({'albemarle:upstream': 2}), 'retained feature'),
            (lambda m: m['county_dispositions'][1].update(source_ids=['unknown']), 'unaccepted')]:
            manifest = copy.deepcopy(self.manifest)
            edit(manifest)
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                reconcile(self.source, self.old, self.other, manifest, self.style)

    def test_trim_preserves_unmatched_tail_and_connects_to_replacement(self):
        old = feature(1)
        old['geometry']['coordinates'][-1][0] = -78.496
        new = feature(2)
        result, detail = trim_covered(old, [new], 10)
        self.assertEqual(result['id'], old['id'])
        self.assertEqual(result['properties'], old['properties'])
        self.assertAlmostEqual(result['geometry']['coordinates'][-1][0], -78.496, places=8)
        self.assertEqual(result['geometry']['coordinates'][-1], old['geometry']['coordinates'][-1])
        self.assertAlmostEqual(result['geometry']['coordinates'][0][0], -78.499, places=8)
        self.assertTrue(detail['joins'])
        self.assertLess(detail['retained_length_m'], detail['original_length_m'])
        with self.assertRaisesRegex(ValueError, 'whole retained feature'):
            trim_covered(new, [new], 10)

    def test_public_tile_check_detects_superseded_rough_geometry(self):
        expected = collection(feature(1))
        self.assertTrue(verify_cleanup_tiles(expected, expected)['passed'])
        stale = feature(2)
        for point in stale['geometry']['coordinates']:
            point[1] += .001
        self.assertFalse(verify_cleanup_tiles(expected, collection(stale))['passed'])
        with self.assertRaisesRegex(ValueError, 'No Strava tile'):
            verify_cleanup_tiles(expected, collection())
