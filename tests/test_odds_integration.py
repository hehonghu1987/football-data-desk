import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import build_data as app


class OddsIntegrationTests(unittest.TestCase):
    def test_api_cache_is_isolated_by_key_and_errors_are_not_cached(self):
        from contextlib import contextmanager
        import io
        calls = []

        @contextmanager
        def fake_open(request, timeout=0):
            calls.append(request.get_header('X-apisports-key'))
            yield io.BytesIO(json.dumps({'response': [len(calls)], 'errors': []}).encode())

        with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'CACHE_DIR', tmp), patch.object(app.urllib.request, 'urlopen', side_effect=fake_open):
            first = app._af_get('/fixtures', 'key-one')
            self.assertEqual(app._af_get('/fixtures', 'key-one'), first)
            second = app._af_get('/fixtures', 'key-two')
            self.assertNotEqual(first, second)
            self.assertEqual(len(calls), 2)
            @contextmanager
            def failed_open(request, timeout=0):
                yield io.BytesIO(b'{"errors":{"requests":"limit"},"response":[]}')
            with patch.object(app.urllib.request, 'urlopen', side_effect=failed_open):
                with self.assertRaises(RuntimeError):
                    app._af_get('/injuries', 'key-one')
            self.assertEqual(app._af_get('/injuries', 'key-one')['response'], [3])

    def test_confirmed_team_aliases_match_without_equating_other_teams(self):
        pairs = [('Ham-Kam', 'Hamarkameratene'), ('WSG Wattens', 'WSG Swarovski Tirol'),
                 ('Stade Brestois 29', 'Brest')]
        for api_name, site_name in pairs:
            with self.subTest(api_name=api_name):
                self.assertEqual(app._af_team_sim(api_name, {'name': site_name}), 1.0)
        self.assertLess(app._af_team_sim('Lustenau', {'name': 'Austria Lustenau'}), 1.0)

    def test_api_lines_preserve_complete_pairs_and_reject_bad_values(self):
        values = [
            {"value": "Home -1.75", "odd": "1.90"},
            {"value": "Away -1.75", "odd": "1.95"},
            {"value": "Home -1.5", "odd": "1.65"},
            {"value": "Away -1.5", "odd": "2.10"},
            {"value": "Home 0", "odd": "NaN"},
            {"value": "Away 0", "odd": "1.02"},
        ]
        self.assertEqual(app._paired_lines(values, "home", "away"), [[-1.75, 1.9, 1.95], [-1.5, 1.65, 2.1]])
        self.assertEqual(app._pick_ah(values), {"line": -1.75, "h": 1.9, "a": 1.95})
        self.assertEqual(app._canon_book('SBO'), 'SBOBET')
        self.assertEqual(app._canon_book('BetVictor'), 'BetVictor')
        self.assertEqual(app._canon_book('Betano'), 'Betano')

    def test_beidan_handicap_is_not_added_to_ordinary_odds(self):
        self.assertEqual(app._bd_line('(-2)'), -2)
        self.assertEqual(app._bd_line('（+1）'), 1)
        self.assertIsNone(app._bd_line(''))
        now = datetime.now(timezone.utc).replace(microsecond=0)
        fixtures = [{"date": now.isoformat(), "home": "1", "away": "2"}]
        teams = {"1": {"cn": "弗拉门戈"}, "2": {"cn": "巴拉纳竞技"}}
        matches = [{"date": now.isoformat(), "home": "弗拉门戈", "away": "巴拉纳竞技", "num": "21", "line": -2, "h": 5.49, "d": 4.97, "a": 1.62}]
        self.assertEqual(app.attach_beidan(fixtures, teams, matches), 1)
        self.assertEqual(fixtures[0]['bj']['line'], -2)
        self.assertNotIn('books', fixtures[0])

    def test_api_markets_and_alternate_lines_reach_matched_fixture(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        when = now + timedelta(hours=3)
        fixture = {"id": "site-match", "date": when.isoformat(), "home": "1", "away": "2", "hs": None, "as": None}
        teams = {"1": {"id": "1", "name": "Flamengo"}, "2": {"id": "2", "name": "Atletico Paranaense"}}
        api_fixture = {"fixture": {"id": 123, "date": when.isoformat(), "status": {"short": "NS"}}, "teams": {"home": {"id": 127, "name": "Flamengo"}, "away": {"id": 134, "name": "Atletico Paranaense"}}}
        odds = {"response": [{"update": "2026-11-17T08:15:09+00:00", "bookmakers": [{"name": "BetVictor", "bets": [
            {"id": 1, "values": [{"value": "Home", "odd": "1.25"}, {"value": "Draw", "odd": "6"}, {"value": "Away", "odd": "11"}]},
            {"id": 4, "values": [{"value": "Home -1.75", "odd": "1.90"}, {"value": "Away -1.75", "odd": "1.95"}, {"value": "Home -1.5", "odd": "1.65"}, {"value": "Away -1.5", "odd": "2.10"}]},
            {"id": 5, "values": [{"value": "Over 2.5", "odd": "1.48"}, {"value": "Under 2.5", "odd": "2.60"}]},
            {"id": 50, "values": [{"value": "Over 2.25", "odd": "1.3"}, {"value": "Under 2.25", "odd": "3.2"}]},
        ]}]}]}
        def fake_get(path, key, params=None, ttl=0):
            if path == '/fixtures': return {'response': [api_fixture]}
            if path == '/odds': return odds
            return {'response': []}
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'CACHE_DIR', tmp), patch.object(app, '_af_get', side_effect=fake_get), patch.dict(os.environ, {'API_FOOTBALL_KEY': 'test-only'}):
            app.attach_apifootball([fixture], teams, log=lambda *_: None)
        book = fixture['books'][0]
        self.assertEqual(book['book'], 'BetVictor')
        self.assertEqual(book['m'], [1.25, 6.0, 11.0])
        self.assertEqual(book['ah']['line'], -1.75)
        self.assertEqual(len(book['ahLines']), 2)
        self.assertEqual(book['ouLines'], [[2.5, 1.48, 2.6]])
        self.assertEqual(book['goalLines'], [[2.25, 1.3, 3.2]])
        self.assertEqual(book['marketAt']['ahLines'], '2026-11-17T08:15:09+00:00')

    def test_retained_quotes_expire_instead_of_refreshing_their_age(self):
        now = datetime.now(timezone.utc)
        fid = 'sample'
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'persist.json')
            old_time = now.timestamp() - 35 * 3600
            old_book = {'book': 'Test Book', 'm': [2, 3, 4]}
            with open(path, 'w') as f:
                json.dump({fid: {'date': (now + timedelta(days=1)).isoformat(), 'books': {'Test Book': {'t': old_time, 'b': old_book}}}}, f)
            fixture = {'id': fid, 'date': (now + timedelta(days=1)).isoformat()}
            with patch.object(app, 'BOOKS_PERSIST', path):
                app.merge_books_persist([fixture])
            with open(path) as f:
                saved = json.load(f)
            self.assertEqual(saved[fid]['books']['Test Book']['t'], old_time)


if __name__ == '__main__':
    unittest.main()
