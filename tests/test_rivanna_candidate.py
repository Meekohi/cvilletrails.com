import copy
import unittest

from maintenance.common import digest
from maintenance.geo import fingerprint
from maintenance.rivanna_candidate import reviewed_candidate, closure_style


def feature(fid):
    return {'type':'Feature','id':fid,'geometry':{'type':'LineString','coordinates':[[-78.5,38.03],[-78.49,38.04]]},'properties':{'Name':'Rivanna Trail','color':'green'}}


class RivannaCandidateTests(unittest.TestCase):
    def setUp(self):
        self.current={'type':'FeatureCollection','features':[feature('main'),feature('detour')]}
        self.rows=[{'snapshot_key':key,'semantic_key':key,'geometry':feature(key)['geometry'],'eligible_for_route_review':True,'flags':[]} for key in ['new','closed','subset','detour','omit']]
        self.report={'current_hash':fingerprint(self.current),'rows':self.rows}
        self.report['review_hash']=digest(self.report)
        self.decisions={'review_hash':self.report['review_hash'],'current_hash':fingerprint(self.current),
                        'decisions':{key:{'decision':'keep-current' if key=='omit' else 'compare-geometry','note':'Explicit user note'} for key in ['new','closed','subset','detour','omit']}}
        actions=[]
        for row in self.rows:
            a={'source_snapshot_key':row['snapshot_key'],'source_semantic_key':row['semantic_key'],'source_geometry_hash':digest(row['geometry'])}
            key=row['snapshot_key']
            a['action']={'new':'add_official_road_walk','closed':'mark_existing_route_temporarily_closed','subset':'coalesce_closed_subset_annotation','detour':'retain_existing_primary_detour','omit':'omit_new_closed_route'}[key]
            if key=='new':a.update(proposed_feature_id='rtf:roadwalk:new',proposed_properties={'Name':'Rivanna Trail'})
            if key in {'closed','subset','detour'}:
                fid='detour' if key=='detour' else 'main'
                a.update(current_feature_id=fid,current_feature_before_hash=digest(feature(fid)))
            if key=='closed':a['proposed_property_additions']={'access_status':'temporarily-closed','status_reviewed_at':'now','status_review_source':'user review'}
            if key=='subset':a['coalesces_into_source_snapshot_key']='closed'
            actions.append(a)
        self.interpretation={'review_hash':self.report['review_hash'],'current_hash':fingerprint(self.current),
                             'export_hash':digest(self.decisions),'original_export':copy.deepcopy(self.decisions),'actions':actions}

    def candidate(self):return reviewed_candidate(self.current,self.report,self.decisions,self.interpretation)

    def test_retains_geometry_and_detour_coalesces_closure_without_duplicate(self):
        result=self.candidate();features={f['id']:f for f in result['features']}
        self.assertEqual(len(features),3)
        self.assertEqual(features['detour'],feature('detour'))
        self.assertEqual(features['main']['geometry'],feature('main')['geometry'])
        self.assertEqual(features['main']['properties']['Name'],'Rivanna Trail')
        self.assertEqual(features['main']['properties']['access_status'],'temporarily-closed')
        self.assertEqual(result['ingest_report']['changes']['deleted'],[])
        self.assertEqual(result['ingest_report']['changes']['geometry_changed'],[])
        self.assertEqual(self.current['features'][0],feature('main'))

    def test_stale_baseline_notes_and_source_geometry_are_rejected(self):
        self.current['features'][0]['properties']['color']='blue'
        with self.assertRaisesRegex(ValueError,'baseline'):self.candidate()
        self.setUp();self.decisions['decisions']['new']['note']='Changed note'
        with self.assertRaisesRegex(ValueError,'export'):self.candidate()
        self.setUp();self.interpretation['actions'][0]['source_geometry_hash']='wrong'
        with self.assertRaisesRegex(ValueError,'identity or geometry'):self.candidate()

    def test_missing_action_colliding_id_and_wrong_subset_are_rejected(self):
        self.interpretation['actions'].pop()
        with self.assertRaisesRegex(ValueError,'exactly one'):self.candidate()
        self.setUp();self.interpretation['actions'][0]['proposed_feature_id']='main'
        with self.assertRaisesRegex(ValueError,'stable semantic ID'):self.candidate()
        self.setUp();self.interpretation['actions'][2]['coalesces_into_source_snapshot_key']='detour'
        with self.assertRaisesRegex(ValueError,'same marked'):self.candidate()

    def test_style_preserves_all_other_settings_and_normal_colors(self):
        style={'sources':{},'layers':[{'id':'other','type':'line','paint':{'line-color':'blue'}},
                 {'id':'rivanna-trail fringe','type':'line','source-layer':'Rivanna_Trail','paint':{'line-color':'darkgreen','line-width':3}},
                 {'id':'rivanna-trail','type':'line','source-layer':'Rivanna_Trail','paint':{'line-color':'green','line-width':2}},
                 {'id':'rivanna-trail-label','type':'symbol','source-layer':'Rivanna_Trail','layout':{'text-field':['get','Name']}}]}
        result=closure_style(style)
        self.assertEqual(result['layers'][0],style['layers'][0])
        self.assertEqual([l['id'] for l in result['layers']],[l['id'] for l in style['layers']])
        for old,new in zip(style['layers'][1:3],result['layers'][1:3]):
            self.assertEqual(new['paint']['line-color'][-1],old['paint']['line-color'])
            self.assertEqual(new['paint']['line-width'],old['paint']['line-width'])
        self.assertIn('TEMPORARILY CLOSED',str(result['layers'][-1]))
        style['layers'][1]['source-layer']='Other'
        with self.assertRaisesRegex(ValueError,'identity'):closure_style(style)


if __name__=='__main__':unittest.main()
