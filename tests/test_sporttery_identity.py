import tempfile
import unittest
from unittest.mock import patch

import build_data as app


class FixtureIdentityTests(unittest.TestCase):
    def test_sporting_and_united_share_one_official_entry(self):
        date = '2026-11-25T20:00:00+00:00'
        teams = {'1': {'id':'1', 'cn':'克里夫巴斯'}, '2': {'id':'2', 'cn':'曼联'},
                 '3': {'id':'3', 'cn':'葡萄牙体育'}}
        fixture = {'id':'401915373','home':'3','away':'2','league':'欧冠','date':date}
        rows = [fixture]
        source = {'id':'2043008','date':date,'league':'欧冠','num':'周三005',
                  'home':'里斯本','homeFull':'里斯本竞技','away':'曼联','awayFull':'曼彻斯特联',
                  'had':[2,3,4]}
        self.assertFalse(app._name_match('克里夫巴斯','里斯本','里斯本竞技'))
        self.assertEqual(app.attach_sporttery(rows,teams,[source]),1)
        self.assertEqual(app.add_sporttery_fixtures(rows,teams,list(teams.values()),[source]),0)
        self.assertEqual(fixture['sp']['homeName'],'里斯本竞技')
        with tempfile.TemporaryDirectory() as temp, patch.object(app,'ROOT',temp):
            app.sporttery_aliases(rows)
            self.assertEqual(app.sporttery_aliases([]), {'2043008':'401915373'})

    def test_unrelated_team_is_never_selected_by_city(self):
        self.assertFalse(app._name_match('大阪樱花','大阪钢巴','大阪钢巴'))
        self.assertFalse(app._name_match('中国（U21）','中国','中国'))
        self.assertTrue(app._name_match('博多格林特','博德闪耀'))
