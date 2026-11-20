import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
import build_data as app

class DomesticFixtureTests(unittest.TestCase):
    def setUp(self):
        self.future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        self.past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        self.sp = {'id':'one', 'num':'周五001', 'date':self.future, 'league':'美职',
                   'home':'奥兰多', 'homeFull':'奥兰多', 'away':'辛辛那提', 'awayFull':'辛辛那提',
                   'had':[None,None,None], 'hhad':{'line':-1,'h':2.5,'d':3,'a':2}, 'ttg':{}}
    def test_listed_match_outside_featured_leagues_is_retained_once(self):
        fixtures, teams, team_rows = [], {}, []
        self.assertEqual(app.attach_sporttery(fixtures, teams, [self.sp]), 0)
        self.assertEqual(app.add_sporttery_fixtures(fixtures, teams, team_rows, [self.sp, self.sp]), 1)
        self.assertEqual(len(fixtures), 1)
        self.assertEqual(len(team_rows), 2)
        self.assertTrue(app.on_schedule(fixtures[0]))
        self.assertIsNone(fixtures[0]['sp']['had'])
        self.assertNotIn('books', fixtures[0])

    def test_competition_scope_and_source_overlap(self):
        for league in ("英超", "西甲", "意甲", "德甲", "法甲", "英冠", "荷甲", "葡超", "比甲",
                       "巴西甲", "欧冠", "欧联杯", "世界杯", "亚洲杯", "国际友谊赛", "世预赛欧洲区"):
            self.assertTrue(app.on_schedule({"league": league}))
        for league in ("法国杯", "苏超", "欧冠资格赛", "美职"):
            self.assertFalse(app.on_schedule({"league": league, "bj": {"num": "1"}}))
            self.assertTrue(app.on_schedule({"league": league, "sp": {"num": "周五001"}}))

    def test_previous_jc_only_qualifies_when_underway_or_completed(self):
        f = {"id":"1", "league":"美职", "sp":{"num":"周五001"}}
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'ROOT', tmp):
            app.record_jc_numbers([f], [])
            finished = {"id":"1", "league":"美职"}
            underway = dict(finished, state="in")
            unlisted = dict(finished, state="pre")
            app.record_jc_numbers([unlisted, underway], [finished])
            self.assertTrue(app.on_schedule(finished))
            self.assertTrue(app.on_schedule(underway))
            self.assertFalse(app.on_schedule(unlisted))
            self.assertNotIn("sp", finished)

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
        self.assertEqual(app.attach_sporttery(fixtures, teams, [self.sp]),0)
        self.assertTrue(all('sp' not in f for f in fixtures))
        self.assertEqual(app._domestic_future([dict(self.sp,date=self.past)]), [])

    def test_youth_and_women_are_not_matched_to_adults(self):
        for name in ('中国U21','中国女足','中国B队'):
            self.assertFalse(app._name_match(name, '中国', '中国'))
        self.assertTrue(app._name_match('布拉干蒂诺','布拉干RB',''))
        self.assertTrue(app._name_match('布拉甘蒂诺红牛','布拉干RB',''))

if __name__ == '__main__': unittest.main()
