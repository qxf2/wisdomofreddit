"""
Tests for index_comments.py and wisdomofreddit.py. They build a tiny Whoosh
index in a temp folder, so no real data is needed.

Run from the repo root:
    python -m unittest discover tests
"""

import os
import shutil
import tempfile
import unittest
from unittest import mock

from whoosh import index

import index_comments
import wisdomofreddit

HEADER = 'link_id,id,score,body,name,created_utc,subreddit,parent_id,gilded'
ROWS = [
    't3_abc,c1,120,"My grandfather taught me chess with a broken board, café style.",'
    't1_c1,1420070400,chess,t1_p1,0',
    't3_def,c2,not_a_number,"A story about a lighthouse keeper\nwho split a line in two.",'
    't1_c2,1420070401,AskReddit,t3_def,1',
]


class AppTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.csvfile = os.path.join(self.tmp, 'comments.csv')
        with open(self.csvfile, 'w', encoding='utf-8') as fp:
            fp.write(HEADER + '\n' + '\n'.join(ROWS) + '\n')
        self.index_dir = os.path.join(self.tmp, 'indexdir')
        index_comments.update_index(self.csvfile, index_name='wor',
                                    new_index_flag='true', index_dir=self.index_dir)
        patcher = mock.patch.object(
            wisdomofreddit, 'open_index',
            lambda index_dir, index_name: index.open_dir(self.index_dir, indexname=index_name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = wisdomofreddit.app.test_client()

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

    def test_search_returns_fields_after_searcher_closes(self):
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


if __name__ == '__main__':
    unittest.main()
