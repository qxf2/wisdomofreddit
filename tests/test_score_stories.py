"""
Tests for score_stories.py. They use a fake Jev client, so no API key is needed.

Run from the repo root:
    python -m unittest discover tests
"""

import os
import shutil
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace

import fetch_comments
import score_stories


class FakeClient:
    "Pretends to be Jev: comments containing 'my dad' are stories"

    def __init__(self, fail_on=None):
        self.fail_on = fail_on
        self.states = []

    def system_one(self, state, questions):
        self.states.append(state)
        if self.fail_on and self.fail_on in state['comment']:
            raise RuntimeError('Service unavailable')
        is_story = 'my dad' in state['comment']
        return SimpleNamespace(
            model='jev-test',
            usage=SimpleNamespace(input_tokens=300, output_tokens=20),
            answers={'is_story': SimpleNamespace(noul=0.9 if is_story else 0.1),
                     'vividness': SimpleNamespace(score=2.5 if is_story else 0.2, confidence=0.8)})


class TestScoreStories(unittest.TestCase):
    "Test scoring comments with a fake client"

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, 'comments.db')
        connection = fetch_comments.get_connection(self.db_path)
        bodies = {'story': 'One time my dad took me fishing on a frozen lake',
                  'opinion': 'I think this movie is overrated',
                  'broken': 'This one makes the fake service fail'}
        for comment_id, body in bodies.items():
            connection.execute('INSERT INTO comments (id, body) VALUES (?, ?)', (comment_id, body))
        connection.commit()
        connection.close()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    def get_scores(self):
        connection = sqlite3.connect(self.db_path)
        scores = dict(connection.execute('SELECT id, p_story FROM story_scores'))
        connection.close()
        return scores

    def test_only_comment_text_is_sent(self):
        client = FakeClient()
        score_stories.score_comments(client, self.db_path)
        self.assertEqual(len(client.states), 3)
        self.assertTrue(all(list(state) == ['comment'] for state in client.states))

    def test_scores_are_stored(self):
        score_stories.score_comments(FakeClient(), self.db_path)
        self.assertEqual(self.get_scores(), {'story': 0.9, 'opinion': 0.1, 'broken': 0.1})

    def test_failed_comments_are_retried_on_next_run(self):
        score_stories.score_comments(FakeClient(fail_on='fail'), self.db_path)
        self.assertNotIn('broken', self.get_scores())
        client = FakeClient()
        score_stories.score_comments(client, self.db_path)
        self.assertEqual(len(client.states), 1)
        self.assertIn('broken', self.get_scores())

    def test_limit(self):
        score_stories.score_comments(FakeClient(), self.db_path, limit=2)
        self.assertEqual(len(self.get_scores()), 2)

    def test_report_runs(self):
        score_stories.score_comments(FakeClient(), self.db_path)
        score_stories.report(self.db_path)


if __name__ == '__main__':
    unittest.main()
