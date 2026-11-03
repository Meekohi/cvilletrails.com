import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from maintenance.common import digest, read_json, write_json
from maintenance.consolidation import preserve_protected, validate_decisions, prepare_consolidation
from maintenance.geo import fingerprint, changes
from maintenance.mapbox import verify_ownership_policy

CITY='ckuppnp9h534y23pyswjd7n1a'
COUNTY='cjcm3ne8w0os033rw0ceoi0ye'
RT='cjawyutol0r7d2wo1z7eb0wiy'
RAGGED='ckfh5qbi7380826oij568hhbg'

def feature(fid, x1=-78.5, x2=-78.48):
    return {'type':'Feature','id':fid,'geometry':{'type':'LineString','coordinates':[[x1,38.03],[x2,38.03]]},'properties':{'name':'Curated trail','color':'blue'}}
def collection(*features):return {'type':'FeatureCollection','features':list(features)}


class ProtectedNetworkTests(unittest.TestCase):
    def test_even_a_partial_cut_of_rivanna_is_rejected(self):
        policy={'protected_datasets':[{'dataset':RT,'retain_entire_dataset':True}]}
        before={RT:collection(feature('rt'))};after=copy.deepcopy(before)
        preserve_protected(before,after,policy)
        after[RT]['features'][0]['geometry']['coordinates'][0][0]+=.001
        with self.assertRaisesRegex(ValueError,'protected Rivanna'):preserve_protected(before,after,policy)

    def test_publish_guard_rejects_rivanna_and_stale_policy(self):
        policy={'protected_datasets':[{'dataset':RT,'retain_entire_dataset':True}]}
        report={'park_consolidation':True,'ownership_policy_hash':digest(policy)}
        with patch('maintenance.mapbox.read_json',return_value=policy):
            with self.assertRaisesRegex(ValueError,'protected Rivanna'):verify_ownership_policy({'dataset':RT},report)
            verify_ownership_policy({'dataset':CITY},report)
            with self.assertRaisesRegex(ValueError,'policy changed'):verify_ownership_policy({'dataset':CITY},{**report,'ownership_policy_hash':'old'})

    def test_tampered_review_or_wrong_export_is_rejected(self):
        report={'plan_hash':'p','parks':[]};report['review_hash']=digest(report)
        validate_decisions(report,{'review_hash':report['review_hash'],'plan_hash':'p','decisions':{}})
        with self.assertRaises(ValueError):validate_decisions(report,{'review_hash':'other','plan_hash':'p'})
        report['parks'].append({'id':'invented'})
        with self.assertRaises(ValueError):validate_decisions(report,{'review_hash':report['review_hash'],'plan_hash':'p'})


@unittest.skipUnless(importlib.util.find_spec('shapely') and importlib.util.find_spec('pyproj'),'optional geometry dependencies not installed')
class ConsolidationGeometryTests(unittest.TestCase):
    def test_cross_boundary_trails_survive_and_empty_dataset_becomes_style_retirement(self):
        baseline=collection();proposal=collection(feature('city:new'))
        plan={'before':baseline,'after':proposal,'before_hash':fingerprint(baseline),'after_hash':fingerprint(proposal),'target':{'dataset':CITY},'changes':changes(baseline,proposal)}
        plan['approval_hash']=digest(plan)
        snapshots={CITY:baseline,COUNTY:collection(feature('county')),RT:collection(feature('rt')),RAGGED:collection(feature('track',-78.493,-78.487))}
        boundary={'type':'Polygon','coordinates':[[[-78.495,38.025],[-78.485,38.025],[-78.485,38.035],[-78.495,38.035],[-78.495,38.025]]]}
        style={'layers':[{'id':'ragged','source-layer':'Ragged_Mountain_Trails'},{'id':'rt','source-layer':'Rivanna_Trail'}]}
        report={'plan_hash':plan['approval_hash'],'style_hash':digest(style),'sources':[{'dataset':did,'hash':fingerprint(fc),'role':'trail-lines'} for did,fc in snapshots.items()],
                'parks':[{'id':'heyward','boundary':boundary,'datasets':[{'dataset':did} for did in snapshots]}]}
        report['review_hash']=digest(report)
        decisions={'review_hash':report['review_hash'],'plan_hash':plan['approval_hash'],'decisions':{'heyward':{'decision':'choose','dataset':CITY}}}
        policy={'protected_datasets':[{'dataset':RT,'retain_entire_dataset':True}],'parks':[{'id':'heyward','geometry_dataset':CITY,'mode':'winner'}]}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);out=root/'out'
            for did,fc in snapshots.items():write_json(root/'datasets'/f'{did}.geojson',fc)
            write_json(root/'style.json',style)
            result=prepare_consolidation(plan,report,decisions,policy,root,out)
            county=read_json(out/'albemarle.geojson')['features'][0]
            self.assertEqual(county['id'],'county');self.assertEqual(county['properties'],feature('county')['properties'])
            self.assertEqual(county['geometry']['type'],'MultiLineString')
            self.assertEqual(len(county['geometry']['coordinates']),2)
            self.assertTrue(result['protected_datasets'][0]['unchanged'])
            self.assertNotIn(RT,[r['dataset'] for r in result['datasets']])
            retired=next(r for r in result['datasets'] if r['dataset']==RAGGED)
            self.assertEqual(retired['publication_method'],'retire-style-layers-keep-dataset')
            proposed_style=read_json(out/'style-proposed.json')
            self.assertEqual(proposed_style['layers'][0]['layout']['visibility'],'none')
            self.assertEqual(proposed_style['layers'][1],style['layers'][1])
            self.assertEqual(len(read_json(out/'city.geojson')['features']),1)
            # A named connector exception keeps the complete reviewed feature,
            # even though the park otherwise chooses another dataset.
            policy['parks'][0]['retain_features'] = [{'dataset':COUNTY,'feature_id':'county','reason':'Keep the saddle connection'}]
            retained_result=prepare_consolidation(plan,report,decisions,policy,root,root/'retained')
            self.assertNotIn(COUNTY,[d['dataset'] for d in retained_result['datasets']])
            self.assertEqual(retained_result['retained_features'][0]['feature_id'],'county')
            self.assertTrue(retained_result['retained_features'][0]['unchanged'])
            policy['parks'][0]['retain_features'][0]['feature_id']='missing'
            with self.assertRaisesRegex(ValueError,'missing from the reviewed inventory'):
                prepare_consolidation(plan,report,decisions,policy,root,root/'missing')
            del policy['parks'][0]['retain_features']
            replacement={'dataset':COUNTY,'feature_id':'county','before_feature_hash':digest(feature('county')),
                         'geometry':feature('county',-78.49,-78.48)['geometry'],'reason':'Three user-selected northern junctions'}
            policy['parks'][0]['geometry_replacements']=[replacement]
            result=prepare_consolidation(plan,report,decisions,policy,root,root/'corrected')
            corrected=read_json(root/'corrected/albemarle.geojson')['features'][0]
            self.assertEqual(corrected['geometry'],replacement['geometry'])
            self.assertEqual(corrected['properties'],feature('county')['properties'])
            self.assertEqual(result['connector_replacements'][0]['feature_id'],'county')
            replacement['before_feature_hash']='stale'
            with self.assertRaisesRegex(ValueError,'reviewed source feature'):
                prepare_consolidation(plan,report,decisions,policy,root,root/'stale')
            replacement.update(dataset=RT,feature_id='rt',before_feature_hash=digest(feature('rt')))
            with self.assertRaisesRegex(ValueError,'protected or retained'):
                prepare_consolidation(plan,report,decisions,policy,root,root/'protected')


if __name__=='__main__':unittest.main()
