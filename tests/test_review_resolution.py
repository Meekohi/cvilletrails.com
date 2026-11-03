import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path
from maintenance.common import ROOT, digest, read_json, write_json
from maintenance.geo import fingerprint, changes
from maintenance.review_map import build_resolution_context, reviewed_candidate, verify_resolution_context


def feature(fid, x1=-78.5, x2=-78.48, y=38.03, **properties):
    return {'type':'Feature','id':fid,'properties':{'name':fid,**properties},'geometry':{'type':'LineString','coordinates':[[x1,y],[x2,y]]}}
def fc(*features): return {'type':'FeatureCollection','features':list(features)}
def plan(before,after):
    p={'before':before,'after':after,'before_hash':fingerprint(before),'after_hash':fingerprint(after),'target':{'id':'city','dataset':'city','tileset':'owner.city','source_layer':'City'},'changes':changes(before,after)}
    p['approval_hash']=digest(p)
    return p

def context(p,baseline,resolutions=None):
    c={'plan_hash':p['approval_hash'],'target':p['target'],'current_baseline':baseline,'current_hash':fingerprint(baseline),'resolutions':resolutions or {},'policy_hash':digest(read_json(ROOT/'config/park-ownership.json'))}
    c['context_hash']=digest(c)
    return c

def decisions(p,c,items):return {'plan_hash':p['approval_hash'],'resolution_context_hash':c['context_hash'],'decisions':items}


class ResolutionCandidateTests(unittest.TestCase):
    def test_old_accepts_cannot_restore_split_or_excluded_city_lines(self):
        p=plan(fc(),fc(feature('city:3076'),feature('ivy')))
        baseline=fc(feature('city:3076',-78.49,-78.48))
        c=context(p,baseline,{'city:3076':{'accept_allowed':False},'ivy':{'accept_allowed':False}})
        for fid in ('city:3076','ivy'):
            with self.assertRaisesRegex(ValueError,'whole-proposal acceptance is blocked'):
                reviewed_candidate(p,decisions(p,c,{fid:{'decision':'accept'}}),c)
        exported=decisions(p,c,{'city:3076':{'decision':'discuss','note':'Check northern end'}})
        exported['historical_decisions']={'ivy':{'decision':'accept','note':'Old duplicate acceptance'}}
        candidate=reviewed_candidate(p,exported,c)
        self.assertEqual(fingerprint(candidate),fingerprint(baseline))
        self.assertEqual(candidate['ingest_report']['historical_decisions'],exported['historical_decisions'])
        self.assertEqual(candidate['ingest_report']['reviewed_before_hash'],fingerprint(baseline))

    def test_metadata_acceptance_preserves_new_geometry_and_unrelated_curation(self):
        before=feature('old',color='blue')
        proposed=copy.deepcopy(before);proposed['properties']['source_url']='https://example.org/trails'
        p=plan(fc(before),fc(proposed))
        live=feature('old',-78.499,-78.481,color='purple',name='Updated name')
        baseline=fc(live,feature('published-addition'))
        c=context(p,baseline)
        result=reviewed_candidate(p,decisions(p,c,{'old':{'decision':'accept'}}),c)
        actual=next(f for f in result['features'] if f['id']=='old')
        self.assertEqual(actual['geometry'],live['geometry'])
        self.assertEqual(actual['properties'],{**live['properties'],'source_url':'https://example.org/trails'})
        self.assertEqual(len(result['features']),2)

    def test_rebase_refuses_changed_deletions_and_null_presence_conflicts(self):
        original=feature('old')
        p=plan(fc(original),fc())
        c=context(p,fc(feature('old',access='private')))
        with self.assertRaisesRegex(ValueError,'Deletion would remove a feature changed'):
            reviewed_candidate(p,decisions(p,c,{'old':{'decision':'accept'}}),c)
        proposed=copy.deepcopy(original);proposed['properties']['access']='yes'
        p=plan(fc(original),fc(proposed));c=context(p,fc(feature('old',access=None)))
        with self.assertRaisesRegex(ValueError,'property changed'):
            reviewed_candidate(p,decisions(p,c,{'old':{'decision':'accept'}}),c)

    def test_stale_or_missing_context_and_new_policy_are_rejected(self):
        p=plan(fc(),fc(feature('new')));c=context(p,fc())
        selection=decisions(p,c,{})
        with self.assertRaisesRegex(ValueError,'requires its resolution context'):reviewed_candidate(p,selection)
        tampered=copy.deepcopy(c);tampered['current_baseline']=fc(feature('tampered'))
        with self.assertRaisesRegex(ValueError,'hash'):verify_resolution_context(p,tampered)
        with self.assertRaisesRegex(ValueError,'current resolution context'):reviewed_candidate(p,{**selection,'resolution_context_hash':'old'},c)
        c['policy_hash']='old';c['context_hash']=digest({k:v for k,v in c.items() if k!='context_hash'})
        with self.assertRaisesRegex(ValueError,'Ownership policy changed'):reviewed_candidate(p,decisions(p,c,{}),c)


@unittest.skipUnless(importlib.util.find_spec('shapely') and importlib.util.find_spec('pyproj'),'optional geometry dependencies not installed')
class ResolutionClassificationTests(unittest.TestCase):
    def test_published_split_owner_exclusion_and_unmatched_exception(self):
        split=feature('split');excluded=feature('excluded',-78.499,-78.492)
        unmatched=feature('unmatched',-78.499,-78.492,y=38.032)
        published=feature('published',-78.488,-78.482)
        p=plan(fc(),fc(split,excluded,unmatched,published))
        current_city=fc(feature('split',-78.49,-78.48),published)
        county=fc(feature('county',-78.5,-78.49))
        boundary={'type':'Polygon','coordinates':[[[-78.501,38.025],[-78.49,38.025],[-78.49,38.035],[-78.501,38.035],[-78.501,38.025]]]}
        policy={'parks':[{'id':'park','geometry_dataset':'county','mode':'winner'}]}
        report={'plan_hash':p['approval_hash'],'parks':[{'id':'park','name':'Park','boundary':boundary}],
                'sources':[{'dataset':'city','hash':fingerprint(fc())},{'dataset':'county','hash':fingerprint(county)}]}
        report['review_hash']=digest(report)
        manifest={'plan_hash':p['approval_hash'],'review_hash':report['review_hash'],'policy_hash':digest(policy),
                  'datasets':[{'dataset':'city','target':'city','publication_method':'reviewed-dataset-update'}]}
        style={'layers':[]}
        audit={'prepared_changes':manifest,'publication_receipt':{'status':'published','manifest_hash':digest(manifest),'finished_at':'now','datasets':[{'target':'city','stored_hash':fingerprint(current_city)}],'style_readback':{'published':{'hash':digest(style)}}},
               'publication_status':'published_and_verified','approval':{'manifest_hash':digest(manifest)},'policy_hash':digest(policy),
               'original_export':{'decisions':{'park':{'decision':'choose','dataset':'county'}}}}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);write_json(root/'datasets/city.geojson',current_city);write_json(root/'datasets/county.geojson',county);write_json(root/'style.json',style)
            c=build_resolution_context(p,audit,report,policy,root)
            self.assertEqual(c['resolutions']['published']['status'],'published')
            self.assertEqual(c['resolutions']['split']['status'],'split-published')
            self.assertFalse(c['resolutions']['split']['needs_review'])
            self.assertEqual(c['resolutions']['excluded']['status'],'excluded-by-owner')
            self.assertTrue(c['resolutions']['unmatched']['needs_review'])
            self.assertFalse(c['resolutions']['unmatched']['accept_allowed'])
            self.assertEqual(c['current_hash'],fingerprint(current_city))
            self.assertEqual(p['approval_hash'],c['plan_hash'])
            verify_resolution_context(p,c)
            pending=copy.deepcopy(audit);pending['publication_receipt']['status']='prepared'
            with self.assertRaisesRegex(ValueError,'requires a published'):build_resolution_context(p,pending,report,policy,root)
            write_json(root/'style.json',{'layers':[{'id':'changed'}]})
            with self.assertRaisesRegex(ValueError,'Current style differs'):build_resolution_context(p,audit,report,policy,root)
            write_json(root/'style.json',style)
            write_json(root/'datasets/city.geojson',fc())
            with self.assertRaisesRegex(ValueError,'Current inventory differs'):build_resolution_context(p,audit,report,policy,root)


if __name__=='__main__':unittest.main()
