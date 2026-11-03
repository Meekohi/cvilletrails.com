import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from maintenance.common import digest, read_json, write_json, configs
from maintenance.geo import validate_collection, canonical, changes, normalize, fingerprint
from maintenance.ingest import fetch_arcgis, run_adapter
from maintenance.mapbox import Mapbox, make_plan, apply_plan, resume_publish, verify_written, stored_coordinates
from maintenance.monitor import check, extract
from maintenance.reconcile import reconcile
from maintenance.review import record_review
from maintenance.site import validate_updates, approve_notice
from maintenance.review_map import review_rows, reviewed_candidate
from maintenance.connections import connect_endpoints


def feature(fid='a', **props):
    return {'type': 'Feature', 'id': fid, 'geometry': {'type': 'LineString', 'coordinates': [[-78.5, 38], [-78.51, 38.01]]}, 'properties': props}


def collection(*features): return {'type': 'FeatureCollection', 'features': list(features)}


class GeometryTests(unittest.TestCase):
    def test_bad_geometry_duplicate_ids_and_crs_fail(self):
        for data in [collection(feature(), feature()), {**collection(feature()), 'crs': 'EPSG:3857'}, collection({**feature(), 'geometry': None})]:
            with self.assertRaises(ValueError): validate_collection(data)
        bad = feature(); bad['geometry']['coordinates'][0][0] = float('nan')
        with self.assertRaises(ValueError): validate_collection(collection(bad))

    def test_order_and_api_metadata_do_not_create_changes(self):
        a, b = feature('a'), feature('b')
        self.assertEqual(fingerprint(collection(a, b)), fingerprint({**collection(b, a), 'bbox': [1, 2, 3, 4]}))

    def test_reconcile_keeps_ids_colors_and_missing_features(self):
        old = collection(feature('curated', OBJECTID=1, color='red'), feature('missing', OBJECTID=2))
        new = collection(feature('city:1', source_feature_id='1', color='blue'))
        result = reconcile(old, new, 'OBJECTID', ['color'])
        self.assertEqual([f['id'] for f in result['features']], ['curated', 'missing'])
        self.assertEqual(result['features'][0]['properties']['color'], 'red')
        self.assertEqual(result['ingest_report']['retained_missing_upstream'], ['missing'])
        self.assertEqual(len(result['ingest_report']['property_conflicts']), 1)

    def test_city_quarantines_proposed_and_null_geometry(self):
        data = collection(feature('1', NAME='Open', STATUS='Existing'), feature('2', NAME='Future', STATUS='Proposed'), {**feature('3', STATUS='Existing'), 'geometry': None})
        # Exercise filtering independently of the real park junction.
        with tempfile.TemporaryDirectory() as tmp:
            config = configs('city')[0]
            (Path(tmp) / 'ingest.py').write_text((config['_directory'] / 'ingest.py').read_text())
            write_json(Path(tmp) / 'overrides.json', {})
            write_json(Path(tmp) / 'connections.json', [])
            config['_directory'] = Path(tmp)
            result = run_adapter(data, config, 'city-gis')
        self.assertEqual(len(result['features']), 1)
        self.assertEqual(result['ingest_report']['excluded_empty_geometry'], ['3'])
        self.assertEqual(result['ingest_report']['excluded_nonexisting'], ['2'])

    def test_reconcile_preserves_roundoff_but_keeps_real_geometry_changes(self):
        old = collection(feature('curated', OBJECTID=1))
        new = collection(feature('city:1', source_feature_id='1'))
        new['features'][0]['geometry']['coordinates'][0][0] += 0.0000001
        result = reconcile(old, new, 'OBJECTID', [])
        self.assertEqual(result['features'][0]['geometry'], old['features'][0]['geometry'])
        self.assertEqual(result['ingest_report']['preserved_submeter_geometry'], ['curated'])
        new['features'][0]['geometry']['coordinates'][0][0] += 0.001
        result = reconcile(old, new, 'OBJECTID', [])
        self.assertNotEqual(result['features'][0]['geometry'], old['features'][0]['geometry'])

    def test_overrides_are_repeatable_and_orphans_stop_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = {'id': 'test', 'system_id': 'test', '_directory': Path(tmp), 'fields': {'id': 'oid', 'name': 'NAME'}, 'sources': [{'id': 'gis', 'url': 'https://example.org'}]}
            write_json(Path(tmp) / 'overrides.json', {'1': {'feature_id': 'curated', 'properties': {'color': 'red'}}})
            source = collection(feature('upstream', oid=1, NAME='Trail'))
            first = normalize(source, config, 'gis')
            self.assertEqual(first, normalize(source, config, 'gis'))
            self.assertEqual(first['features'][0]['id'], 'curated')
            self.assertEqual(first['features'][0]['properties']['color'], 'red')
            with self.assertRaises(ValueError): normalize(collection(), config, 'gis')

    def test_partial_arcgis_response_is_rejected(self):
        answers = [({'objectIds': [1, 2]}, {}, 200), (collection(feature('1')), {}, 200)]
        with patch('maintenance.ingest.request', side_effect=[(json.dumps(v).encode(), h, c) for v, h, c in answers]):
            with self.assertRaisesRegex(ValueError, 'incomplete'): fetch_arcgis('https://example.org/MapServer/1')


class MonitorTests(unittest.TestCase):
    def test_random_tab_anchors_do_not_trigger_source_changes(self):
        one = b'<a href="#random-one">Trails</a><script>clock=123</script><a href="/map.pdf">Map</a>'
        two = b'<a href="#random-two">Trails</a><script>clock=456</script><a href="/map.pdf">Map</a>'
        self.assertEqual(extract(one, 'html'), extract(two, 'html'))
        self.assertIn('/map.pdf', extract(one, 'html'))
    def test_baseline_304_changes_and_errors_preserve_evidence(self):
        source = {'id': 'page', 'kind': 'html', 'url': 'https://example.org', 'label': 'Example'}
        config = {'id': 'test', 'system_ids': ['test'], 'sources': [source]}
        html = ('<p>Trail notice: ' + 'open ' * 30 + '</p>').encode()
        with tempfile.TemporaryDirectory() as tmp, patch('maintenance.monitor.configs', return_value=[config]):
            state = Path(tmp)
            with patch('maintenance.monitor.request', return_value=(html, {'ETag': 'one'}, 200)):
                first = check(state_dir=state)
            manifest = read_json(state / 'manifest.json')
            review = state / first['sources'][0]['review']
            self.assertEqual(read_json(review)['change_type'], 'baseline')
            with patch('maintenance.monitor.request', return_value=(b'', {}, 304)):
                self.assertEqual(check(state_dir=state)['sources'][0]['state'], 'unchanged')
            with patch('maintenance.monitor.request', side_effect=RuntimeError('HTTP 403')):
                self.assertEqual(len(check(state_dir=state)['errors']), 1)
            self.assertEqual(read_json(state / 'manifest.json')['test/page']['sha256'], manifest['test/page']['sha256'])
            with patch('maintenance.monitor.request', return_value=(html + b'<p>Bridge closed.</p>', {}, 200)):
                updated = check(state_dir=state)
            self.assertIn('Bridge closed', read_json(state / updated['sources'][0]['review'])['diff'])
            self.assertTrue(review.exists())

    def test_failed_api_review_can_retry_without_source_change(self):
        config = {'id': 'test', 'system_ids': ['test'], 'sources': [{'id': 'page', 'kind': 'html', 'url': 'https://example.org'}]}
        html = ('<p>' + 'trail ' * 30 + '</p>').encode()
        with tempfile.TemporaryDirectory() as tmp, patch('maintenance.monitor.configs', return_value=[config]), patch('maintenance.monitor.request', return_value=(html, {}, 200)):
            with patch('maintenance.monitor.llm_review', side_effect=RuntimeError('quota')):
                self.assertTrue(check(use_llm=True, state_dir=tmp)['errors'])
            with patch('maintenance.monitor.llm_review', return_value={'result': {'notices': []}}) as reviewer:
                result = check(use_llm=True, state_dir=tmp)
                self.assertFalse(result['errors']); reviewer.assert_called_once()


class FakeMapbox:
    def __init__(self):
        self.data = collection(feature('a', name='Before', color='red'))
        self.modified = 'version1'
        self.writes = []
        self.uploads = []
    def features(self, dataset): return copy.deepcopy(self.data)
    def metadata(self, dataset): return {'modified': self.modified}
    def tileset(self, tileset): return {'vector_layers': [{'id': 'Trails'}]}
    def style(self): return {'sources': {'composite': {'url': 'mapbox://owner.existing'}}, 'layers': [{'source-layer': 'Trails'}]}
    def write_feature(self, dataset, f):
        self.writes.append(f['id'])
        self.data['features'] = [old for old in self.data['features'] if old['id'] != f['id']] + [copy.deepcopy(f)]
    def delete_feature(self, dataset, fid):
        self.writes.append(fid)
        self.data['features'] = [f for f in self.data['features'] if f['id'] != fid]
    def check_publish_tools(self): pass
    def upload(self, dataset, tileset, source_layer, stored_hash):
        self.uploads.append(tileset)
        return {'id': 'upload', 'complete': True, 'error': None}


class PublishingTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeMapbox()
        self.target = {'id': 'test', 'dataset': 'data', 'tileset': 'owner.existing', 'source_layer': 'Trails'}
        self.after = collection(feature('a', name='After', color='red'))
        self.plan = make_plan(self.client, self.target, self.after, 'official source snapshot')

    def test_tampering_and_concurrent_studio_edits_stop_before_writing(self):
        with patch('maintenance.mapbox.target_by_id', return_value=self.target):
            tampered = copy.deepcopy(self.plan); tampered['after']['features'][0]['properties']['color'] = 'blue'
            with self.assertRaises(ValueError): apply_plan(self.client, tampered, self.plan['approval_hash'])
            self.client.modified = 'version2'
            with self.assertRaisesRegex(ValueError, 'changed since review'): apply_plan(self.client, self.plan, self.plan['approval_hash'])
            self.assertFalse(self.client.writes)

    def test_backup_precedes_writes_and_default_does_not_publish(self):
        with tempfile.TemporaryDirectory() as tmp, patch('maintenance.mapbox.target_by_id', return_value=self.target), patch('maintenance.mapbox.time.sleep'):
            state = Path(tmp)
            original = self.client.write_feature
            def write(dataset, f):
                self.assertTrue((state / 'backups' / f"{self.plan['approval_hash']}.geojson").exists())
                original(dataset, f)
            self.client.write_feature = write
            result = apply_plan(self.client, self.plan, self.plan['approval_hash'], state_dir=state)
            self.assertEqual(result['state'], 'dataset-updated')
            self.assertFalse(self.client.uploads)

    def test_explicit_publish_reuses_existing_tileset(self):
        with tempfile.TemporaryDirectory() as tmp, patch('maintenance.mapbox.target_by_id', return_value=self.target), patch('maintenance.mapbox.time.sleep'):
            result = apply_plan(self.client, self.plan, self.plan['approval_hash'], publish=True, state_dir=Path(tmp))
            self.assertEqual(result['state'], 'published')
            self.assertEqual(self.client.uploads, ['owner.existing'])

    def test_partial_failure_keeps_journal_and_skips_upload(self):
        with tempfile.TemporaryDirectory() as tmp, patch('maintenance.mapbox.target_by_id', return_value=self.target), patch.object(self.client, 'write_feature', side_effect=RuntimeError('network')):
            with self.assertRaises(RuntimeError): apply_plan(self.client, self.plan, self.plan['approval_hash'], publish=True, state_dir=Path(tmp))
            journal = read_json(Path(tmp) / 'publishes' / f"{self.plan['approval_hash']}.json")
            self.assertEqual(journal['state'], 'needs-attention')
            self.assertFalse(self.client.uploads)

    def test_retired_style_target_cannot_be_published(self):
        with patch.object(self.client, 'style', return_value={'sources': {}, 'layers': []}):
            with self.assertRaisesRegex(ValueError, 'no longer uses'): make_plan(self.client, self.target, self.after, 'evidence')

    def test_reads_use_unique_cache_keys(self):
        client = Mapbox.__new__(Mapbox)
        client.token = 'test'
        with patch('maintenance.mapbox.request', return_value=(b'{}', {}, 200)) as request:
            client.call('datasets/v1/test/data/features')
            client.call('datasets/v1/test/data/features')
            client.call('styles/v1/test/style')
        urls = [call.args[0] for call in request.call_args_list]
        self.assertNotEqual(urls[0], urls[1])
        self.assertTrue(all('fresh=' in url for url in urls[:2]))
        self.assertNotIn('fresh=', urls[2])

    def test_storage_truncation_is_allowed_only_for_written_geometry(self):
        self.client.data['features'].append(feature('untouched'))
        self.after['features'].append(feature('untouched'))
        self.after['features'][0]['geometry']['coordinates'][0] = [-78.12345699, 38.12345699]
        plan = make_plan(self.client, self.target, self.after, 'precision test')
        stored = copy.deepcopy(self.after)
        stored['features'][0]['geometry']['coordinates'] = stored_coordinates(stored['features'][0]['geometry']['coordinates'])
        self.assertEqual(stored['features'][0]['geometry']['coordinates'][0], [-78.123456, 38.123456])
        self.assertEqual(verify_written(plan, stored)['mode'], 'mapbox-six-decimal-truncation')
        for kind in ('property', 'vertex', 'untouched', 'missing'):
            bad = copy.deepcopy(stored)
            if kind == 'property': bad['features'][0]['properties']['color'] = 'blue'
            elif kind == 'vertex': bad['features'][0]['geometry']['coordinates'][0][0] += .000001
            elif kind == 'untouched': bad['features'][1]['geometry']['coordinates'][0][0] += .0000001
            else: bad['features'].pop()
            with self.assertRaisesRegex(ValueError, 'Post-write verification failed'): verify_written(plan, bad)

    def test_resume_verifies_writes_without_repeating_them(self):
        with tempfile.TemporaryDirectory() as tmp, patch('maintenance.mapbox.target_by_id', return_value=self.target), patch('maintenance.mapbox.time.sleep'):
            state = Path(tmp)
            apply_plan(self.client, self.plan, self.plan['approval_hash'], state_dir=state)
            writes = self.client.writes[:]
            result = resume_publish(self.client, self.plan, self.plan['approval_hash'], state)
            self.assertEqual(result['state'], 'published')
            self.assertEqual(self.client.writes, writes)
            resume_publish(self.client, self.plan, self.plan['approval_hash'], state)
            self.assertEqual(len(self.client.uploads), 1)

    def test_resume_rejects_partial_writes_and_intervening_edits(self):
        with tempfile.TemporaryDirectory() as tmp, patch('maintenance.mapbox.target_by_id', return_value=self.target), patch('maintenance.mapbox.time.sleep'):
            state = Path(tmp)
            result = apply_plan(self.client, self.plan, self.plan['approval_hash'], state_dir=state)
            path = state / 'publishes' / f"{self.plan['approval_hash']}.json"
            partial = {**result, 'completed': []}
            write_json(path, partial)
            with self.assertRaisesRegex(ValueError, 'incomplete'): resume_publish(self.client, self.plan, self.plan['approval_hash'], state)
            write_json(path, result)
            self.client.data['features'][0]['properties']['name'] = 'Studio edit'
            with self.assertRaisesRegex(ValueError, 'Post-write verification failed'): resume_publish(self.client, self.plan, self.plan['approval_hash'], state)
            self.assertFalse(self.client.uploads)

    def test_uncertain_upload_submission_cannot_be_repeated(self):
        with tempfile.TemporaryDirectory() as tmp, patch('maintenance.mapbox.target_by_id', return_value=self.target), patch('maintenance.mapbox.time.sleep'):
            state = Path(tmp)
            with patch.object(self.client, 'upload', side_effect=RuntimeError('connection lost')):
                with self.assertRaises(RuntimeError): apply_plan(self.client, self.plan, self.plan['approval_hash'], publish=True, state_dir=state)
            with self.assertRaisesRegex(ValueError, 'outcome is unknown'): resume_publish(self.client, self.plan, self.plan['approval_hash'], state)
            self.assertFalse(self.client.uploads)

    def test_resume_polls_existing_upload(self):
        with tempfile.TemporaryDirectory() as tmp, patch('maintenance.mapbox.target_by_id', return_value=self.target), patch('maintenance.mapbox.time.sleep'):
            state = Path(tmp)
            result = apply_plan(self.client, self.plan, self.plan['approval_hash'], state_dir=state)
            result.update(upload_id='existing', state='tileset-processing')
            write_json(state / 'publishes' / f"{self.plan['approval_hash']}.json", result)
            self.client.upload_status = lambda uid: {'id': uid, 'complete': True, 'error': None}
            self.assertEqual(resume_publish(self.client, self.plan, self.plan['approval_hash'], state)['state'], 'published')
            self.assertFalse(self.client.uploads)

    def test_layer_repair_preserves_style_and_records_prior_upload(self):
        with tempfile.TemporaryDirectory() as tmp, patch('maintenance.mapbox.target_by_id', return_value=self.target), patch('maintenance.mapbox.time.sleep'):
            state = Path(tmp)
            result = apply_plan(self.client, self.plan, self.plan['approval_hash'], state_dir=state)
            result.update(upload_id='incompatible', state='tileset-processing')
            write_json(state / 'publishes' / f"{self.plan['approval_hash']}.json", result)
            self.client.upload_status = lambda uid: {'id': uid, 'complete': True, 'error': None}
            with patch.object(self.client, 'tileset', side_effect=[{'vector_layers': [{'id': 'original'}]}, {'vector_layers': [{'id': 'Trails'}]}]):
                repaired = resume_publish(self.client, self.plan, self.plan['approval_hash'], state, repair_layer=True)
            self.assertEqual(repaired['state'], 'published')
            self.assertEqual(repaired['previous_uploads'][0]['upload_id'], 'incompatible')
            self.assertEqual(self.client.writes, ['a'])
            self.assertEqual(self.client.uploads, ['owner.existing'])

    def test_missing_publish_tools_stop_before_dataset_writes(self):
        with patch('maintenance.mapbox.target_by_id', return_value=self.target), patch.object(self.client, 'check_publish_tools', side_effect=ValueError('missing tools')):
            with self.assertRaisesRegex(ValueError, 'missing tools'): apply_plan(self.client, self.plan, self.plan['approval_hash'], publish=True)
            self.assertFalse(self.client.writes)

    def test_completed_upload_with_wrong_layer_is_not_success(self):
        with tempfile.TemporaryDirectory() as tmp, patch('maintenance.mapbox.target_by_id', return_value=self.target), patch('maintenance.mapbox.time.sleep'):
            state = Path(tmp)
            with patch.object(self.client, 'tileset', side_effect=[{'vector_layers': [{'id': 'Trails'}]}, {'vector_layers': [{'id': 'original'}]}]):
                with self.assertRaisesRegex(ValueError, 'source layer is absent'):
                    apply_plan(self.client, self.plan, self.plan['approval_hash'], publish=True, state_dir=state)
            journal = read_json(state / 'publishes' / f"{self.plan['approval_hash']}.json")
            self.assertEqual(journal['state'], 'tileset-processing')
            self.assertEqual(journal['upload_id'], 'upload')

    def test_layer_repair_waits_for_processing_but_can_replace_failed_upload(self):
        with tempfile.TemporaryDirectory() as tmp, patch('maintenance.mapbox.target_by_id', return_value=self.target), patch('maintenance.mapbox.time.sleep'):
            state = Path(tmp)
            result = apply_plan(self.client, self.plan, self.plan['approval_hash'], state_dir=state)
            result.update(upload_id='failed-repair', state='tileset-processing')
            write_json(state / 'publishes' / f"{self.plan['approval_hash']}.json", result)
            self.client.upload_status = lambda uid: {'id': uid, 'complete': False, 'error': None}
            with patch.object(self.client, 'tileset', return_value={'vector_layers': [{'id': 'original'}]}):
                with self.assertRaisesRegex(ValueError, 'finished or failed'):
                    resume_publish(self.client, self.plan, self.plan['approval_hash'], state, repair_layer=True)
            self.assertFalse(self.client.uploads)
            self.client.upload_status = lambda uid: {'id': uid, 'complete': False, 'error': 'Maxzoom exceeded'}
            with patch.object(self.client, 'tileset', side_effect=[{'vector_layers': [{'id': 'original'}]}, {'vector_layers': [{'id': 'Trails'}]}]):
                repaired = resume_publish(self.client, self.plan, self.plan['approval_hash'], state, repair_layer=True)
            self.assertEqual(repaired['state'], 'published')
            self.assertEqual(repaired['previous_uploads'][0]['error'], 'Maxzoom exceeded')


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.data = collection(feature('a', source_feature_id='718'), feature('b', source_feature_id='3056'))
        self.data['features'][0]['geometry']['coordinates'][-1][0] += 0.000003
        self.rules = [{'source_feature_id': '718', 'endpoint': 'end', 'target_source_feature_id': '3056', 'target_endpoint': 'end', 'max_distance_m': 1.0}]

    def test_endpoint_join_is_exact_repeatable_and_preserves_input(self):
        original = copy.deepcopy(self.data)
        joined = connect_endpoints(self.data, self.rules)
        self.assertEqual(joined['features'][0]['geometry']['coordinates'][-1], joined['features'][1]['geometry']['coordinates'][-1])
        self.assertEqual(self.data, original)
        self.assertEqual(fingerprint(joined), fingerprint(connect_endpoints(joined, self.rules)))

    def test_missing_target_and_large_move_stop_ingestion(self):
        with self.assertRaisesRegex(ValueError, 'disappeared'): connect_endpoints(collection(self.data['features'][0]), self.rules)
        self.data['features'][0]['geometry']['coordinates'][-1][0] += .001
        with self.assertRaisesRegex(ValueError, 'beyond'): connect_endpoints(self.data, self.rules)

    def test_reconciliation_roundoff_preservation_cannot_reopen_a_join(self):
        baseline = collection(feature('old-a', OBJECTID=718), feature('old-b', OBJECTID=3056))
        candidate = collection(feature('city:718', source_feature_id='718'), feature('city:3056', source_feature_id='3056'))
        for f in candidate['features']: f['geometry']['coordinates'][-1][0] += .0000005
        candidate['features'][1]['geometry']['coordinates'][0][0] += .001
        joined = connect_endpoints(candidate, self.rules)
        result = reconcile(baseline, joined, 'OBJECTID', [])
        self.assertEqual(result['features'][0]['geometry']['coordinates'][-1], result['features'][1]['geometry']['coordinates'][-1])
        self.assertNotIn('old-a', result['ingest_report']['preserved_submeter_geometry'])


class ReviewMapTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeMapbox()
        self.target = {'id': 'test', 'dataset': 'data', 'tileset': 'owner.existing', 'source_layer': 'Trails'}
        self.plan = make_plan(self.client, self.target, collection(feature('a', name='Changed', color='red'), feature('new', name='New')), 'test evidence')

    def test_only_accepted_features_enter_candidate(self):
        decisions = {'plan_hash': self.plan['approval_hash'], 'decisions': {'new': {'decision': 'accept'}, 'a': {'decision': 'discuss', 'note': 'Check name'}}}
        result = reviewed_candidate(self.plan, decisions)
        self.assertEqual([f['id'] for f in result['features']], ['a', 'new'])
        self.assertEqual(result['features'][0]['properties']['name'], 'Before')
        decisions['decisions'] = {}
        self.assertEqual(fingerprint(reviewed_candidate(self.plan, decisions)), self.plan['before_hash'])

    def test_wrong_plan_and_unknown_ids_are_rejected(self):
        for decisions in [{'plan_hash': 'stale', 'decisions': {}}, {'plan_hash': self.plan['approval_hash'], 'decisions': {'unknown': {'decision': 'accept'}}}]:
            with self.assertRaises(ValueError): reviewed_candidate(self.plan, decisions)
        self.plan['after']['features'][0]['properties']['color'] = 'blue'
        with self.assertRaises(ValueError): review_rows(self.plan)

    def test_existing_attributes_are_not_classified_as_new_metadata(self):
        rows = {r['id']: r for r in review_rows(self.plan)}
        self.assertIn('attributes', rows['a']['kinds'])
        self.assertNotIn('metadata', rows['a']['kinds'])
        self.assertIn('added', rows['new']['kinds'])

    def test_reviewed_candidate_cannot_overwrite_intervening_studio_edits(self):
        candidate = reviewed_candidate(self.plan, {'plan_hash': self.plan['approval_hash'], 'decisions': {'new': {'decision': 'accept'}}})
        self.client.data['features'][0]['properties']['name'] = 'New Studio edit'
        with self.assertRaisesRegex(ValueError, 'changed during visual review'):
            make_plan(self.client, self.target, candidate, 'exported decisions')


class ContentTests(unittest.TestCase):
    def test_notice_approval_requires_dates_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, output = Path(tmp) / 'review.json', Path(tmp) / 'updates.json'
            write_json(output, {'schema_version': 1, 'updates': []})
            write_json(path, {'source': {'id': 'city-guide', 'url': 'https://charlottesville.gov/659/Trails', 'label': 'City'}, 'after': {'sha256': 'test-snapshot'}, 'system_ids': ['city'], 'assessment': {'result': {'notices': [{'title': 'Test notice', 'body': 'Reviewed text', 'kind': 'maintenance', 'evidence': 'Source passage', 'starts_at': None, 'expires_at': None}]}}})
            with self.assertRaisesRegex(ValueError, 'Explicit start and expiry'): approve_notice(path, 0, 'Reviewer', None, None, output)
            for _ in range(2): approve_notice(path, 0, 'Reviewer', '2026-11-01T00:00:00Z', '2026-11-02T00:00:00Z', output)
            self.assertEqual(len(read_json(output)['updates']), 1)

    def test_unknown_system_and_expiry_are_rejected(self):
        notice = dict(id='n', title='Closed', body='Bridge work', source_url='https://example.org', source_label='Manager', reviewer='Human', evidence='Notice', status='approved', kind='closure', system_ids=['unknown'], starts_at='2026-11-01T00:00:00Z', expires_at='2026-11-02T00:00:00Z', reviewed_at='2026-11-01T00:00:00Z')
        with self.assertRaises(ValueError): validate_updates({'updates': [notice]}, [{'id': 'city'}])
        notice['system_ids'] = ['city']; notice['expires_at'] = notice['starts_at']
        with self.assertRaises(ValueError): validate_updates({'updates': [notice]}, [{'id': 'city'}])

    def test_chat_review_schema_is_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            record, result = Path(tmp) / 'record.json', Path(tmp) / 'result.json'
            write_json(record, {'status': 'pending'})
            write_json(result, {'summary': 'Baseline', 'map_change': False, 'uncertainties': [], 'notices': []})
            self.assertEqual(record_review(record, result, 'Codex')['assessment']['method'], 'chat')
            write_json(result, {'summary': 'Incomplete'})
            with self.assertRaises(ValueError): record_review(record, result, 'Codex')


if __name__ == '__main__': unittest.main()
