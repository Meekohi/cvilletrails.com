import copy
import unittest
from pathlib import Path

from maintenance.albemarle_followup import build, explain, is_junction_flag, southern_records, verify_inputs
from maintenance.common import digest, read_json, ROOT
from maintenance.geo import fingerprint
from tests.test_albemarle import collection, feature


class FollowupTests(unittest.TestCase):
    def setUp(self):
        self.source = collection(feature())
        self.baseline = collection()
        self.report = {'source_hash': digest(self.source), 'baseline_hash': fingerprint(self.baseline),
            'rows': [{'id': 'accepted', 'category': 'eligible'}, {'id': 'closed', 'category': 'held'}]}
        self.report['review_hash'] = digest(self.report)
        self.feedback = {'parent_review_hash': self.report['review_hash'],
            'source_hash': self.report['source_hash'], 'baseline_hash': self.report['baseline_hash'],
            'geometry_accepted_feature_ids': ['accepted']}

    def test_exact_geometry_acceptance_and_input_binding(self):
        verify_inputs(self.report, self.source, self.baseline, self.feedback)
        for ids in ([], ['accepted', 'closed'], ['another']):
            with self.subTest(ids=ids), self.assertRaisesRegex(ValueError, 'exact reviewed'):
                verify_inputs(self.report, self.source, self.baseline,
                    {**self.feedback, 'geometry_accepted_feature_ids': ids})
        modified = copy.deepcopy(self.source)
        modified['features'][0]['properties']['Trail_Name'] = 'Changed'
        with self.assertRaisesRegex(ValueError, 'inputs do not match'):
            verify_inputs(self.report, modified, self.baseline, self.feedback)
        with self.assertRaisesRegex(ValueError, 'Parent review hash'):
            verify_inputs({**self.report, 'extra': True}, self.source, self.baseline, self.feedback)

    def test_prevents_parent_overwrite(self):
        with self.assertRaisesRegex(ValueError, 'overwrite'):
            build(Path('/tmp/parent'), None, None, None, None, Path('/tmp/parent'))

    def test_south_geometry_keeps_closed_status_and_raw_source(self):
        closed = feature(1, Loc_Name='Biscuit Run Park-400 Acres', Property_Info='Closed', Map_Method='Submeter', Hiking=None)
        source = collection(closed, feature(2, Loc_Name='Biscuit Run Park-400 Acres'),
            feature(3, Loc_Name='Biscuit Run Park-400 Acres', Property_Info='Closed', Status='Inactive'),
            feature(4, Loc_Name='Another park', Property_Info='Closed'))
        before = copy.deepcopy(source)
        report = {'rows': [{'global_id': closed['properties']['GlobalID'], 'id': 'southern', 'category': 'held', 'geometry_valid': True}]}
        result = southern_records(source, report)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['properties']['Property_Info'], 'Closed')
        self.assertIsNone(result[0]['properties']['Hiking'])
        self.assertEqual(result[0]['properties']['compare_category'], 'closed-south')
        self.assertEqual(source, before)
        report['rows'][0]['category'] = 'eligible'
        with self.assertRaisesRegex(ValueError, 'review group changed'):
            southern_records(source, report)

    def test_junction_screen_does_not_hide_substantial_route_conflict(self):
        small = {'source_coverage': {'3': .02}, 'existing_length_m': 100,
            'existing_coverage': {'3': .2}, 'conflicts': [{'property': 'rendered_color'}]}
        row = {'length_m': 1000, 'park_id': 'ivy-creek-natural-area', 'name': 'Blue', 'matches': [small]}
        evidence = read_json(ROOT / 'pipelines/albemarle/color-evidence.json')
        self.assertTrue(is_junction_flag(row, [small]))
        self.assertEqual(explain(row, evidence)['kind'], 'Junction proximity flag')
        row['matches'].append({**small, 'source_coverage': {'3': .4}, 'existing_length_m': 1000,
            'existing_coverage': {'3': .4}})
        self.assertFalse(is_junction_flag(row, row['matches']))
        self.assertEqual(explain(row, evidence)['kind'], 'Route attribution differs; map also revised')

    def test_alias_evidence_is_separate_from_unverified_routes(self):
        evidence = read_json(ROOT / 'pipelines/albemarle/color-evidence.json')
        self.assertEqual(evidence['notes']['walnut-creek/Blue Wheel']['suggested_alias'], 'The Blue Wheel')
        for key in ('walnut-creek/Wilkins Way', "walnut-creek/Luke's Connector", 'ivy-creek-natural-area/Blue'):
            self.assertNotIn('suggested_alias', evidence['notes'][key])
