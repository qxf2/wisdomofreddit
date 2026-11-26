"""
Tests for index_comments.py (the old Whoosh indexer) and wisdomofreddit.py.
The app tests build a tiny story search index (story_search.py) in a temp
folder, so no real data is needed.

Run from the repo root:
    python -m unittest discover tests
"""

import io
import logging
import os
import shutil
import tempfile
import unittest
from unittest import mock

from whoosh import index

# Keep test runs out of the real log file. Set before the app is imported.
os.environ['WOR_LOG_FILE'] = os.path.join(tempfile.mkdtemp(), 'test.log')

import index_comments
import story_search
import wisdomofreddit
from test_story_search import make_comments_db

HEADER = 'link_id,id,score,body,name,created_utc,subreddit,parent_id,gilded'
ROWS = [
    't3_abc,c1,120,"My grandfather taught me chess with a broken board, café style.",'
    't1_c1,1420070400,chess,t1_p1,0',
    't3_def,c2,not_a_number,"A story about a lighthouse keeper\nwho split a line in two.",'
    't1_c2,1420070401,AskReddit,t3_def,1',
]


class IndexCommentsTest(unittest.TestCase):
    "The old Whoosh indexer for the 2007 to 2015 CSV files"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.csvfile = os.path.join(self.tmp, 'comments.csv')
        with open(self.csvfile, 'w', encoding='utf-8') as fp:
            fp.write(HEADER + '\n' + '\n'.join(ROWS) + '\n')
        self.index_dir = os.path.join(self.tmp, 'indexdir')
        index_comments.update_index(self.csvfile, index_name='wor',
                                    new_index_flag='true', index_dir=self.index_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_pre_process_joins_split_lines_and_drops_non_ascii(self):
        lines = index_comments.pre_process_csv(self.csvfile)
        self.assertEqual(len(lines), 2)
        self.assertIn('caf  style', lines[0])
        self.assertIn('keeper who split', lines[1])

    def test_index_has_both_comments_with_fields(self):
        ix = index.open_dir(self.index_dir, indexname='wor')
        with ix.searcher() as searcher:
            docs = sorted(searcher.documents(), key=lambda d: d['name'])
        self.assertEqual(len(docs), 2)
        self.assertEqual(docs[0]['url'], 'http://www.reddit.com/comments/abc/x/c1')
        self.assertEqual(docs[0]['parent'], 'p1')
        self.assertEqual(docs[1]['score'], 35)  # bad score falls back to 35

    def test_sample_data_indexes_every_row(self):
        sample = os.path.join(os.path.dirname(__file__), '..', 'sample_data', 'sample_comments.csv')
        sample_dir = os.path.join(self.tmp, 'sample_index')
        index_comments.update_index(sample, index_name='wor', new_index_flag='true',
                                    index_dir=sample_dir)
        self.assertEqual(index.open_dir(sample_dir, indexname='wor').doc_count(), 200)


class AppTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        comments_db = make_comments_db(os.path.join(self.tmp, 'comments.db'))
        search_dir = os.path.join(self.tmp, 'search')
        story_search.add_stories(story_search.connect(search_dir), comments_db)
        patcher = mock.patch.object(wisdomofreddit, 'SEARCH_DIR', search_dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = wisdomofreddit.app.test_client()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_search_returns_fields(self):
        results = wisdomofreddit.search_comments('chess')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['subreddit'], 'chess')

    def test_search_page_shows_result(self):
        response = self.client.get('/search?query=lighthouse')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'/r/AskReddit', response.data)

    def test_random_page_shows_result(self):
        with mock.patch.object(wisdomofreddit, 'get_random_query', return_value='chess'):
            response = self.client.get('/random')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'/r/chess', response.data)

    def test_random_page_gives_up_when_nothing_matches(self):
        with mock.patch.object(wisdomofreddit, 'get_random_query', return_value='zzzz'):
            response = self.client.get('/random')
        self.assertEqual(response.status_code, 200)

    def test_static_pages_load(self):
        pages = ['/', '/about', '/why', '/uses', '/pro-tips', '/examples', '/blog',
                 '/blogposts/real-scary-creepy-paranormal-stories',
                 '/blogposts/mundane-coincidence-stories',
                 '/api-tutorial-main', '/api-tutorial-redirect', '/trial-page-bug',
                 '/trial-redirect-page-bug', '/retrieve-wrong-data',
                 '/retrieve-wrong-data-redirect-page', '/no-response',
                 '/no-response-page-bug', '/click-button-bug']
        for page in pages:
            with self.subTest(page=page):
                self.assertEqual(self.client.get(page).status_code, 200)


class LoggingTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.log_file = os.path.join(self.tmp, 'nested', 'app.log')
        wisdomofreddit.setup_logging(self.log_file)
        self.addCleanup(wisdomofreddit.setup_logging)

    def read_log(self):
        for handler in wisdomofreddit.logger.handlers:
            handler.flush()
        with open(self.log_file, encoding='utf-8') as fp:
            return fp.read()

    def test_search_logs_one_info_line_with_query_and_count(self):
        comments_db = make_comments_db(os.path.join(self.tmp, 'comments.db'))
        search_dir = os.path.join(self.tmp, 'search')
        story_search.add_stories(story_search.connect(search_dir), comments_db)
        with mock.patch.object(wisdomofreddit, 'SEARCH_DIR', search_dir):
            wisdomofreddit.search_comments('chess')
        lines = self.read_log().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertIn(' INFO ', lines[0])
        self.assertIn("query='chess' results=1", lines[0])

    def test_search_failure_logs_error_with_stack_trace(self):
        with mock.patch.object(story_search, 'search', side_effect=RuntimeError('boom')):
            self.assertEqual(wisdomofreddit.search_comments('chess'), [])
        log = self.read_log()
        self.assertIn(" ERROR wisdomofreddit: Search failed for query='chess'", log)
        self.assertIn('Traceback (most recent call last)', log)

    def test_log_file_comes_from_env_var(self):
        env_file = os.path.join(self.tmp, 'from_env.log')
        with mock.patch.dict(os.environ, {'WOR_LOG_FILE': env_file}):
            self.assertEqual(wisdomofreddit.setup_logging(), env_file)
        self.assertEqual(wisdomofreddit.logger.handlers[0].baseFilename, env_file)

    def test_unwritable_log_file_falls_back_to_stderr(self):
        blocker = os.path.join(self.tmp, 'a_file')
        open(blocker, 'w').close()
        with mock.patch('sys.stderr', new_callable=io.StringIO) as stderr:
            wisdomofreddit.setup_logging(os.path.join(blocker, 'app.log'))
        self.assertEqual(len(wisdomofreddit.logger.handlers), 1)
        self.assertNotIsInstance(wisdomofreddit.logger.handlers[0], logging.FileHandler)
        self.assertIn('WARNING wisdomofreddit: Could not open log file', stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
