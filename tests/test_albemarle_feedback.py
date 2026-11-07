import copy
import tempfile
import unittest
from pathlib import Path

from maintenance.albemarle_feedback import import_feedback, resolve, southern_open_decision
from maintenance.albemarle import normalize_trails
from maintenance.common import configs, digest, read_json, write_json
from tests.test_albemarle import collection, feature


class ColorFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = {**configs('albemarle')[0], '_directory': self.root}
        write_json(self.root / 'overrides.json', {})
        self.source = collection(feature(Trail_Name='Blue Wheel'), feature(2, Trail_Name='Connector'))
        self.ids = ['albemarle:' + f['properties']['GlobalID'] for f in self.source['features']]
        self.style = {'layers': [{'id': 'albemarle-trail', 'paint': {'line-color':
            ['match', ['get', 'TrailName'], 'The Blue Wheel', 'blue', 'Red', 'red', 'tan']}}]}
        self.report = {'parent_review_hash': 'parent', 'source_hash': digest(self.source),
            'baseline_hash': 'baseline', 'feedback_hash': 'geometry', 'style_hash': digest(self.style),
            'geometry_accepted_feature_ids': self.ids,
            'cases': [{'id': fid, 'park_id': 'walnut-creek', 'name': name, 'raw_color': 'tan',
                'old_records': [{'id': 'old', 'name': 'The Blue Wheel', 'color': 'blue'}],
                'analysis': {}} for fid, name in zip(self.ids, ['Blue Wheel', 'Connector'])]}
        self.feedback = {'schema_version': 1, 'kind': 'albemarle-color-and-south-review',
            'geometry_feedback_hash': 'geometry', 'publication_authorized': False,
            'questions': {self.ids[0]: {'decision': 'preserve-current', 'notes': 'Keep blue.'}}}
        self.sign()

    def sign(self):
        self.report.pop('review_hash', None)
        self.report['review_hash'] = digest(self.report)
        self.feedback.update({k: self.report[k] for k in ('review_hash', 'parent_review_hash', 'source_hash', 'baseline_hash')})

    def resolve(self):
        return resolve(self.report, self.feedback, self.style, {})

    def test_partial_feedback_preserves_alias_without_accepting_omissions(self):
        overrides, resolved, pending, south = self.resolve()
        self.assertEqual(overrides[self.ids[0][10:]]['properties'], {'TrailName': 'The Blue Wheel', 'color': 'blue'})
        self.assertEqual(resolved[0]['notes'], 'Keep blue.')
        self.assertEqual([p['id'] for p in pending], [self.ids[1]])
        self.assertEqual(south['decision'], '')

    def test_gis_choice_can_resolve_multiple_old_colors(self):
        self.report['cases'][0]['old_records'].append({'id': 'other', 'name': 'Red', 'color': 'red'})
        self.sign()
        with self.assertRaisesRegex(ValueError, 'multiple possible colors'):
            self.resolve()
        self.feedback['questions'][self.ids[0]]['decision'] = 'gis-name-color'
        self.assertEqual(self.resolve()[0][self.ids[0][10:]]['properties'], {'TrailName': 'Blue Wheel', 'color': 'tan'})

    def test_wrong_snapshot_unknown_id_and_unsupported_alias_fail(self):
        for key in ('review_hash', 'parent_review_hash', 'source_hash', 'baseline_hash', 'geometry_feedback_hash'):
            f = {**self.feedback, key: 'wrong'}
            with self.subTest(key=key), self.assertRaises(ValueError):
                resolve(self.report, f, self.style, {})
        self.feedback['questions']['unknown'] = {'decision': 'preserve-current', 'notes': ''}
        with self.assertRaisesRegex(ValueError, 'Unknown feedback'):
            self.resolve()
        del self.feedback['questions']['unknown']
        self.feedback['questions'][self.ids[0]]['decision'] = 'suggested-alias'
        with self.assertRaisesRegex(ValueError, 'No supported'):
            self.resolve()

    def test_existing_override_conflicts_fail_and_identical_reimport_is_safe(self):
        overrides = self.resolve()[0]
        self.assertEqual(resolve(self.report, self.feedback, self.style, overrides)[0], overrides)
        overrides[self.ids[0][10:]]['properties']['TrailName'] = 'Red'
        with self.assertRaisesRegex(ValueError, 'existing override'):
            resolve(self.report, self.feedback, self.style, overrides)

    def test_import_keeps_raw_names_geometry_and_review_only_marker(self):
        for name, value in [('review', self.report), ('feedback', self.feedback), ('source', self.source), ('style', self.style)]:
            write_json(self.root / (name + '.json'), value)
        paths = [self.root / (name + '.json') for name in ('review', 'feedback', 'source', 'style')]
        output = self.root / 'output'
        import_feedback(*paths, output, self.config)
        candidate = read_json(output / 'screened-with-reviewed-colors.geojson')
        self.assertTrue(candidate['ingest_report']['review_only'])
        first = candidate['features'][0]
        self.assertEqual(first['properties']['name'], 'Blue Wheel')
        self.assertEqual(first['properties']['Trail_Name'], 'Blue Wheel')
        self.assertEqual(first['properties']['TrailName'], 'The Blue Wheel')
        self.assertEqual(first['geometry'], self.source['features'][0]['geometry'])
        self.assertEqual((output / 'original-feedback.json').read_bytes(), paths[1].read_bytes())
        previous = (self.root / 'overrides.json').read_bytes()
        modified = copy.deepcopy(self.source)
        modified['features'][0]['properties']['Property_Info'] = 'Closed'
        write_json(paths[2], modified)
        with self.assertRaisesRegex(ValueError, 'Source differs'):
            import_feedback(*paths, output, self.config)
        self.assertEqual((self.root / 'overrides.json').read_bytes(), previous)

    def test_south_decision_is_recorded_without_granting_access(self):
        self.feedback['questions']['biscuit-south'] = {'decision': 'closed-geometry', 'notes': 'Keep Closed.'}
        overrides, _, _, south = self.resolve()
        self.assertEqual(len(overrides), 1)
        self.assertEqual(south['decision'], 'closed-geometry')

    def southern_fixture(self):
        f = feature(3, Loc_Name='Biscuit Run Park-400 Acres', Property_Info='Closed', Hiking=None)
        self.source['features'].append(f)
        self.report['source_hash'] = digest(self.source)
        self.report['south'] = {'ids': ['albemarle:' + f['properties']['GlobalID']]}
        self.feedback['questions']['biscuit-south'] = {'decision': 'closed-geometry',
            'notes': 'Mark it as open; this section is open in practice.'}
        self.sign()
        return f

    def test_explicit_southern_note_adds_exact_geometry_with_raw_access_provenance(self):
        f = self.southern_fixture()
        for name, value in [('review', self.report), ('feedback', self.feedback), ('source', self.source), ('style', self.style)]:
            write_json(self.root / (name + '.json'), value)
        paths = [self.root / (name + '.json') for name in ('review', 'feedback', 'source', 'style')]
        # Dropdown/notes alone do not silently grant access.
        initial = import_feedback(*paths, self.root / 'initial', self.config)
        self.assertEqual(initial['normalized_features'], 2)
        result = import_feedback(*paths, self.root / 'open', self.config, southern_open=True)
        self.assertEqual(result['normalized_features'], 3)
        self.assertEqual(result['southern_open_features'], 1)
        candidate = normalize_trails(self.source, self.config, 'county-gis')
        southern = next(g for g in candidate['features'] if g['id'] == self.report['south']['ids'][0])
        self.assertEqual(southern['geometry'], f['geometry'])
        p = southern['properties']
        self.assertEqual(p['Property_Info'], 'Open')
        self.assertEqual(p['Hiking'], 'Yes')
        self.assertEqual(p['source_Property_Info'], 'Closed')
        self.assertIsNone(p['source_Hiking'])
        self.assertIsNone(p['Biking'])
        self.assertTrue(candidate['ingest_report']['review_only'])
        # The exception persists for future imports, without expanding to new records.
        other = feature(4, Loc_Name='Biscuit Run Park-400 Acres', Property_Info='Closed', Hiking=None)
        expanded = copy.deepcopy(self.source)
        expanded['features'].append(other)
        self.assertEqual(len(normalize_trails(expanded, self.config, 'county-gis')['features']), 3)
        for key, value in [('Hiking', 'No'), ('Status', 'Inactive'), ('Ownership', 'Private'), ('Property_Info', 'Open')]:
            changed = copy.deepcopy(self.source)
            changed['features'][-1]['properties'][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'source facts or geometry changed'):
                normalize_trails(changed, self.config, 'county-gis')
        changed = copy.deepcopy(self.source)
        changed['features'][-1]['geometry']['coordinates'][0][0] -= .001
        with self.assertRaisesRegex(ValueError, 'geometry changed'):
            normalize_trails(changed, self.config, 'county-gis')
        with self.assertRaisesRegex(ValueError, 'record disappeared'):
            normalize_trails(collection(*self.source['features'][:2]), self.config, 'county-gis')

    def test_southern_interpretation_cannot_override_other_holds(self):
        f = self.southern_fixture()
        for key, value in [('Hiking', 'No'), ('Status', 'Inactive'), ('Ownership', 'Private')]:
            source = copy.deepcopy(self.source)
            source['features'][-1]['properties'][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'access-only holds'):
                southern_open_decision(self.report, self.feedback, source, self.config)
        self.feedback['questions']['biscuit-south']['notes'] = ''
        with self.assertRaisesRegex(ValueError, 'explicit user notes'):
            southern_open_decision(self.report, self.feedback, self.source, self.config)
