import importlib.util
import unittest
from maintenance.trail_release import replace_route,retain_distinct
from maintenance.trail_release_style import transform


class ReleaseStyleTests(unittest.TestCase):
    def test_preserves_other_layers_and_existing_color_expression(self):
        import copy
        old_color=['case',['==',['get','pipeline_id'],'virginia-state-parks'],'red','brown']
        at='meekohi.ck578grpj01232ipbxr2ampjj-7v6dv'
        style={'sources':{'composite':{'type':'vector','url':'mapbox://other,another,'+at}},'layers':[
            {'id':'strava-trail','source-layer':'Strava_Sidetrails','paint':{'line-color':old_color}},
            {'id':'shenandoah-np fringe','source-layer':'shen-08a9vs','filter':['==',['get','visible'],True]},
            {'id':'shenandoah-np-trail','source-layer':'shen-08a9vs'},
            {'id':'rivanna-trail','paint':{'line-color':'green'}},
            {'id':'appalachian-trail','paint':{'line-color':'white'}}]}
        original=copy.deepcopy(style);result=transform(style)
        self.assertEqual(style,original)
        self.assertEqual(result['layers'][3:],style['layers'][3:])
        self.assertEqual(result['sources']['composite']['url'],'mapbox://'+at+',other,another')
        self.assertEqual(result['layers'][0]['paint']['line-color'][-1],old_color)
        self.assertEqual(result['layers'][1]['filter'][1],style['layers'][1]['filter'])
        self.assertIn('12/21/2019',str(result['layers'][2]['filter']))
        with self.assertRaisesRegex(ValueError,'already applied'):transform(result)


@unittest.skipUnless(importlib.util.find_spec('shapely'), 'optional geometry dependencies')
class ReleaseGeometryTests(unittest.TestCase):
    def test_source_replacement_preserves_other_route_and_connects_tails(self):
        from shapely.geometry import LineString,MultiLineString,Point
        old=MultiLineString([[(0,0),(100,0)],[(100.1,0),(200,0)],[(0,100),(200,100)]])
        new=LineString([(50,2),(150,2)])
        remaining,audit=replace_route(old,[('new',new)])
        self.assertEqual(len(audit),1)
        self.assertLess(remaining.distance(Point(50,2)),.00001)
        self.assertLess(remaining.distance(Point(150,2)),.00001)
        self.assertEqual(remaining.intersection(LineString([(0,100),(200,100)])).length,200)
        self.assertGreater(remaining.distance(Point(100,0)),40)

    def test_crossings_stay_and_shared_tread_rejoins_reference(self):
        from shapely.geometry import LineString,Point
        reference=LineString([(0,0),(100,0)])
        crossing=LineString([(50,-100),(50,100)])
        result,audit=retain_distinct(crossing,[reference],3)
        self.assertTrue(result.equals(crossing));self.assertEqual(audit['removed_m'],0)
        shared=LineString([(0,1),(80,1),(80,100)])
        result,audit=retain_distinct(shared,[reference],3)
        self.assertGreater(audit['removed_m'],70)
        self.assertLess(result.distance(reference),.00001)
        self.assertLess(result.distance(Point(80,100)),.00001)
        result,_=retain_distinct(reference,[reference],3)
        self.assertTrue(result.is_empty)

    def test_distant_route_endpoint_fails_closed(self):
        from shapely.geometry import LineString
        with self.assertRaisesRegex(ValueError,'too far'):
            replace_route(LineString([(0,0),(100,0)]),[('bad',LineString([(0,100),(100,100)]))])


if __name__=='__main__':unittest.main()
