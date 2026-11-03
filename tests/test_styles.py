import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from maintenance.common import digest, read_json, write_json
from maintenance.geo import fingerprint
from maintenance.styles import hide_layers, retire_style_layers


class StyleRetirementTests(unittest.TestCase):
    def test_retirement_keeps_other_layers_and_refuses_wrong_sources(self):
        style={'layers':[{'id':'old','source-layer':'Old','paint':{'line-color':'red'}}, {'id':'rt','source-layer':'RT'}]}
        after=hide_layers(style,['old'],{'Old'})
        self.assertNotIn('layout',style['layers'][0])
        self.assertEqual(after['layers'][1],style['layers'][1])
        self.assertEqual(after['layers'][0]['layout'],{'visibility':'none'})
        with self.assertRaises(ValueError):hide_layers(style,['rt'],{'Old'})
        with self.assertRaises(ValueError):hide_layers(style,['missing'],{'Old'})

    def test_publish_preserves_draft_edits_archives_data_and_refuses_replay(self):
        fc={'type':'FeatureCollection','features':[]}
        style={'version':8,'name':'Trails','metadata':{'editor':'keep'},'created':'old','modified':'old',
               'layers':[{'id':'old','source-layer':'Old'}, {'id':'rt','source-layer':'RT'}]}
        draft={**style,'name':'Unrelated draft name','draft':True}
        policy={'protected_datasets':[{'dataset':'rt','source_layer':'RT'}]}
        class Client:
            username='owner';style_id='style'
            def __init__(self):self.versions={'styles/v1/owner/style':copy.deepcopy(style),'styles/v1/owner/style/draft':copy.deepcopy(draft)};self.writes=[]
            def features(self,dataset):return fc
            def style(self):return self.versions['styles/v1/owner/style']
            def call(self,url,method='GET',body=None):
                if method=='PATCH':
                    assert 'created' not in body and 'modified' not in body
                    self.versions[url]={**body,'created':'old','modified':'new'};self.writes.append(url)
                return copy.deepcopy(self.versions[url]),{}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);client=Client()
            write_json(root/'config/park-ownership.json',policy)
            proposed=hide_layers(style,['old'],{'Old'});write_json(root/'proposed.json',proposed)
            manifest={'policy_hash':digest(policy),'datasets':[{'target':'old','dataset':'old','publication_method':'retire-style-layers-keep-dataset','before_hash':fingerprint(fc)}],
                      'protected_datasets':[{'dataset':'rt','hash':fingerprint(fc)}],
                      'style_proposal':{'path':str(root/'proposed.json'),'before_hash':digest(style),'after_hash':digest(proposed),'hide_layers':['old']}}
            write_json(root/'manifest.json',manifest)
            with patch('maintenance.styles.ROOT',root),patch('maintenance.styles.target_by_id',return_value={'source_layer':'Old'}):
                result=retire_style_layers(client,root/'manifest.json',digest(manifest),root/'state')
                self.assertEqual(result['state'],'published')
                self.assertEqual(len(client.writes),2)
                self.assertEqual(client.versions['styles/v1/owner/style/draft']['name'],'Unrelated draft name')
                self.assertEqual(client.style()['layers'][1],style['layers'][1])
                backup=root/'state/backups'/f'style-{digest(manifest)}'
                self.assertEqual(read_json(backup/'old.geojson'),fc)
                with self.assertRaisesRegex(ValueError,'already attempted'):
                    retire_style_layers(client,root/'manifest.json',digest(manifest),root/'state')


if __name__=='__main__':unittest.main()
