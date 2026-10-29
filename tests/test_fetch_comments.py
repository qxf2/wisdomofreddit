"""
Tests for fetch_comments.py

Run from the repo root:
    python -m unittest discover tests
"""

import json
import os
import shutil
import sqlite3
import tempfile
import unittest

import zstandard

import fetch_comments


def make_comment(comment_id, score=100, words=200, body=None):
    "Return a comment in the same shape as the monthly dumps"
    return {'id': comment_id,
            'link_id': 't3_abc',
            'score': score,
            'body': body if body is not None else ' '.join(['word'] * words),
            'name': 't1_' + comment_id,
            'created_utc': 1764547200,
            'subreddit': 'AskReddit',
            'parent_id': 't3_abc'}


class TestFilter(unittest.TestCase):
    "Test the comment filter rules"

    def test_good_comment(self):
        self.assertTrue(fetch_comments.is_good_comment(make_comment('a')))

    def test_score_must_be_more_than_35(self):
        self.assertFalse(fetch_comments.is_good_comment(make_comment('a', score=35)))
        self.assertTrue(fetch_comments.is_good_comment(make_comment('a', score=36)))

    def test_words_must_be_more_than_150(self):
        self.assertFalse(fetch_comments.is_good_comment(make_comment('a', words=150)))
        self.assertTrue(fetch_comments.is_good_comment(make_comment('a', words=151)))

    def test_deleted_and_removed(self):
        self.assertFalse(fetch_comments.is_good_comment(make_comment('a', body='[deleted]')))
        self.assertFalse(fetch_comments.is_good_comment(make_comment('a', body='[removed]')))

    def test_missing_fields(self):
        self.assertFalse(fetch_comments.is_good_comment({}))


class TestDump(unittest.TestCase):
    "Test filtering a small dump into a db"

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, 'comments.db')
        self.zst_path = os.path.join(self.tmp_dir, 'RC_2025-12.zst')
        comments = [make_comment('good1'),
                    make_comment('good2', score=500),
                    make_comment('low_score', score=10),
                    make_comment('short', words=20)]
        lines = '\n'.join(json.dumps(comment) for comment in comments) + '\nnot json\n'
        with open(self.zst_path, 'wb') as fp:
            fp.write(zstandard.ZstdCompressor().compress(lines.encode('utf-8')))

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    def get_ids(self, db_path):
        connection = sqlite3.connect(db_path)
        ids = [row[0] for row in connection.execute('SELECT id FROM comments ORDER BY id')]
        connection.close()
        return ids

    def test_filter_dump(self):
        fetch_comments.filter_dump(self.zst_path, '2025-12', self.db_path)
        self.assertEqual(self.get_ids(self.db_path), ['good1', 'good2'])
        connection = sqlite3.connect(self.db_path)
        done = connection.execute('SELECT month, lines_read, comments_kept FROM months_done').fetchall()
        gilded = connection.execute('SELECT gilded FROM comments').fetchall()
        connection.close()
        self.assertEqual(done, [('2025-12', 4, 2)])
        self.assertEqual(gilded, [(0,), (0,)])

    def test_month_is_not_filtered_twice(self):
        fetch_comments.filter_dump(self.zst_path, '2025-12', self.db_path)
        fetch_comments.filter_dump(self.zst_path, '2025-12', self.db_path)
        self.assertEqual(self.get_ids(self.db_path), ['good1', 'good2'])

    def test_sample(self):
        fetch_comments.filter_dump(self.zst_path, '2025-12', self.db_path)
        sample_path = os.path.join(self.tmp_dir, 'sample.db')
        fetch_comments.make_sample(sample_path, 1, self.db_path)
        self.assertEqual(len(self.get_ids(sample_path)), 1)


if __name__ == '__main__':
    unittest.main()
