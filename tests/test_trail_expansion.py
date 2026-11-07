import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs,urlparse
from maintenance.common import configs,digest,read_json,write_json
from maintenance.ingest import fetch_arcgis,run_adapter
from maintenance.monitor import extract
from maintenance.tnc import catalog,PDFLinks
from maintenance.trail_expansion import feedback,screen,fc


def feature(fid='one', coords=None, **props):
    return {'type':'Feature','id':fid,'properties':{'name':fid,'pipeline_id':'usfs-gwj','source_id':'trails','admin_org':'080806','source_url':'https://example.org',**props},
            'geometry':{'type':'LineString','coordinates':coords or [[-79.8,37.9],[-79.8,37.91]]}}


def source(**props):
    f=feature();f['properties']={'globalid':'{aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee}','admin_org':'080806','trail_name':'SAMPLE','trail_type':'TERRA','attributesubset':'TrailNFS_MGMT','hiker_pedestrian_managed':'01/01-12/31',**props};return f


class CatalogTests(unittest.TestCase):
    def data(self, items):
        return ('<script>'+json.dumps({'openHighlightPin':'x','mapItems':items})+'</script>').encode()

    def row(self, **kwargs):
        return {'markerSubtitle':'Virginia','title':'Sample','link':'https://www.nature.org/place/sample/','preserveStatus':'Open to the Public','markerLatitude':'38','markerLongitude':'-79','preserveTags':[{'tag':'Virginia'}],**kwargs}

    def test_location_scope_closed_preserves_and_semantic_changes(self):
        rows=[self.row(),self.row(link='https://www.nature.org/place/closed/',preserveStatus='Closed to the Public'),self.row(markerSubtitle='Tennessee')]
        data=self.data(rows)
        self.assertEqual(len(catalog(data)),2)
        rows[0]['image']='rotating-fundraising.jpg'
        self.assertEqual(extract(data,'tnc-catalog'),extract(self.data(rows),'tnc-catalog'))
        rows[0]['preserveStatus']='Limited Access'
        self.assertNotEqual(extract(data,'tnc-catalog'),extract(self.data(rows),'tnc-catalog'))

    def test_structure_and_unknown_access_fail_closed(self):
        for data in [b'<html>no catalog</html>',self.data([self.row(preserveStatus='Maybe')]),self.data([self.row(),self.row()])]:
            with self.assertRaises(ValueError):catalog(data)

    def test_discovery_keeps_only_official_pdf_links(self):
        p=PDFLinks('https://www.nature.org/place/');p.feed('<a href="/maps/a.pdf">A</a><a href="https://evil.test/a.pdf">B</a><a href="/other">C</a>')
        self.assertEqual(p.links,{'https://www.nature.org/maps/a.pdf'})


class ArcGISTests(unittest.TestCase):
    def fetch(self, returned, final=None, bbox=None):
        calls=[];answers=[{'objectIds':[1,2]}, {'type':'FeatureCollection','features':[feature(i) for i in returned]}, {'objectIds':final or [2,1]}]
        def request(url):
            calls.append(parse_qs(urlparse(url).query));return json.dumps(answers.pop(0)).encode(),{},200
        data=fetch_arcgis('https://example.org/0',request_fn=request,where="admin_org LIKE '0808%'",bbox=bbox)
        return json.loads(data),calls

    def test_filter_applies_to_both_membership_checks(self):
        data,calls=self.fetch([2,1]);self.assertEqual(len(data['features']),2)
        self.assertEqual(calls[0]['where'],["admin_org LIKE '0808%'"])
        self.assertEqual(calls[-1]['where'],calls[0]['where'])

    def test_bbox_applies_to_both_membership_queries(self):
        _,calls=self.fetch([1,2],bbox=[-80,37,-78,39])
        for call in (calls[0],calls[-1]):
            self.assertEqual(call['geometry'],['-80,37,-78,39'])
            self.assertEqual(call['inSR'],['4326'])
        self.assertNotIn('geometry',calls[1])
        for bbox in ([0,0,0,1],[0,0,float('nan'),1],[True,0,1,1],[-181,0,1,1]):
            with self.assertRaises(ValueError):self.fetch([1,2],bbox=bbox)

    def test_wrong_ids_same_count_and_membership_edits_are_rejected(self):
        for returned,final in [([1,3],None),([1,1],None),([1,2],[1,3])]:
            with self.assertRaises(ValueError):self.fetch(returned,final)


class ForestTests(unittest.TestCase):
    def run_source(self, features):return run_adapter({'type':'FeatureCollection','features':features},configs('usfs-gwj')[0],'trails')

    def test_explicit_contrary_evidence_remains_held(self):
        for props in [{'hiker_pedestrian_restricted':'01/01-12/31'}, {'hiker_pedestrian_disc':'01/01-12/31'}, {'trail_name':'OLD BRIDGE (DECO'}]:
            self.assertEqual(len(self.run_source([source(**props)])['ingest_report']['held']),1)
        result=self.run_source([source()]);self.assertTrue(result['ingest_report']['review_only']);self.assertFalse(result['ingest_report']['held']);self.assertIsNone(result['features'][0]['properties']['color'])

    def test_unknown_and_seasonal_records_follow_user_open_policy(self):
        for props in [{'attributesubset':None,'hiker_pedestrian_managed':None}, {'hiker_pedestrian_managed':'04/01-10/31'}, {'hiker_pedestrian_restricted':'N/A','hiker_pedestrian_disc':'None'}]:
            self.assertFalse(self.run_source([source(**props)])['ingest_report']['held'])

    def test_selected_route_sources_and_explicit_rejections(self):
        for name in ['APPALACHIAN TRAIL','APPALACHIAN NATIONAL SCENIC TRAIL','HIGH KNOB LOOP','CASCADES OVERLOOK']:
            result=self.run_source([source(trail_name=name)])
            self.assertFalse(result['features']);self.assertEqual(len(result['ingest_report']['excluded']),1)
        self.assertEqual(len(self.run_source([source(trail_name='APPALACHIAN TRAIL SIDE TRAIL')])['features']),1)

    def test_short_exclusion_is_bound_to_reviewed_geometry(self):
        from maintenance.usfs import transform
        config=copy.deepcopy(configs('usfs-gwj')[0]);f=source();sid=f['properties']['globalid'].strip('{}')
        config['feature_exclusions']={sid:{'geometry_hash':digest(f['geometry']),'reason':'isolated'}}
        self.assertFalse(transform(fc([f]),config,'trails')['features'])
        f['geometry']['coordinates'][1][1]+=.001
        result=transform(fc([f]),config,'trails')
        self.assertEqual(len(result['features']),1);self.assertEqual(len(result['ingest_report']['connectivity_recheck']),1)

    def test_null_geometry_reported_and_ids_are_not_row_numbers(self):
        f=source();f['geometry']=None;r=self.run_source([f]);self.assertEqual(len(r['ingest_report']['rejected']),1);self.assertFalse(r['features'])
        a=self.run_source([source()]);f=source();f['id']=999;f['properties']['objectid']=999;b=self.run_source([f]);self.assertEqual(a['features'][0]['id'],b['features'][0]['id'])
        for f in [source(admin_org='090101'),source(globalid='invalid')]:
            with self.assertRaises(ValueError):self.run_source([f])
        with self.assertRaises(ValueError):self.run_source([source(),source()])


class FeedbackTests(unittest.TestCase):
    def test_publication_plan_rejects_unreviewed_candidates(self):
        from maintenance.mapbox import make_plan
        candidate=fc([feature()]);candidate['ingest_report']={'review_only':True}
        with self.assertRaisesRegex(ValueError,'review'):
            make_plan(None,{},candidate,'test')


    def test_stale_tampered_or_held_inclusion_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);incoming=fc([feature()]);report={'incoming_hash':digest(incoming),'rows':[{'id':'one','status':'access-hold'}]};report['review_hash']=digest(report)
            write_json(root/'incoming.geojson',incoming);write_json(root/'review.json',report)
            value={'review_hash':report['review_hash'],'decisions':{'one':'include'}};write_json(root/'feedback.json',value)
            with self.assertRaisesRegex(ValueError,'Held/duplicate'):feedback(root,root/'feedback.json',root/'result.json')
            value['decisions']['one']='hold';write_json(root/'feedback.json',value)
            self.assertEqual(feedback(root,root/'feedback.json',root/'result.json')['features'],[])
            report['rows'][0]['status']='proposed';write_json(root/'review.json',report)
            with self.assertRaisesRegex(ValueError,'report changed'):feedback(root,root/'feedback.json',root/'result.json')


try:
    import shapely
    import pyproj
    GEO=True
except ImportError:GEO=False


@unittest.skipUnless(GEO,'optional geo dependencies')
class OverlapTests(unittest.TestCase):
    def test_duplicate_partial_overlap_crossing_and_protected_existing_are_unchanged(self):
        existing=fc([feature('rivanna/old',reference_source='Rivanna Trail')]);before=copy.deepcopy(existing)
        incoming=fc([feature('same'),feature('partial',[[-79.8,37.9],[-79.8,37.92]]),feature('cross',[[-79.81,37.905],[-79.79,37.905]])])
        rows={r['id']:r for r in screen(incoming,existing,{}, {'holds':[]})}
        self.assertEqual(rows['same']['status'],'duplicate');self.assertEqual(rows['partial']['status'],'overlap-hold');self.assertEqual(rows['cross']['status'],'proposed');self.assertEqual(existing,before)

    def test_conflicting_incoming_and_access_priority(self):
        incoming=fc([feature('one'),feature('two')]);rows=screen(incoming,fc([]),{'one':'Restricted'}, {'holds':[]})
        self.assertEqual(rows[0]['status'],'access-hold');self.assertEqual(rows[1]['status'],'incoming-overlap')

    def test_selected_paths_in_one_tnc_map_keep_parallel_topology(self):
        incoming=fc([feature('one',pipeline_id='tnc-virginia'),feature('two',pipeline_id='tnc-virginia')])
        self.assertTrue(all(r['status']=='proposed' for r in screen(incoming,fc([]),{}, {'holds':[]})))


class GeoPDFTests(unittest.TestCase):
    def test_reviewed_maps_have_exact_paths_and_official_colors(self):
        directory=os.environ.get('TEST_TNC_PDF_DIRECTORY')
        if not directory:self.skipTest('set TEST_TNC_PDF_DIRECTORY for exact official-map regression')
        from maintenance.tnc import extract_maps
        with tempfile.TemporaryDirectory() as tmp:
            result=extract_maps(Path(directory),Path(tmp))
            self.assertEqual(len(result['features']),16)
            bear=next(f for f in result['features'] if f['properties']['source_id']=='bear-loop')
            self.assertEqual(bear['properties']['map_color'],'#ee3524')
            self.assertEqual(len(bear['geometry']['coordinates']),129)
            reports=read_json(Path(tmp)/'extraction-report.json')
            self.assertAlmostEqual(reports['bear-loop']['lengths_m']['loop-and-approach'],4635.24,delta=.1)
            self.assertEqual(reports['cumberland-marsh']['crs'],'EPSG:26918')
            self.assertTrue(all(max(r['control_residual_m'])<1 for r in reports.values()))


    def test_changed_pdf_rejected_before_geometry_extraction(self):
        try:
            import numpy,pymupdf,pypdf,pyproj
        except ImportError:self.skipTest('optional PDF dependencies')
        from maintenance.geopdf import extract as extract_pdf
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'map.pdf';p.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'PDF changed'):extract_pdf(p,{'pdf_sha256':'no'})


if __name__=='__main__':unittest.main()
