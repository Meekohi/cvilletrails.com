import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from maintenance.common import RequestError, read_json, request
from maintenance.monitor import SourceFetcher, check
from maintenance.source_summary import render


class RetryTests(unittest.TestCase):
    def setUp(self):
        self.report = {'retries': []}
        self.fetch = SourceFetcher(self.report)
        self.fetch.source = 'test/page'

    def test_temporary_errors_retry_then_succeed(self):
        answer = (b'page', {}, 200)
        with patch('maintenance.monitor.request', side_effect=[RequestError('timeout'), RequestError('HTTP 503', 503), answer]) as get, patch('maintenance.monitor.time.sleep') as sleep:
            self.assertEqual(self.fetch('https://example.org'), answer)
        self.assertEqual(get.call_count, 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [2, 4])
        self.assertEqual([r['attempt'] for r in self.report['retries']], [2, 3])

    def test_permanent_failures_and_invalid_content_do_not_retry(self):
        for error in [RequestError('HTTP 403', 403), RequestError('HTTP 404', 404), ValueError('invalid content')]:
            with self.subTest(error=error), patch('maintenance.monitor.request', side_effect=error) as get:
                with self.assertRaises(type(error)):
                    self.fetch('https://example.org')
                self.assertEqual(get.call_count, 1)

    def test_attempt_limit_and_shared_budget_preserve_failure(self):
        with patch('maintenance.monitor.request', side_effect=RequestError('HTTP 503', 503)) as get, patch('maintenance.monitor.time.sleep'):
            with self.assertRaises(RequestError):
                self.fetch('https://example.org')
            self.assertEqual(get.call_count, 3)
            self.fetch.remaining = 2
            self.fetch.source = 'test/another'
            with self.assertRaises(RequestError) as caught:
                self.fetch('https://example.org/another')
            self.assertEqual(caught.exception.status, 503)
            self.assertEqual(get.call_count, 4)

    def test_retry_network_time_counts_against_budget(self):
        with patch('maintenance.monitor.request', side_effect=[RequestError('timeout'), (b'ok', {}, 200)]), patch('maintenance.monitor.time.sleep'), patch('maintenance.monitor.time.monotonic', side_effect=[0, 2, 22]):
            self.fetch('https://example.org')
        self.assertEqual(self.fetch.remaining, 98)

    def test_request_metadata_is_sanitized_and_does_not_retry_writes(self):
        error = HTTPError('https://secret.example/?token=secret', 503, 'secret', {}, io.BytesIO(b'secret'))
        with patch('maintenance.common.urlopen', side_effect=error) as send:
            with self.assertRaises(RequestError) as caught:
                request('https://secret.example', method='POST', body={'secret': 'secret'})
            self.assertEqual(send.call_count, 1)
            self.assertEqual(caught.exception.status, 503)
            self.assertTrue(caught.exception.retryable)
            self.assertNotIn('secret', str(caught.exception))
        with patch('maintenance.common.urlopen', side_effect=URLError('secret')):
            with self.assertRaises(RequestError) as caught:
                request('https://secret.example')
            self.assertIsNone(caught.exception.status)
            self.assertNotIn('secret', str(caught.exception))


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.source = {'id': 'page', 'kind': 'html', 'url': 'https://example.org',
            'manual_review_on_403': {'reason': 'Browser challenge', 'since': '2026-11-06', 'evidence': 'Saved run'}}
        self.config = {'id': 'test', 'system_ids': ['test'], 'sources': [self.source]}
        self.html = ('<p>' + 'trail notice ' * 30 + '</p>').encode()

    def test_known_403_is_visible_and_preserves_last_good_evidence_then_recovers(self):
        with tempfile.TemporaryDirectory() as tmp, patch('maintenance.monitor.configs', return_value=[self.config]):
            state = Path(tmp)
            with patch('maintenance.monitor.request', return_value=(self.html, {}, 200)):
                baseline = check(state_dir=state)
            self.assertEqual(baseline['sources'][0]['state'], 'baseline')
            saved = read_json(state / 'manifest.json')
            with patch('maintenance.monitor.request', side_effect=RequestError('HTTP 403', 403)) as get:
                blocked = check(state_dir=state)
            self.assertEqual(get.call_count, 1)
            self.assertFalse(blocked['errors'])
            self.assertFalse(blocked['sources'])
            self.assertEqual(blocked['status'], 'manual-review-required')
            self.assertEqual(blocked['manual_review'][0]['last_success'], saved['test/page']['checked_at'])
            self.assertEqual(read_json(state / 'manifest.json'), saved)
            self.assertTrue((state / baseline['sources'][0]['review']).exists())
            with patch('maintenance.monitor.request', return_value=(self.html + b'<p>New closure</p>', {}, 200)):
                recovered = check(state_dir=state)
            self.assertEqual(recovered['status'], 'complete')
            self.assertEqual(recovered['sources'][0]['state'], 'changed')
            self.assertFalse(recovered['manual_review'])

    def test_unknown_403_and_other_errors_still_fail_and_other_sources_continue(self):
        for registered, error in [(False, RequestError('HTTP 403', 403)), (True, RequestError('HTTP 404', 404)), (True, RequestError('timeout'))]:
            bad = dict(self.source)
            if not registered: bad.pop('manual_review_on_403')
            config = {**self.config, 'sources': [bad, {**self.source, 'id': 'other'}]}
            failures = [error] * (3 if error.retryable else 1)
            with self.subTest(error=error, registered=registered), tempfile.TemporaryDirectory() as tmp, patch('maintenance.monitor.configs', return_value=[config]), patch('maintenance.monitor.request', side_effect=failures + [(self.html, {}, 200)]), patch('maintenance.monitor.time.sleep'):
                report = check(state_dir=tmp)
            self.assertEqual(report['status'], 'failed')
            self.assertEqual(len(report['errors']), 1)
            self.assertFalse(report['manual_review'])
            self.assertEqual(report['sources'][0]['source'], 'test/other')

    def test_first_block_never_creates_a_baseline_or_claims_success(self):
        with tempfile.TemporaryDirectory() as tmp, patch('maintenance.monitor.configs', return_value=[self.config]), patch('maintenance.monitor.request', side_effect=RequestError('HTTP 403', 403)):
            report = check(state_dir=tmp)
            self.assertEqual(read_json(Path(tmp) / 'manifest.json'), {})
        self.assertIsNone(report['manual_review'][0]['last_success'])
        summary = render(report)
        self.assertIn('0 sources checked successfully; 1 require manual review', summary)
        self.assertIn('not checked', summary)
        self.assertIn('https://example.org', summary)

    def test_arcgis_pages_use_the_same_read_only_retry_policy(self):
        config = {**self.config, 'sources': [{**self.source, 'kind': 'arcgis'}]}
        def arcgis(url, request_fn):
            request_fn(url + '/query')
            return b'{"type":"FeatureCollection","features":[]}'
        with tempfile.TemporaryDirectory() as tmp, patch('maintenance.monitor.configs', return_value=[config]), patch('maintenance.monitor.fetch_arcgis', side_effect=arcgis), patch('maintenance.monitor.request', side_effect=[RequestError('timeout'), (b'{}', {}, 200)]), patch('maintenance.monitor.time.sleep'), patch('maintenance.monitor.run_adapter', return_value={'type':'FeatureCollection','features':[]}):
            report = check(state_dir=tmp)
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(len(report['retries']), 1)

    def test_summary_includes_failures_and_escapes_untrusted_text(self):
        report = {'checked_at': 'now', 'sources': [{'source': 'a', 'state': 'baseline', 'review': 'reviews/a.json'}],
            'errors': [{'source': 'b', 'error': '<script> | bad\nline'}]}
        summary = render(report)
        self.assertIn('run failed', summary)
        self.assertIn('New baselines: 1', summary)
        self.assertNotIn('<script>', summary)
        self.assertIn('&#124;', summary)


if __name__ == '__main__':
    unittest.main()
