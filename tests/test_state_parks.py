import copy
import tempfile
import unittest
from pathlib import Path
from maintenance.common import write_json
from maintenance.state_parks import hold_reasons,normalize_trails
from maintenance.state_parks_style import color_style


class StateParkTests(unittest.TestCase):
    def feature(self,**props):
        return {'type':'Feature','id':1,'properties':{'GlobalID':'06c108a3-56d9-4027-bca0-7d40cd7992ab','LABEL':'Lake Anna State Park','Trail_Name':'  Campground  Walkway Trail ','Trail_User':'H','BlazeColor':'None','Status':'Open','outside_park':'No','Restrictions':'No',**props},'geometry':{'type':'LineString','coordinates':[[-77.8,38.1],[-77.81,38.11]]}}

    def test_open_is_not_enough_for_proposed_staff_water_or_offsite(self):
        for fields in [{'Trail_Name':'Proposed/Reroute Trail'},{'Trail_Name':'Potomac Heritage Trail - closed section'},{'Trail_User':'Staff'},{'Trail_User':None},{'Status':None},{'Status':'Not Open'},{'Surfacing':'Water'},{'outside_park':'Yes'},{'Restrictions':None}]:
            self.assertTrue(hold_reasons(self.feature(**fields)),fields)
        self.assertFalse(hold_reasons(self.feature()))

    def test_stable_identity_scoped_park_and_evidenced_usage_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);gid=self.feature()['properties']['GlobalID'];write_json(d/'overrides.json',{gid:{'properties':{'trail_use':'H'}}})
            config={'_directory':d,'system_ids':['lake-anna'],'approved_parks':{'Lake Anna State Park':{'system_id':'lake-anna','palette':{'none':'#000000'}}},'sources':[{'id':'trails-gis','url':'https://example.com/official'}]}
            original=self.feature(Trail_User=None);unreviewed=self.feature(LABEL='Other Park',GlobalID='76fe465a-0cd7-4f7c-83a1-c27735893ea0')
            data={'type':'FeatureCollection','features':[original,unreviewed]};result=normalize_trails(data,config,'trails-gis')
            f=result['features'][0];self.assertEqual(f['id'],'va-state-parks:'+gid);self.assertEqual(f['properties']['trail_use'],'H');self.assertIsNone(f['properties']['Trail_User']);self.assertEqual(f['properties']['name'],'Campground Walkway Trail');self.assertEqual(len(result['features']),1)
            self.assertEqual(result['ingest_report']['unreviewed_parks'],{'Other Park':1})
            original['id']=999;original['properties']['OBJECTID']=999
            self.assertEqual(normalize_trails(data,config,'trails-gis')['features'][0]['id'],f['id'])
            data['features'].append(copy.deepcopy(original))
            with self.assertRaises(ValueError):normalize_trails(data,config,'trails-gis')

    def test_unknown_color_and_orphaned_override_stop_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);write_json(d/'overrides.json',{})
            config={'_directory':d,'system_ids':['lake-anna'],'approved_parks':{'Lake Anna State Park':{'system_id':'lake-anna','palette':{}}},'sources':[{'id':'trails-gis','url':'https://example.com/official'}]}
            with self.assertRaises(ValueError):normalize_trails({'type':'FeatureCollection','features':[self.feature()]},config,'trails-gis')
            write_json(d/'overrides.json',{'missing':{'properties':{'trail_use':'H'}}})
            with self.assertRaises(ValueError):normalize_trails({'type':'FeatureCollection','features':[]},config,'trails-gis')

    def test_scoped_color_preserves_fortunes_palette_and_other_layers(self):
        old=['case',['==',['get','system_id'],'fortunes-cove'],'yellow','tan']
        before={'layers':[{'id':'strava-trail','source-layer':'Strava_Sidetrails','paint':{'line-color':old,'line-width':4}},{'id':'rivanna-trail','paint':{'line-color':'green'}}]}
        after=color_style(before);self.assertEqual(after['layers'][0]['paint']['line-color'][-1],old);self.assertEqual(after['layers'][1],before['layers'][1]);self.assertEqual(color_style(after),after);self.assertEqual(before['layers'][0]['paint']['line-color'],old)

    def test_shared_palette_and_explicit_hold_keep_mixed_blaze_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);write_json(d/'overrides.json',{})
            gid='76fe465a-0cd7-4f7c-83a1-c27735893ea0'
            config={'_directory':d,'system_ids':['lake-anna'],'palette':{'none':'#000000'},
                    'approved_parks':{'Lake Anna State Park':{'system_id':'lake-anna'}},
                    'held_features':{gid:'Mixed blaze needs review'},'sources':[{'id':'trails-gis','url':'https://example.com/official'}]}
            source={'type':'FeatureCollection','features':[self.feature(),self.feature(GlobalID=gid,BlazeColor='Orange, White')]}
            result=normalize_trails(source,config,'trails-gis')
            self.assertEqual(len(result['features']),1)
            self.assertEqual(result['features'][0]['properties']['display_color'],'#000000')
            self.assertIn('Mixed blaze needs review',result['ingest_report']['held'][0]['reasons'])
            source['features'].pop()
            with self.assertRaisesRegex(ValueError,'held DCR feature disappeared'):normalize_trails(source,config,'trails-gis')


if __name__=='__main__':unittest.main()
