import copy
import unittest
from maintenance.common import digest
from maintenance.geo import changes, fingerprint
from maintenance.park_review import remaining_addition_candidate


def feature(fid):
    return {'type': 'Feature', 'id': fid, 'properties': {'name': fid, 'color': 'curated'},
            'geometry': {'type': 'LineString', 'coordinates': [[-78.5, 38.03], [-78.49, 38.03]]}}


class RemainingAdditionCandidateTests(unittest.TestCase):
    def fixture(self):
        before = {'type': 'FeatureCollection', 'features': [feature('published')]}
        after = {'type': 'FeatureCollection', 'features': [feature(fid) for fid in ('published', 'new', 'held', 'excluded')]}
        plan = {'before': before, 'after': after, 'before_hash': fingerprint(before), 'after_hash': fingerprint(after),
                'target': {'id': 'city', 'dataset': 'city'}, 'changes': changes(before, after)}
        plan['approval_hash'] = digest(plan)
        report = {'review_kind': 'remaining-additions', 'plan_hash': plan['approval_hash'],
                  'parks': [{'id': fid, 'review_feature_ids': [fid]} for fid in ('new', 'held', 'excluded')]}
        report['review_hash'] = digest(report)
        decisions = {'schema_version': 2, 'review_kind': 'remaining-additions', 'plan_hash': plan['approval_hash'],
                     'review_hash': report['review_hash'], 'decisions': {
                         fid: {'decision': choice, 'dataset': None, 'feature_ids': [fid], 'note': 'User note'}
                         for fid, choice in [('new', 'include'), ('held', 'discuss'), ('excluded', 'keep-existing')]}}
        return plan, report, decisions

    def test_only_explicit_includes_are_added_without_mutating_baseline(self):
        plan, report, decisions = self.fixture()
        original = copy.deepcopy(plan)
        candidate = remaining_addition_candidate(plan, report, decisions)
        self.assertEqual(plan, original)
        self.assertEqual(changes(plan['before'], candidate)['added'], ['new'])
        self.assertEqual(changes(plan['before'], candidate)['changed'], [])
        self.assertEqual(changes(plan['before'], candidate)['deleted'], [])
        self.assertEqual(candidate['ingest_report']['held_for_discussion'], ['held'])
        self.assertEqual(candidate['ingest_report']['decisions'], decisions['decisions'])
        self.assertEqual(candidate['ingest_report']['reviewed_before_hash'], plan['before_hash'])

    def test_missing_decisions_remain_unreviewed(self):
        plan, report, decisions = self.fixture()
        decisions['decisions'].pop('new')
        candidate = remaining_addition_candidate(plan, report, decisions)
        self.assertEqual(fingerprint(candidate), plan['before_hash'])
        self.assertEqual(candidate['ingest_report']['unreviewed'], ['new'])

    def test_stale_export_wrong_ids_and_ownership_exports_are_rejected(self):
        plan, report, decisions = self.fixture()
        for mutate in (
            lambda d: d.update(review_hash='other'),
            lambda d: d.update(review_kind='park-ownership'),
            lambda d: d['decisions']['new'].update(feature_ids=['held']),
            lambda d: d['decisions']['new'].update(dataset='replace-rt'),
            lambda d: d['decisions'].update(unknown={'decision': 'include'}),
        ):
            changed = copy.deepcopy(decisions); mutate(changed)
            with self.assertRaises(ValueError): remaining_addition_candidate(plan, report, changed)

    def test_changed_existing_features_cannot_be_smuggled_into_additions_plan(self):
        plan, report, decisions = self.fixture()
        plan['after']['features'][0]['properties']['color'] = 'changed'
        plan['after_hash'] = fingerprint(plan['after'])
        plan['changes'] = changes(plan['before'], plan['after'])
        plan['approval_hash'] = digest({k: v for k, v in plan.items() if k != 'approval_hash'})
        report['plan_hash'] = decisions['plan_hash'] = plan['approval_hash']
        report['review_hash'] = digest({k: v for k, v in report.items() if k != 'review_hash'})
        decisions['review_hash'] = report['review_hash']
        with self.assertRaisesRegex(ValueError, 'cannot edit or delete'):
            remaining_addition_candidate(plan, report, decisions)


if __name__ == '__main__': unittest.main()
