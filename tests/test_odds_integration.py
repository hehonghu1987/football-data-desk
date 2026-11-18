import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import build_data as app


class OddsIntegrationTests(unittest.TestCase):
    def test_oddsapi_gap_fill_only_uses_returned_markets_and_preserves_existing(self):
        import io
        from contextlib import contextmanager
        when = datetime.now(timezone.utc) + timedelta(hours=2)
        original = {'line': -0.5, 'h': 1.9, 'a': 1.9}
        fixture = {'id': 'upcoming', 'date': when.isoformat(), 'league': '巴西甲', 'home': '1', 'away': '2',
                   'books': [{'book': 'Ladbrokes', 'src': 'oddsapi', 'm': [1.8, 3.6, 4.2],
                              'ah': {'line': -1.5, 'h': 3.25, 'a': 1.29, 'alternate': True}},
                             {'book': 'William Hill', 'src': 'oddsapi', 'm': [1.8, 3.5, 4.0], 'ah': original}]}
        teams = {'1': {'name': 'Corinthians'}, '2': {'name': 'Botafogo'}}
        response = [{'commence_time': when.isoformat(), 'home_team': 'Corinthians', 'away_team': 'Botafogo', 'bookmakers': [
            {'title': 'Ladbrokes', 'markets': [
                {'key': 'spreads', 'last_update': '2026-11-18T12:00:00Z', 'outcomes': [{'name': 'Corinthians', 'point': -0.5, 'price': 1.9}, {'name': 'Botafogo', 'point': 0.5, 'price': 2.0}]},
                {'key': 'totals', 'outcomes': [{'name': 'Over', 'point': 2.5, 'price': 1.8}, {'name': 'Under', 'point': 2.5, 'price': 2.0}]},
            ]},
            {'title': 'William Hill', 'markets': [{'key': 'spreads', 'outcomes': [{'name': 'Corinthians', 'point': -1, 'price': 2}, {'name': 'Botafogo', 'point': 1, 'price': 1.8}]}]},
        ]}]
        calls = []
        @contextmanager
        def fake_open(req, timeout=0):
            calls.append(req.full_url)
            stream = io.BytesIO(json.dumps(response).encode())
            stream.headers = {'x-requests-remaining': '151'}
            yield stream
        with tempfile.TemporaryDirectory() as tmp:
            cache = os.path.join(tmp, 'cache')
            os.makedirs(cache)
            state = os.path.join(tmp, 'odds-state.json')
            with open(state, 'w') as f:
                json.dump({'remaining': 153, 'last': 100}, f)
            with patch.object(app, 'ROOT', tmp), patch.object(app, 'CACHE_DIR', cache), patch.object(app, 'ODDSAPI_STATE', state), patch.object(app, 'ODDSAPI_BOOKS', os.path.join(tmp, 'odds-books.json')), patch.object(app.urllib.request, 'urlopen', side_effect=fake_open), patch.dict(os.environ, {'ODDS_API_KEY': 'test-only'}):
                self.assertEqual(app.fill_oddsapi_market_gaps([fixture], teams), 2)
                lad = fixture['books'][0]
                self.assertEqual(lad['ah'], {'line': -0.5, 'h': 1.9, 'a': 2.0})
                self.assertEqual(lad['ou'], {'line': 2.5, 'over': 1.8, 'under': 2.0})
                restored = {'id': 'upcoming', 'date': when.isoformat()}
                app.load_oddsapi_snapshot([restored])
                app.filter_whitelist_books([restored])
                copied = next(b for b in restored['books'] if b['book'] == 'Ladbrokes')
                self.assertEqual(copied['ah'], lad['ah'])
                self.assertEqual(copied['marketAt']['ah'], '2026-11-18T12:00:00Z')
                self.assertEqual(fixture['books'][1]['ah'], original)
                self.assertIsNone(fixture['books'][1].get('ou'))
                self.assertEqual(app.fill_oddsapi_market_gaps([fixture], teams), 0)
                self.assertEqual(len(calls), 1)
                second_fixture = {'id': 'second', 'date': when.isoformat(), 'league': '英超', 'home': '1', 'away': '2',
                                  'books': [{'book': 'Ladbrokes', 'src': 'oddsapi', 'm': [1.8, 3.6, 4.2]}]}
                self.assertEqual(app.fill_oddsapi_market_gaps([second_fixture], teams), 2)
                self.assertIn('betfair', calls[1])
                self.assertEqual(app.fill_oddsapi_market_gaps([fixture, second_fixture], teams), 0)
                self.assertEqual(len(calls), 2)

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

    def test_empty_odds_cache_is_rechecked_soon(self):
        from contextlib import contextmanager
        import io
        responses = iter([{'response': [], 'errors': []}, {'response': [{'fixture': 1}], 'errors': []}])
        @contextmanager
        def fake_open(request, timeout=0):
            yield io.BytesIO(json.dumps(next(responses)).encode())
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'CACHE_DIR', tmp), patch.object(app.urllib.request, 'urlopen', side_effect=fake_open):
            self.assertEqual(app._af_get('/odds', 'key-one', {'fixture': 1}, ttl=3600)['response'], [])
            cache_file = os.path.join(tmp, os.listdir(tmp)[0])
            old = datetime.now().timestamp() - 901
            os.utime(cache_file, (old, old))
            self.assertEqual(app._af_get('/odds', 'key-one', {'fixture': 1}, ttl=3600)['response'], [{'fixture': 1}])

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

    def test_available_alternate_handicap_is_marked_and_not_discarded(self):
        values = [{'value': 'Home -1.5', 'odd': '3.25'}, {'value': 'Away -1.5', 'odd': '1.29'},
                  {'value': 'Home +1.5', 'odd': '1.04'}, {'value': 'Away +1.5', 'odd': '9.50'}]
        self.assertEqual(app._pick_ah(values), {'line': -1.5, 'h': 3.25, 'a': 1.29, 'alternate': True})

    def test_coverage_does_not_count_alternate_as_main_line(self):
        fixture = {'date': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                   'league': '巴西甲', 'hs': None, 'as': None,
                   'books': [{'book': 'Betfair', 'm': [2, 3, 4],
                              'ah': {'line': -1.5, 'h': 3.25, 'a': 1.29, 'alternate': True}}]}
        logs = []
        app.log_odds_coverage([fixture], log=logs.append)
        self.assertTrue(any('覆盖 巴西甲' in line and '亚盘主线 0' in line for line in logs))
        self.assertTrue(any('机构覆盖 Betfair' in line and '备选 1' in line for line in logs))

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

    def test_historical_stats_require_exact_teams_time_and_score(self):
        match = {'id': 'old1', 'date': '2023-05-11T22:30:00Z', 'home': '1', 'away': '2', 'hs': 3, 'as': 0, 'stats': None}
        teams = {'1': {'name': 'Botafogo'}, '2': {'name': 'Corinthians'}}
        candidate = {'fixture': {'id': 1005690, 'date': '2023-05-11T22:30:00Z'}, 'goals': {'home': 3, 'away': 0}, 'teams': {'home': {'id': 120, 'name': 'Botafogo'}, 'away': {'id': 131, 'name': 'Corinthians'}}}
        records = [{'team': {'id': 120}, 'statistics': [{'type': 'Total Shots', 'value': 16}, {'type': 'Ball Possession', 'value': '53%'}, {'type': 'Red Cards', 'value': None}]}, {'team': {'id': 131}, 'statistics': [{'type': 'Total Shots', 'value': 12}, {'type': 'Ball Possession', 'value': '47%'}]}]
        def fake_get(path, key, params=None, ttl=0):
            return {'response': [candidate] if path == '/fixtures' else records}
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'CACHE_DIR', tmp), patch.object(app, '_af_get', side_effect=fake_get), patch.dict(os.environ, {'API_FOOTBALL_KEY': 'test-only'}):
            self.assertEqual(app.backfill_missing_history([match], [{'date': '2026-11-19T00:30:00Z', 'home': '1', 'away': '2'}], teams, log=lambda *_: None), 1)
            self.assertEqual(match['stats']['home']['shots'], 16)
            self.assertEqual(match['stats']['away']['possession'], 47)
            self.assertNotIn('red', match['stats']['home'])
            restored = dict(match, stats=None)
            self.assertEqual(app.backfill_missing_history([restored], [], teams, log=lambda *_: None), 1)
            self.assertEqual(restored['stats'], match['stats'])
            wrong = dict(match, id='old2', hs=2, stats=None)
            self.assertEqual(app.backfill_missing_history([wrong], [], teams, log=lambda *_: None), 0)
            self.assertIsNone(wrong['stats'])

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
        requested_paths = []
        def fake_get(path, key, params=None, ttl=0, empty_ttl=900):
            requested_paths.append(path)
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
        self.assertNotIn('/fixtures/lineups', requested_paths)  # 比赛还在三小时以后

        # 备选盘口不能覆盖另一个来源已经给出的主盘口。
        odds['response'][0]['bookmakers'][0]['bets'][1]['values'] = [
            {'value': 'Home -1.5', 'odd': '3.25'}, {'value': 'Away -1.5', 'odd': '1.29'}]
        main = {'line': -0.5, 'h': 1.9, 'a': 2.0}
        f2 = dict(fixture, books=[{'book': 'BetVictor', 'ah': main}])
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'CACHE_DIR', tmp), patch.object(app, '_af_get', side_effect=fake_get), patch.dict(os.environ, {'API_FOOTBALL_KEY': 'test-only'}):
            app.attach_apifootball([f2], teams, log=lambda *_: None)
        self.assertEqual(f2['books'][0]['ah'], main)
        self.assertEqual(f2['books'][0]['ahLines'], [[-1.5, 3.25, 1.29]])

    def test_future_window_expands_only_when_quota_permits(self):
        when = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=8)
        fixture = {'id': 'future', 'date': when.isoformat(), 'home': '1', 'away': '2', 'hs': None, 'as': None}
        teams = {'1': {'id': '1', 'name': 'Sabah FK'}, '2': {'id': '2', 'name': 'Barcelona'}}
        api = {'fixture': {'id': 1635718, 'date': when.isoformat(), 'status': {'short': 'NS'}},
               'teams': {'home': {'id': 1, 'name': 'Sabah FA'}, 'away': {'id': 2, 'name': 'Barcelona'}}}
        calls = []
        def fake_get(path, key, params=None, ttl=0, empty_ttl=900):
            calls.append((path, ttl, empty_ttl))
            if path == '/status': return {'response': {'requests': {'limit_day': 7500, 'current': 1000}}}
            if path == '/fixtures': return {'response': [api]}
            if path == '/odds': return {'response': [{'bookmakers': [{'name': 'William Hill', 'bets': [
                {'id': 1, 'values': [{'value': 'Home', 'odd': '8'}, {'value': 'Draw', 'odd': '5'}, {'value': 'Away', 'odd': '1.3'}]}]}]}]}
            return {'response': []}
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'CACHE_DIR', tmp), patch.object(app, '_af_get', side_effect=fake_get), patch.dict(os.environ, {'API_FOOTBALL_KEY': 'test-only'}):
            app.attach_apifootball([fixture], teams, log=lambda *_: None)
        self.assertEqual(fixture['af'], '1635718')
        self.assertEqual(fixture['books'][0]['book'], 'William Hill')
        self.assertIn(('/odds', 43200, 21600), calls)

        calls.clear()
        def low_quota(path, key, params=None, ttl=0, empty_ttl=900):
            calls.append(path)
            if path == '/status': return {'response': {'requests': {'limit_day': 7500, 'current': 6800}}}
            return {'response': []}
        other = dict(fixture, id='future-low')
        other.pop('af', None)
        other.pop('books', None)
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'CACHE_DIR', tmp), patch.object(app, '_af_get', side_effect=low_quota), patch.dict(os.environ, {'API_FOOTBALL_KEY': 'test-only'}):
            app.attach_apifootball([other], teams, log=lambda *_: None)
        self.assertNotIn('af', other)
        self.assertNotIn('/odds', calls)

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
