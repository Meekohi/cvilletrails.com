import tempfile
import importlib.util
import unittest
from pathlib import Path
from maintenance.access_review import short_connectivity, contrary_reason
from maintenance.appalachian_trail import transform, prepare
from maintenance.common import configs, digest


def line(fid, xy):
    return {'type':'Feature','id':fid,'properties':{'name':fid},
            'geometry':{'type':'LineString','coordinates':[[-79+x/88000,38+y/111000] for x,y in xy]}}


@unittest.skipUnless(importlib.util.find_spec('shapely') and importlib.util.find_spec('pyproj'), 'optional geometry dependencies')
class ConnectivityTests(unittest.TestCase):
    def test_short_chain_needs_two_useful_anchors(self):
        short=[line('a',[(0,0),(40,0)]),line('b',[(40,0),(80,0)])]
        left=line('left',[(0,-200),(0,200)])
        right=line('right',[(80,-200),(80,200)])
        for refs,expected in [([],False),([left],False),([left,right],True)]:
            result=short_connectivity(short,refs)
            self.assertTrue(all(r['useful_connection']==expected for r in result.values()))
            self.assertEqual(set(result['a']['component_ids']),{'a','b'})

    def test_shortcut_between_two_positions_on_one_trail(self):
        shortcut=line('cut',[(0,0),(80,0)])
        trail=line('long',[(0,0),(0,200),(80,200),(80,0)])
        self.assertTrue(short_connectivity([shortcut],[trail])['cut']['useful_connection'])

    def test_contrary_evidence_and_placeholders(self):
        f=line('sample',[(0,0),(80,0)])
        f['properties']['hiker_pedestrian_restricted']='N/A'
        self.assertIsNone(contrary_reason(f,{'holds':[]}))
        f['properties']['hiker_pedestrian_disc']='01/01-12/31'
        self.assertIn('discourages',contrary_reason(f,{'holds':[]}))
        f['properties']={'name':'OLD SPUR (DECO'}
        self.assertIn('decommissioning',contrary_reason(f,{'holds':[]}))


class ATTests(unittest.TestCase):
    def source(self,status='Official A.T. Route'):
        f=line('old',[(0,0),(100,0)])
        f['properties']={'GlobalID':'{aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee}','Status':status}
        return {'type':'FeatureCollection','features':[f]}

    def test_stable_official_identity_and_white_style(self):
        config=configs('appalachian-trail')[0]
        result=transform(self.source(),config,'official-centerline')
        f=result['features'][0]
        self.assertEqual(f['id'],'nps-atc:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee')
        self.assertEqual(f['properties']['color'],'white')
        self.assertTrue(result['ingest_report']['review_only'])
        held=transform(self.source('Proposed'),config,'official-centerline')
        self.assertFalse(held['features']);self.assertEqual(len(held['ingest_report']['held']),1)
        source=self.source();source['features']*=2
        with self.assertRaisesRegex(ValueError,'Duplicate'):transform(source,config,'official-centerline')

    @unittest.skipUnless(importlib.util.find_spec('shapely') and importlib.util.find_spec('pyproj'), 'optional geometry dependencies')
    def test_bounded_replacement_and_stale_baseline_guard(self):
        baseline=self.source()
        config=configs('appalachian-trail')[0]
        source=transform(baseline,config,'official-centerline')
        scope={'baseline_hash':digest(baseline),'bounds':[-79,37.99,-78.9995,38.01]}
        with tempfile.TemporaryDirectory() as tmp:
            report=prepare(baseline,source,Path(tmp),scope)
            self.assertEqual(report['after_count'],1)
            self.assertEqual(len(report['clipped_ids']),1)
            self.assertLess(report['after_miles'],report['before_miles'])
            touch=line('boundary-touch',[(-100,0),(0,0)])
            source['features'].append(touch)
            report=prepare(baseline,source,Path(tmp),scope)
            self.assertIn('boundary-touch',report['out_of_scope_ids'])
            baseline['features'][0]['properties']['changed']=True
            with self.assertRaisesRegex(ValueError,'dataset changed'):prepare(baseline,source,Path(tmp),scope)


if __name__=='__main__':unittest.main()
