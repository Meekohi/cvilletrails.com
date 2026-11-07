import tempfile
import unittest
from pathlib import Path
from maintenance.common import digest,write_json
from maintenance.geo import fingerprint
from maintenance.trail_exceptions import recommendation,verify_acceptance,import_preferences


def row(**kwargs):return {'id':'one','name':'SIDE TRAIL','status':'overlap-hold',**kwargs}


def feature(fid='one'):return {'type':'Feature','id':fid,'properties':{},'geometry':{'type':'LineString','coordinates':[[-79,38],[-79,38.01]]}}


class SourcePreferenceTests(unittest.TestCase):
    def test_current_official_at_beats_unproven_old_import_and_usfs_patchwork(self):
        category,action,_,reason,options=recommendation(row(name='APPALACHIAN TRAIL'),[],[])
        self.assertEqual((category,action),('appalachian','official-at'))
        self.assertIn('route-wide',reason);self.assertIn('official-at',options)

    def test_official_park_data_is_not_treated_as_strava_geometry(self):
        match={'properties':{'reference_source':'Strava Sidetrails','pipeline_id':'virginia-state-parks'}}
        self.assertEqual(recommendation(row(status='duplicate'),[match],[])[1],'existing')
        self.assertEqual(recommendation(row(),[match],[])[1],'split')

    def test_patc_survey_quality_is_retained_as_evidence(self):
        result=recommendation(row(name='TUSCARORA - POND RUN'),[{'properties':{'reference_source':'meekohi.8n5896es'}}],[])
        self.assertEqual(result[1],'incoming');self.assertIn('differential-GPS',result[3]);self.assertIn('does not prove better geometry',result[3])

    def test_same_official_source_and_crossings_do_not_get_blind_winner(self):
        self.assertEqual(recommendation(row(status='incoming-overlap'),[],[])[1],'shared')
        self.assertEqual(recommendation(row(name='SPY ROCK'),[],[])[0],'at-junctions')

    def test_sandy_gap_is_resolved_and_access_holds_cannot_be_approved(self):
        resolved=recommendation(row(status='alternate-source'),[],[])
        self.assertEqual(resolved[0],'resolved');self.assertEqual(resolved[4],[])
        self.assertEqual(recommendation(row(status='access-hold'),[],[])[4],['hold'])


class AcceptanceTests(unittest.TestCase):
    def test_confirmed_choices_and_access_receipts_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            report={'kind':'tnc-usfs-source-exceptions','acceptance_hash':'batch','rows':[
                {'id':'at','category':'appalachian','options':['official-at','existing']},
                {'id':'access','category':'access','options':['hold']}]}
            report['review_hash']=digest(report)
            source={'review_hash':report['review_hash'],'acceptance_hash':'batch','decisions':{'at':'official-at'}}
            source['decision_hash']=digest(source)
            access={'review_hash':report['review_hash'],'acceptance_hash':'batch','rows':[{'id':'access','action':'approve'}]}
            access['decision_hash']=digest(access)
            for filename,value in [('exceptions.json',report),('confirmed-decisions.json',source),('access-decisions.json',access)]:write_json(root/filename,value)
            value={'kind':report['kind'],'review_hash':report['review_hash'],'acceptance_hash':'batch',
                   'confirmed_hash':source['decision_hash'],'access_hash':access['decision_hash'],
                   'decisions':{'at':'official-at','access':'hold'}}
            def check():
                write_json(root/'input.json',value)
                return import_preferences(root,root/'input.json',root/'output.json')
            self.assertTrue(check()['review_only'])
            value['decisions']['at']='existing'
            with self.assertRaisesRegex(ValueError,'already confirmed'):check()
            value['decisions']['at']='official-at';value['access_hash']='stale'
            with self.assertRaisesRegex(ValueError,'predates'):check()
            value['access_hash']=access['decision_hash'];access['rows'][0]['action']='reject'
            write_json(root/'access-decisions.json',access)
            with self.assertRaisesRegex(ValueError,'decisions changed'):check()

    def fixture(self,root):
        data={'type':'FeatureCollection','features':[feature()]}
        report={'rows':[row(status='proposed')],'incoming_hash':fingerprint(data)};report['review_hash']=digest(report)
        decisions={'review_hash':report['review_hash'],'decisions':{'one':'include'}}
        receipt={'review_hash':report['review_hash'],'decision_hash':digest(decisions),'accepted_feature_ids':['one'],'accepted_geometry_hash':fingerprint(data),'style_proposal_hash':digest({}),'systems_proposal_hash':digest([])}
        for path,value in [('review.json',report),('incoming.geojson',data),('accepted/receipt.json',receipt),('accepted/user-decisions.json',decisions),('accepted/additions.geojson',data),('style-proposal.json',{}),('systems-proposal.json',[])]:write_json(root/path,value)
        return data

    def test_acceptance_and_supplementary_proposals_are_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=self.fixture(root);verify_acceptance(root)
            data['features'][0]['geometry']['coordinates'][0][0]=-80;write_json(root/'accepted/additions.geojson',data)
            with self.assertRaisesRegex(ValueError,'geometry changed'):verify_acceptance(root)
            self.fixture(root);write_json(root/'style-proposal.json',{'altered':True})
            with self.assertRaisesRegex(ValueError,'supporting proposal'):verify_acceptance(root)

    def test_feedback_can_only_record_preferences_for_unresolved_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);report={'kind':'tnc-usfs-source-exceptions','acceptance_hash':'approved-batch','rows':[{'id':'access','options':['hold']},{'id':'sandy','options':[]}]};report['review_hash']=digest(report)
            write_json(root/'exceptions.json',report)
            value={'kind':report['kind'],'review_hash':report['review_hash'],'acceptance_hash':'approved-batch','decisions':{'access':'hold'}}
            write_json(root/'input.json',value)
            result=import_preferences(root,root/'input.json',root/'output.json');self.assertTrue(result['review_only'])
            value['decisions']['access']='incoming';write_json(root/'input.json',value)
            with self.assertRaisesRegex(ValueError,'Unsupported'):import_preferences(root,root/'input.json',root/'output.json')
            value['decisions']={'access':'hold','sandy':'incoming'};write_json(root/'input.json',value)
            with self.assertRaisesRegex(ValueError,'every unresolved'):import_preferences(root,root/'input.json',root/'output.json')
            value['decisions']={'access':'hold'};value['acceptance_hash']='other';write_json(root/'input.json',value)
            with self.assertRaisesRegex(ValueError,'accepted batch'):import_preferences(root,root/'input.json',root/'output.json')


if __name__=='__main__':unittest.main()
