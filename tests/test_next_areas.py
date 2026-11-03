import copy
import unittest
from maintenance.common import STATE, digest
from maintenance.park_review import annotate_next_area_review, build_next_area_review


class NextAreaReviewTests(unittest.TestCase):
    def fixture(self):
        report={'plan_hash':'plan','parks':[
            {'id':'a','name':'A','review_feature_ids':['city:1'],'recommended_dataset':'city','cautions':[]},
            {'id':'b','name':'B','review_feature_ids':['city:2'],'recommended_dataset':'city','cautions':[]},
        ]}
        report['review_hash']=digest(report)
        assessment={'plan_hash':'plan','scope':'Additions only','source_verification':{'checked_at':'today'},'areas':[
            {'area_id':'a','feature_ids':['city:1'],'priority':2,'recommendation':'Inspect alignment'},
            {'area_id':'b','feature_ids':['city:2'],'priority':1,'recommendation':'Hold for access'},
        ]}
        return report,assessment

    def test_separate_hash_and_no_preselected_source_or_approval(self):
        report,assessment=self.fixture();original=copy.deepcopy(report)
        result=annotate_next_area_review(report,assessment)
        self.assertEqual(report,original)
        self.assertNotEqual(result['review_hash'],report['review_hash'])
        self.assertEqual(result['review_kind'],'remaining-additions')
        self.assertEqual(result['parks'][0]['id'],'b')
        self.assertTrue(all(p['recommended_dataset'] is None for p in result['parks']))
        self.assertNotIn('decisions',result)
        self.assertEqual(result['assessment_hash'],digest(assessment))

    def test_stale_or_incomplete_assessments_are_rejected(self):
        report,assessment=self.fixture()
        assessment['plan_hash']='other'
        with self.assertRaisesRegex(ValueError,'another plan'):annotate_next_area_review(report,assessment)
        assessment['plan_hash']='plan';assessment['areas'][0]['feature_ids']=['city:wrong']
        with self.assertRaisesRegex(ValueError,'feature IDs'):annotate_next_area_review(report,assessment)
        assessment['areas'].pop()
        with self.assertRaisesRegex(ValueError,'exactly the reviewed areas'):annotate_next_area_review(report,assessment)

    def test_tampered_report_and_old_output_are_rejected(self):
        report,assessment=self.fixture();report['parks'][0]['name']='Changed'
        with self.assertRaisesRegex(ValueError,'contents'):annotate_next_area_review(report,assessment)
        with self.assertRaisesRegex(ValueError,'separate output'):
            build_next_area_review(None,None,None,None,None,STATE/'review-parks')


if __name__=='__main__':unittest.main()
