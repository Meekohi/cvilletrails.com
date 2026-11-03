import copy
import tempfile
import unittest
from pathlib import Path

from maintenance.common import digest, read_json, write_json
from maintenance.geo import changes, fingerprint
from maintenance.mapbox import target_by_id
from maintenance.rivanna_candidate import closure_style
from maintenance.rivanna_publish import publish_style
from maintenance.styles import editable_style


class Client:
    username='meekohi'
    style_id='test'
    def __init__(self, data, style):
        self.data=data
        self.live=copy.deepcopy(style)
        self.draft=copy.deepcopy(style)
        self.draft['name']='Unrelated draft name'
        self.writes=[]
        self.fail=False
    def features(self, dataset):return copy.deepcopy(self.data)
    def call(self, path, method='GET', body=None, params=None):
        key='draft' if path.endswith('/draft') else 'live'
        if method=='PATCH':
            self.writes.append(key)
            setattr(self,key,{**copy.deepcopy(body),'modified':'updated'})
            if self.fail:raise RuntimeError('Unknown network outcome')
        return copy.deepcopy(getattr(self,key)),{}


class RivannaPublishTests(unittest.TestCase):
    def setUp(self):
        f={'type':'Feature','id':'retained','geometry':{'type':'LineString','coordinates':[[-78.5,38.03],[-78.49,38.04]]},'properties':{'Name':'Rivanna Trail'}}
        before={'type':'FeatureCollection','features':[f]}
        after=copy.deepcopy(before);after['features'][0]['properties']['access_status']='temporarily-closed'
        self.plan={'target':target_by_id('rivanna'),'before':before,'after':after,'before_hash':fingerprint(before),
                   'after_hash':fingerprint(after),'changes':changes(before,after),'ingest_report':{'interpretation_hash':'reviewed'}}
        self.plan['approval_hash']=digest(self.plan)
        self.style={'name':'Live name','layers':[
            {'id':'other','type':'line','paint':{'line-color':'blue'}},
            {'id':'rivanna-trail fringe','type':'line','source-layer':'Rivanna_Trail','paint':{'line-color':'darkgreen'}},
            {'id':'rivanna-trail','type':'line','source-layer':'Rivanna_Trail','paint':{'line-color':'green'}},
            {'id':'rivanna-trail-label','type':'symbol','source-layer':'Rivanna_Trail','layout':{'text-field':['get','Name']}}]}
        self.proposed=closure_style(self.style)
        self.manifest={'before_hash':fingerprint(before),'after_hash':fingerprint(after),'changes':changes(before,after),
                       'interpretation_hash':'reviewed','style_before_hash':digest(self.style),'style_after_hash':digest(self.proposed)}
        self.manifest['proposal_hash']=digest(self.manifest)
        self.client=Client(after,self.style)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.state=Path(self.tmp.name)
        self.receipt_path=self.state/'publishes'/f"{self.plan['approval_hash']}.json"
        self.receipt={'state':'published','target':self.plan['target'],'approval_hash':self.plan['approval_hash'],
                      'verification':{'stored_hash':fingerprint(after)}}
        write_json(self.receipt_path,self.receipt)

    def publish(self):return publish_style(self.client,self.plan,self.manifest,self.proposed,self.manifest['proposal_hash'],self.state)

    def test_updates_only_reviewed_layers_and_preserves_draft_work(self):
        result=self.publish()
        self.assertEqual(self.client.writes,['draft','live'])
        self.assertEqual(editable_style(self.client.live),self.proposed)
        self.assertEqual(self.client.draft['name'],'Unrelated draft name')
        self.assertEqual(self.client.live['layers'][0],self.style['layers'][0])
        self.assertEqual(result['state'],'published')
        backup=self.state/'backups'/f"rivanna-style-{self.manifest['proposal_hash']}"
        self.assertEqual(read_json(backup/'published.json'),self.style)
        with self.assertRaisesRegex(ValueError,'already attempted'):self.publish()
        self.assertEqual(len(self.client.writes),2)

    def test_rejects_unpublished_dataset_and_stale_data_or_style(self):
        self.receipt['state']='tileset-processing';write_json(self.receipt_path,self.receipt)
        with self.assertRaisesRegex(ValueError,'finish publication'):self.publish()
        self.receipt['state']='published';write_json(self.receipt_path,self.receipt)
        self.client.data=copy.deepcopy(self.plan['before'])
        with self.assertRaisesRegex(ValueError,'verification failed'):self.publish()
        self.client.data=copy.deepcopy(self.plan['after']);self.client.live['name']='Changed in Studio'
        with self.assertRaisesRegex(ValueError,'Live style changed'):self.publish()
        self.assertEqual(self.client.writes,[])

    def test_unknown_patch_outcome_cannot_be_replayed(self):
        self.client.fail=True
        with self.assertRaisesRegex(RuntimeError,'Unknown network'):self.publish()
        path=self.state/'publishes'/f"rivanna-style-{self.manifest['proposal_hash']}.json"
        self.assertEqual(read_json(path)['state'],'updating-draft')
        with self.assertRaisesRegex(ValueError,'already attempted'):self.publish()
        self.assertEqual(self.client.writes,['draft'])


if __name__=='__main__':unittest.main()
