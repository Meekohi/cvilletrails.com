import importlib.util
import unittest
from maintenance.overlaps import classify, coverage


@unittest.skipUnless(importlib.util.find_spec('shapely') and importlib.util.find_spec('pyproj'), 'optional geometry dependencies not installed')
class OverlapTests(unittest.TestCase):
    def test_reversed_and_split_lines_cover_the_same_route(self):
        from shapely.geometry import LineString, MultiLineString
        route = LineString([(0, 0), (100, 0)])
        existing = MultiLineString([[(50, 0), (0, 0)], [(100, 0), (50, 0)]])
        result = coverage(route, existing)
        self.assertEqual(result['1'], 1)
        self.assertEqual(classify(result, route.length), 'close-match')

    def test_crossing_is_not_a_duplicate_and_parallel_is_only_candidate(self):
        from shapely.geometry import LineString
        route = LineString([(0, 0), (100, 0)])
        crossing = LineString([(50, -100), (50, 100)])
        self.assertEqual(classify(coverage(route, crossing), route.length), 'no-substantial-overlap')
        parallel = LineString([(0, 8), (100, 8)])
        result = coverage(route, parallel)
        self.assertEqual(result['3'], 0)
        self.assertEqual(classify(result, route.length), 'strong-overlap')

    def test_reverse_coverage_exposes_geometry_that_must_be_kept(self):
        from shapely.geometry import LineString
        city = LineString([(0, 0), (100, 0)])
        existing = LineString([(0, 0), (500, 0)])
        self.assertEqual(coverage(city, existing)['10'], 1)
        self.assertLess(coverage(existing, city)['10'], .25)

    def test_zero_length_and_short_segments_are_not_high_confidence(self):
        from shapely.geometry import LineString
        point_line = LineString([(0, 0), (0, 0)])
        normal = LineString([(0, 0), (100, 0)])
        self.assertEqual(coverage(point_line, normal)['10'], 0)
        self.assertEqual(classify({'3': 1, '10': 1}, 5), 'short-segment')


class ReviewBindingTests(unittest.TestCase):
    def test_overlap_page_rejects_a_report_for_another_plan(self):
        import tempfile
        from pathlib import Path
        from maintenance.common import digest, write_json
        from maintenance.geo import fingerprint
        from maintenance.review_map import build_review
        data = {'type': 'FeatureCollection', 'features': []}
        plan = {'before': data, 'after': data, 'before_hash': fingerprint(data), 'after_hash': fingerprint(data), 'target': {'id': 'city'}}
        plan['approval_hash'] = digest(plan)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(root / 'plan.json', plan)
            write_json(root / 'overlaps.json', {'plan_hash': 'wrong'})
            with self.assertRaisesRegex(ValueError, 'different review plan'):
                build_review(root / 'plan.json', root, root / 'overlaps.json')


if __name__ == '__main__': unittest.main()
