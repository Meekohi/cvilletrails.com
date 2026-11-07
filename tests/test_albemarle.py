import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID

from maintenance.albemarle import normalize_trails, screen
from maintenance.albemarle_review import compare
from maintenance.common import ROOT, configs, digest, read_json, write_json
from maintenance.geo import canonical, fingerprint
from maintenance.mapbox import make_plan, target_by_id, validate_plan

try:
    from maintenance.overlaps import geometry_tools
    geometry_tools()
    HAS_GEO = True
except ValueError:
    HAS_GEO = False


def feature(number=1, **properties):
    return {'type': 'Feature', 'id': number, 'geometry': {'type': 'LineString',
        'coordinates': [[-78.5, 38], [-78.499, 38]]}, 'properties': {
        'OBJECTID': number, 'GlobalID': str(UUID(int=number)), 'Trail_Name': 'Blue',
        'Loc_Name': 'Ivy Creek Natural Area & Historic River View Farm', 'Status': 'Active',
        'Property_Info': 'Open', 'Ownership': 'Public Use Trail', 'Hiking': 'Yes',
        'Biking': None, 'Equestrian': 'No', 'Surface': 'Bare Earth', **properties}}


def collection(*features):
    return {'type': 'FeatureCollection', 'features': list(features)}


def existing(fid='curated', name='Blue'):
    f = feature()
    f['id'] = fid
    f['properties'] = {'TrailName': name, 'LocationNa': 'Ivy Creek Natural Area',
        'Hiking': 'Yes', 'Biking': None, 'Equestrian': 'No', 'Surface': 'Bare Earth', 'Ownership': 'Public Use Trail',
        'curated_note': 'Preserve this value'}
    return f


class CountyAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = copy.deepcopy(configs('albemarle')[0])
        self.config['_directory'] = Path(self.temp.name)
        write_json(self.config['_directory'] / 'overrides.json', {})

    def normalize(self, *features):
        return normalize_trails(collection(*features), self.config, 'county-gis')

    def test_uuid_identity_survives_objectid_change_and_preserves_raw_fields(self):
        f = feature(Trail_Name=' Blue  ', Biking=None)
        before = copy.deepcopy(f)
        result = self.normalize(f)
        normalized = result['features'][0]
        self.assertEqual(normalized['id'], 'albemarle:' + str(UUID(int=1)))
        self.assertEqual(normalized['properties']['TrailName'], 'Blue')
        self.assertEqual(normalized['properties']['Trail_Name'], ' Blue  ')
        self.assertEqual(normalized['properties']['LocationNa'], 'Ivy Creek Natural Area')
        self.assertIsNone(normalized['properties']['Biking'])
        self.assertEqual(f, before)
        f['id'] = 99
        f['properties'].update(OBJECTID=99, GlobalID='{' + str(UUID(int=1)).upper() + '}')
        self.assertEqual(self.normalize(f)['features'][0]['id'], normalized['id'])
        self.assertTrue(result['ingest_report']['review_only'])

    def test_active_public_is_not_enough_and_every_exclusion_is_reported(self):
        variations = [{'Status': 'Inactive'}, {'Status': 'Future'}, {'Status': 'Pending'},
            {'Ownership': 'Private'}, {'Ownership': None}, {'Property_Info': 'Closed'},
            {'Property_Info': 'Open outside school hours'}, {'Property_Info': None}, {'Hiking': None},
            {'Loc_Name': 'Monticello'}, {'Trail_Name': None}, {'Trail_Name': 'Emergency Access Trail'},
            {'Trail_Name': 'Proposed connector'}, {'Surface': 'Water'}]
        result = self.normalize(*(feature(i + 1, **props) for i, props in enumerate(variations)))
        self.assertEqual(result['features'], [])
        self.assertEqual(len(result['ingest_report']['held']), len(variations))
        self.assertTrue(all(r['reasons'] for r in result['ingest_report']['held']))

    def test_identity_errors_stop_even_on_excluded_records(self):
        for features in [(feature(), feature()), (feature(GlobalID=None, Status='Inactive'),),
                         (feature(GlobalID='not-a-uuid'),)]:
            with self.assertRaises(ValueError):
                self.normalize(*features)

    def test_bad_geometry_is_quarantined_and_projection_is_rejected(self):
        for geometry in [None, {'type': 'Point', 'coordinates': [-78, 38]},
            {'type': 'LineString', 'coordinates': [[-78, 38], [-78, 38]]},
            {'type': 'LineString', 'coordinates': [[-78, 38], [-780, 38]]}]:
            f = feature(); f['geometry'] = geometry
            result = self.normalize(f)
            self.assertFalse(result['features'])
            self.assertFalse(result['ingest_report']['held'][0]['geometry_valid'])
        with self.assertRaises(ValueError):
            screen({**collection(feature()), 'crs': 'EPSG:2284'}, self.config)
        f = feature(); f['geometry']['coordinates'][0][0] = float('nan')
        with self.assertRaises(ValueError):
            self.normalize(f)  # Non-JSON numeric values cannot form a hash-bound snapshot.

    def test_override_cannot_grant_access_or_hide_missing_source(self):
        path = self.config['_directory'] / 'overrides.json'
        gid = str(UUID(int=1))
        write_json(path, {gid: {'properties': {'TrailName': 'Blue'}}})
        with self.assertRaisesRegex(ValueError, 'no longer eligible'):
            self.normalize(feature(Property_Info='Closed'))
        with self.assertRaisesRegex(ValueError, 'disappeared'):
            self.normalize()
        write_json(path, {gid: {'properties': {'Status': 'Active'}}})
        with self.assertRaisesRegex(ValueError, 'only preserve'):
            self.normalize(feature())

    def test_alias_collision_and_wrong_source_fail(self):
        self.config['locations']['byrom']['aliases'].append('Ivy Creek Natural Area')
        with self.assertRaisesRegex(ValueError, 'unique'):
            self.normalize(feature())
        with self.assertRaisesRegex(ValueError, 'county-gis'):
            normalize_trails(collection(feature()), self.config, 'trail-directory')

    def test_screening_cannot_be_planned_or_published_even_with_valid_hash(self):
        candidate = self.normalize(feature())
        client = Mock()
        with self.assertRaisesRegex(ValueError, 'Review-only'):
            make_plan(client, target_by_id('albemarle'), candidate, 'review first')
        self.assertEqual(client.mock_calls, [])
        plan = {'target': target_by_id('albemarle'), 'ingest_report': candidate['ingest_report']}
        plan['approval_hash'] = digest(plan)
        with self.assertRaisesRegex(ValueError, 'Review-only'):
            validate_plan(plan, plan['approval_hash'])


@unittest.skipUnless(HAS_GEO, 'Optional geometry dependencies not installed')
class CountyComparisonTests(unittest.TestCase):
    setUp = CountyAdapterTests.setUp

    def compare(self, source, baseline, references=()):
        style = {'layers': read_json(ROOT / 'config/style-contract.json')['trail_layers']}
        return compare(source, baseline, self.config, style, references)[0]

    def test_reverse_direction_matches_without_mutating_curated_ids_or_properties(self):
        before = collection(existing())
        source = collection(feature())
        source['features'][0]['geometry']['coordinates'].reverse()
        saved = copy.deepcopy(before)
        result = self.compare(source, before)
        self.assertEqual(len(result['crosswalk_suggestions']), 1)
        self.assertFalse(result['crosswalk_suggestions'][0]['approved'])
        self.assertEqual(result['crosswalk_suggestions'][0]['existing_id'], 'curated')
        self.assertEqual(before, saved)
        self.assertEqual(result['baseline_hash'], fingerprint(saved))

    def test_split_merge_and_reverse_coverage_do_not_become_identity_matches(self):
        a, b = feature(1), feature(2)
        a['geometry']['coordinates'][-1] = [-78.4995, 38]
        b['geometry']['coordinates'][0] = [-78.4995, 38]
        result = self.compare(collection(a, b), collection(existing()))
        self.assertFalse(result['crosswalk_suggestions'])
        self.assertEqual(result['existing_rows'][0]['comparison'], 'covered-needs-review')
        # A short new segment is entirely on the old route, but leaves the old tail uncovered.
        result = self.compare(collection(a), collection(existing()))
        self.assertEqual(result['existing_rows'][0]['comparison'], 'coverage-gap')
        self.assertLess(result['existing_rows'][0]['eligible_coverage']['10'], .8)

    def test_duplicate_sources_and_parallel_lines_never_get_automatic_crosswalks(self):
        result = self.compare(collection(feature(1), feature(2)), collection(existing()))
        self.assertFalse(result['crosswalk_suggestions'])
        self.assertEqual(len(result['source_duplicate_pairs']), 1)
        f = feature()
        for p in f['geometry']['coordinates']:
            p[1] += .00006  # About 6.7m away: inside 10m band, outside identity threshold.
        result = self.compare(collection(f), collection(existing()))
        self.assertFalse(result['crosswalk_suggestions'])
        self.assertEqual(result['rows'][0]['comparison'], 'overlap-needs-review')

    def test_closed_and_missing_source_retain_old_trails_and_show_gaps(self):
        old = collection(existing('retained'), existing('missing'))
        old['features'][1]['geometry']['coordinates'] = [[-78.6, 38], [-78.599, 38]]
        result = self.compare(collection(feature(Property_Info='Closed')), old)
        self.assertEqual(result['counts']['existing_preserved'], 2)
        self.assertEqual(result['counts']['existing_coverage_gaps'], 2)
        self.assertEqual(result['counts']['eligible'], 0)
        self.assertEqual(result['existing_rows'][1]['eligible_matches'], [])

    def test_name_based_color_change_and_null_permission_are_visible(self):
        old = existing(name='Blue'); old['properties']['Biking'] = 'Yes'
        result = self.compare(collection(feature(Trail_Name='Green', Biking=None)), collection(old))
        conflicts = result['rows'][0]['matches'][0]['conflicts']
        self.assertIn('rendered_color', [c['property'] for c in conflicts])
        self.assertIn({'property': 'Biking', 'existing': 'Yes', 'source': None}, conflicts)
        self.assertTrue(result['rows'][0]['color_conflict'])

    def test_protected_other_dataset_overlap_is_reported_without_mutation(self):
        ref = existing('rivanna/retained')
        ref['properties'].update(review_dataset='Rivanna Trail', review_protected=True)
        saved = copy.deepcopy(ref)
        result = self.compare(collection(feature()), collection(), [ref])
        self.assertTrue(result['rows'][0]['other_overlaps'][0]['protected'])
        self.assertEqual(ref, saved)


if __name__ == '__main__':
    unittest.main()
