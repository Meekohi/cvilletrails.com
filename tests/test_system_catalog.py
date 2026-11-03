import copy
import unittest
from maintenance.common import ROOT, read_json
from maintenance.site import validate_systems


class SystemCatalogTests(unittest.TestCase):
    def setUp(self):self.systems=read_json(ROOT/'data/systems.json')

    def test_official_catalog_and_facts_validate(self):
        validate_systems(self.systems)
        expected={'ivy-creek-natural-area','heyward-community-forest','mcintire-park','quarry-park','azalea-park','pen-park',
                  'washington-park','jordan-park','meadow-creek','uva','pleasant-grove','montpelier','wintergreen'}
        self.assertTrue(expected.issubset({s['id'] for s in self.systems if s.get('info_sources') and s.get('context_mode')}))

    def test_unregistered_evidence_or_invalid_boundary_fails_the_build(self):
        altered=copy.deepcopy(self.systems)
        altered[0]['visitor_info'][0]['sources']=['unregistered']
        with self.assertRaisesRegex(ValueError,'evidence'):validate_systems(altered)
        altered=copy.deepcopy(self.systems)
        altered[1]['boundary']={'type':'Point','coordinates':[0,0]}
        with self.assertRaisesRegex(ValueError,'polygon'):validate_systems(altered)

    def test_duplicate_ids_and_missing_parent_fail(self):
        with self.assertRaisesRegex(ValueError,'Duplicate'):validate_systems(self.systems+[self.systems[0]])
        self.systems[0]['parent_ids']=['missing']
        with self.assertRaisesRegex(ValueError,'parent'):validate_systems(self.systems)


if __name__=='__main__':unittest.main()
