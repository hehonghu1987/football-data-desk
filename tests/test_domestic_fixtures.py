import unittest
from datetime import datetime, timedelta, timezone
import build_data as app

class DomesticFixtureTests(unittest.TestCase):
    def setUp(self):
        self.future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        self.past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        self.sp = {'id':'one', 'num':'周五001', 'date':self.future, 'league':'美职',
                   'home':'奥兰多', 'homeFull':'奥兰多', 'away':'辛辛那提', 'awayFull':'辛辛那提',
                   'had':[None,None,None], 'hhad':{'line':-1,'h':2.5,'d':3,'a':2}, 'ttg':{}}
        self.bj = {'num':'28','date':self.future,'league':'美职','home':'奥兰多城','away':'辛辛那提',
                   'line':-1,'h':2.5,'d':3,'a':2}

    def test_missing_league_is_added_once_and_merged_across_sources(self):
        fixtures, teams, team_rows = [], {}, []
        self.assertEqual(app.attach_sporttery(fixtures, teams, [self.sp], team_rows), 1)
        self.assertEqual(app.attach_beidan(fixtures, teams, [self.bj], team_rows), 1)
        self.assertEqual(len(fixtures), 1)
        self.assertEqual(len(team_rows), 2)
        self.assertIsNone(fixtures[0]['sp']['had'])
        self.assertNotIn('books', fixtures[0])
        self.assertEqual(fixtures[0]['bj']['num'], '28')
        self.assertIsNone(fixtures[0]['pred'])

    def test_future_match_can_use_official_had_and_unhide(self):
        fixtures = [{'id':'123','date':self.future,'home':'1','away':'2','hide':1}]
        teams = {'1':{'cn':'拜仁慕尼黑'},'2':{'cn':'科隆'}}
        source = dict(self.sp, home='拜仁', away='科隆', homeFull='拜仁', awayFull='科隆', had=[1.5,4.,7.])
        self.assertEqual(app.attach_sporttery(fixtures, teams, [source]), 1)
        self.assertEqual(fixtures[0]['books'][0]['m'],[1.5,4.,7.])
        self.assertNotIn('hide',fixtures[0])

    def test_past_and_ambiguous_matches_are_not_marked(self):
        teams = {'1':{'cn':'奥兰多城'},'2':{'cn':'辛辛那提'}}
        fixtures = [{'date':self.future,'home':'1','away':'2'}, {'date':self.future,'home':'1','away':'2'}]
        self.assertEqual(app.attach_sporttery(fixtures, teams, [self.sp], []),0)
        self.assertTrue(all('sp' not in f for f in fixtures))
        self.assertEqual(app.attach_beidan([], {}, [dict(self.bj,date=self.past)], []), 0)

    def test_youth_and_women_are_not_matched_to_adults(self):
        for name in ('中国U21','中国女足','中国B队'):
            self.assertFalse(app._name_match(name, '中国', '中国'))
        self.assertTrue(app._name_match('布拉干蒂诺','布拉干RB',''))
        self.assertTrue(app._name_match('布拉甘蒂诺红牛','布拉干RB',''))

if __name__ == '__main__': unittest.main()
