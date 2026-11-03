import copy
import unittest

from maintenance.fortunes_cove import color_style, prepare_style
from maintenance.common import digest, read_json, ROOT
from maintenance.geo import changes, fingerprint
from maintenance.mapbox import target_by_id


class FortuneStyleTests(unittest.TestCase):
    def style(self):
        return {'layers':[
            {'id':'strava-trail','source-layer':'Strava_Sidetrails','paint':{'line-color':['coalesce',['get','draft_color'],'tan'],'line-width':3}},
            {'id':'rivanna-trail','source-layer':'Rivanna_Trail','paint':{'line-color':'green'}}],
            'metadata':{'draft-only':'keep'}}

    def test_scoped_palette_preserves_fallback_draft_and_rivanna(self):
        before=self.style();saved=copy.deepcopy(before);after=color_style(before)
        self.assertEqual(before,saved)
        color=after['layers'][0]['paint'].pop('line-color')
        self.assertEqual(color[1],['==',['get','system_id'],'fortunes-cove'])
        self.assertEqual(color[-1],before['layers'][0]['paint'].pop('line-color'))
        self.assertEqual(after,before)
        self.assertEqual(color_style(color_style(saved)),color_style(saved))

    def test_rejects_wrong_layer_or_existing_palette(self):
        style=self.style();style['layers'][0]['source-layer']='Rivanna_Trail'
        with self.assertRaises(ValueError): color_style(style)
        style=color_style(self.style());style['layers'][0]['paint']['line-color'][2]='red'
        with self.assertRaises(ValueError): color_style(style)

    def test_proposal_rejects_unrelated_addition_or_existing_geometry_edit(self):
        before={'type':'FeatureCollection','features':[{'type':'Feature','id':'existing','properties':{},'geometry':{'type':'LineString','coordinates':[[-78,38],[-78.1,38.1]]}}]}
        additions=[]
        for p in read_json(ROOT/'pipelines/fortunes-cove/extraction.json')['paths']:
            f=copy.deepcopy(before['features'][0]);f['id']='fortunes-cove:'+p['id'];f['properties']={'system_id':'fortunes-cove'};additions.append(f)
        after={'type':'FeatureCollection','features':before['features']+additions}
        def plan_for(value):
            p={'target':target_by_id('strava'),'before':before,'after':value,'before_hash':fingerprint(before),'after_hash':fingerprint(value),'changes':changes(before,value)}
            p['approval_hash']=digest(p);return p
        manifest,_=prepare_style(plan_for(after),self.style())
        self.assertIn('proposal_hash',manifest)
        extra=copy.deepcopy(after);extra['features'][-1]['id']='unrelated'
        with self.assertRaises(ValueError):prepare_style(plan_for(extra),self.style())
        edited=copy.deepcopy(after);edited['features'][0]['geometry']['coordinates'][0][0]-=.1
        with self.assertRaises(ValueError):prepare_style(plan_for(edited),self.style())


if __name__=='__main__':unittest.main()
