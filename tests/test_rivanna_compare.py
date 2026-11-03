import copy
import importlib.util
import unittest
from maintenance.rivanna_compare import parse_kml, compare_rivanna
from maintenance.geo import fingerprint

KML=b'''<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<Folder><name>Section #4 - Test</name><Placemark><name>Section 4C: CLOSED</name><description>Closed till 2027 &lt;br&gt;Use detour</description><LineString><coordinates>-78.5,38.03,0 -78.49,38.03,0</coordinates></LineString></Placemark><Placemark><name>Parking</name><Point><coordinates>-78.5,38.03</coordinates></Point></Placemark></Folder>
<Folder><name>2026 Loop deVille Route</name><Placemark><name>Event</name><LineString><coordinates>-78.5,38.03 -78.49,38.03</coordinates></LineString></Placemark></Folder>
</Document></kml>'''


class RivannaKmlTests(unittest.TestCase):
    def test_event_and_point_exclusions_and_explicit_status_flags(self):
        data=parse_kml(KML)
        self.assertEqual(len(data['records']),3)
        eligible=[r for r in data['records'] if r['eligible_for_route_review']]
        self.assertEqual(len(eligible),1)
        self.assertEqual(eligible[0]['flags'],['closure','detour'])
        self.assertIsNone(eligible[0]['source_id'])
        self.assertEqual(eligible[0]['geometry']['coordinates'][0],[-78.5,38.03])
        self.assertEqual(data['records'][-1]['exclusion_reason'],'event-only layer')

    def test_snapshot_keys_do_not_claim_stable_source_identity(self):
        first=parse_kml(KML)['records'][0]
        changed=parse_kml(KML.replace(b'-78.49,38.03',b'-78.48,38.03'))['records'][0]
        self.assertEqual(first['semantic_key'],changed['semantic_key'])
        self.assertNotEqual(first['snapshot_key'],changed['snapshot_key'])
        self.assertIsNone(changed['source_id'])

    @unittest.skipUnless(importlib.util.find_spec('shapely') and importlib.util.find_spec('pyproj'),'optional geometry dependencies not installed')
    def test_comparison_preserves_unmatched_current_features_and_properties(self):
        current={'type':'FeatureCollection','features':[{'type':'Feature','id':'curated-spur','geometry':{'type':'LineString','coordinates':[[-78.6,38.03],[-78.59,38.03]]},'properties':{'Name':'Rivanna Trail Spur','color':'curated-green'}}]}
        before=copy.deepcopy(current)
        report=compare_rivanna(KML,current,{'url':'official-test'})
        self.assertEqual(current,before)
        self.assertEqual(report['current_hash'],fingerprint(before))
        self.assertTrue(report['current_features_preserved'])
        self.assertEqual(report['current_rows'][0]['action'],'retain-entire-feature')
        self.assertEqual(report['current_rows'][0]['coverage_by_official']['10'],0)
        self.assertEqual(report['rows'][0]['review_priority'],'access-status')
        self.assertNotIn('candidate',report)


if __name__=='__main__':unittest.main()
