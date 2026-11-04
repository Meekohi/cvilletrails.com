import copy
import tempfile
import unittest
from pathlib import Path

from maintenance.common import write_json
from maintenance.state_parks import normalize_trails
from maintenance.state_parks_batch import prepare, internal_overlaps


class StateParksBatchTests(unittest.TestCase):
    def feature(self, gid='06c108a3-56d9-4027-bca0-7d40cd7992ab', park='New Park', **props):
        return {'type': 'Feature', 'id': 1, 'properties': {'GlobalID': gid, 'LABEL': park,
            'Trail_Name': 'Loop Trail', 'Trail_User': 'H', 'Status': 'Open', 'outside_park': 'No',
            'Restrictions': 'No', 'BlazeColor': 'Blue', **props},
            'geometry': {'type': 'LineString', 'coordinates': [[-78.12345678, 38.12345678], [-78.12, 38.12]]}}

    def config(self, directory):
        write_json(directory / 'overrides.json', {})
        return {'id': 'virginia-state-parks', '_directory': directory,
                'approved_parks': {'Lake Anna State Park': {'system_id': 'lake-anna', 'palette': {'blue': '#004da8'}}},
                'system_ids': ['lake-anna'], 'sources': [{'id': 'trails-gis', 'url': 'https://example.org/official'}]}

    def test_candidate_expands_only_temporary_policy_and_preserves_curated_features(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self.config(Path(tmp)); original = copy.deepcopy(config)
            curated = self.feature(park='Curated');curated['id'] = 'heyward-connector'
            source = {'type': 'FeatureCollection', 'features': [self.feature()]}
            candidate, rows, systems = prepare(source, {'type': 'FeatureCollection', 'features': [curated]}, config, {}, {'palette': {'blue': '#004da8'}})
            self.assertEqual(config, original)
            self.assertIn(curated, candidate['features'])
            self.assertEqual(len(candidate['features']), 2)
            self.assertFalse(candidate['ingest_report']['publication_authorized'])
            self.assertEqual(rows[0]['category'], 'candidate')
            self.assertEqual(systems[0]['id'], 'dcr-new-park')

    def test_existing_source_change_is_flagged_without_replacing_live_trail(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self.config(Path(tmp))
            source = {'type': 'FeatureCollection', 'features': [self.feature(park='Lake Anna State Park')]}
            baseline = normalize_trails(source, config, 'trails-gis')
            source['features'][0]['geometry']['coordinates'][0][0] -= .01
            candidate, rows, _ = prepare(source, baseline, config, {}, {'palette': {'blue': '#004da8'}})
            self.assertEqual(candidate['features'], baseline['features'])
            self.assertEqual(rows[0]['category'], 'existing-change')

    def test_closed_name_ambiguous_color_and_bad_geometry_are_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self.config(Path(tmp))
            fs = [self.feature(Trail_Name='Path - closed section'),
                  self.feature('76fe465a-0cd7-4f7c-83a1-c27735893ea0', BlazeColor='Orange, White'),
                  self.feature('48c75f19-30ca-4c3d-88e7-9cea05542501')]
            fs[-1]['geometry']['coordinates'] = [[-78, 38]]
            candidate, rows, _ = prepare({'type': 'FeatureCollection', 'features': fs}, {'type': 'FeatureCollection', 'features': []}, config, {}, {'palette': {'blue': '#004da8'}})
            self.assertFalse(candidate['features'])
            self.assertTrue(all(r['category'] == 'held' for r in rows))
            self.assertFalse(rows[-1]['geometry_valid'])

    def test_duplicate_global_id_fails_before_generating_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                prepare({'type': 'FeatureCollection', 'features': [self.feature(), self.feature()]}, {'type': 'FeatureCollection', 'features': []}, self.config(Path(tmp)), {}, {'palette': {'blue': '#004da8'}})

    def test_registered_holds_are_checked_before_prefiltering_for_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self.config(Path(tmp));gid='76fe465a-0cd7-4f7c-83a1-c27735893ea0'
            config['held_features']={gid:'Mixed blaze remains held'}
            source={'type':'FeatureCollection','features':[self.feature(),self.feature(gid,BlazeColor='Orange, White')]}
            candidate, rows, _ = prepare(source, {'type':'FeatureCollection','features':[]},config,{}, {'palette':{'blue':'#004da8'}})
            self.assertEqual(len(candidate['features']),1)
            self.assertEqual(rows[1]['category'],'held')
            source['features'].pop()
            with self.assertRaisesRegex(ValueError,'held DCR feature disappeared'):
                prepare(source, {'type':'FeatureCollection','features':[]},config,{}, {'palette':{'blue':'#004da8'}})

    def test_overlap_screen_ignores_crossings_but_finds_shared_segments(self):
        try:
            import shapely, pyproj
        except ImportError:
            self.skipTest('Optional geo dependencies not installed')
        def line(fid, coords):
            return {'type': 'Feature', 'id': fid, 'properties': {}, 'geometry': {'type': 'LineString', 'coordinates': coords}}
        fs = [line('long', [[-78, 38], [-78, 38.02]]),
              line('shared', [[-78, 38.001], [-78, 38.009]]),
              line('crossing', [[-78.01, 38.01], [-77.99, 38.01]])]
        pairs = internal_overlaps(fs)
        self.assertEqual([(p['a'], p['b']) for p in pairs], [('long', 'shared')])


if __name__ == '__main__':
    unittest.main()
