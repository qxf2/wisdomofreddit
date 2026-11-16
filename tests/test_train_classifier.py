"""
Tests for train_classifier.py on a tiny made-up db, so no real data is needed.

Run from the repo root:
    python -m unittest discover tests
"""

import contextlib
import io
import os
import shutil
import sqlite3
import tempfile
import unittest

import fetch_comments
import score_stories
import train_classifier

STORIES = ['One time my dad took me fishing on a frozen lake and we fell in',
           'When I worked as a nurse a patient told me about her childhood farm',
           'My grandmother once drove across the country alone in an old truck',
           'Back in college my roommate and I got lost hiking for two days']
NOT_STORIES = ['lol this is the best pun ever', 'Source? That sounds made up',
               'Upvote for visibility', 'This is just wrong and you know it']


class TestTrainClassifier(unittest.TestCase):
    "Test training, evaluating and predicting on a tiny db"

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, 'comments.db')
        self.sample_path = os.path.join(self.tmp_dir, 'sample.db')
        self.model_path = os.path.join(self.tmp_dir, 'models', 'model.joblib')
        fetch_comments.get_connection(self.db_path).close()
        connection = score_stories.get_connection(self.db_path)
        rows = []
        # 10 copies of each text with small changes, so there is enough to split
        for copy in range(10):
            for index, body in enumerate(STORIES + NOT_STORIES):
                comment_id = 'c%d_%d' % (index, copy)
                story = body in STORIES
                connection.execute('INSERT INTO comments (id, body, month) VALUES (?,?,?)',
                                   (comment_id, '%s %d' % (body, copy), '2025-12'))
                # One story with low vividness must count as not a story
                vividness = 2.5 if story else 0.2
                if comment_id == 'c0_0':
                    vividness = 1.0
                rows.append((comment_id, 0.9 if story else 0.1, vividness))
        connection.executemany(
            "INSERT INTO story_scores (id, p_story, vividness) VALUES (?,?,?)", rows)
        connection.commit()
        connection.close()

        # The sample db holds two comments that must never be trained or tested on
        fetch_comments.get_connection(self.sample_path).close()
        connection = sqlite3.connect(self.sample_path)
        connection.executemany('INSERT INTO comments (id, body) VALUES (?,?)',
                               [('c1_1', 'x'), ('c5_1', 'y')])
        connection.commit()
        connection.close()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    def run_quietly(self, function, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            function(*args)
        return output.getvalue()

    def test_labels_follow_story_rule(self):
        "Labels need both p_story >= 0.5 and vividness >= 2"
        ids, _, labels = train_classifier.load_labelled(self.db_path)
        by_id = dict(zip(ids, labels))
        self.assertEqual(by_id['c0_0'], 0)
        self.assertEqual(by_id['c0_1'], 1)
        self.assertEqual(by_id['c4_1'], 0)

    def test_train_excludes_sample_comments(self):
        "Sample comments are in neither the training nor the test split"
        self.run_quietly(train_classifier.train, self.db_path, self.model_path, self.sample_path)
        saved = train_classifier.joblib.load(self.model_path)
        self.assertNotIn('c1_1', saved['test_ids'])
        self.assertEqual(len(saved['test_ids']), 16)  # 20% of 78

    def test_evaluate_reports_agreement(self):
        "Evaluate prints the model-only line and the band table"
        self.run_quietly(train_classifier.train, self.db_path, self.model_path, self.sample_path)
        output = self.run_quietly(train_classifier.evaluate, self.db_path, self.model_path)
        self.assertIn('Model alone: accuracy', output)
        self.assertIn('0.3-0.7', output)
        self.assertIn('All comments to Jev:', output)

    def test_bands_send_unsure_comments_to_jev(self):
        "Comments in the unsure band take Jev's label"
        probabilities = [0.05, 0.45, 0.55, 0.95]
        jev_labels = [0, 1, 0, 1]
        rows = dict((band, rest) for band, *rest in
                    train_classifier.band_rows(probabilities, jev_labels, [(0.5, 0.5), (0.4, 0.6)]))
        share, accuracy = rows[(0.5, 0.5)][:2]
        self.assertEqual(share, 0.0)
        self.assertEqual(accuracy, 0.5)
        share, accuracy = rows[(0.4, 0.6)][:2]
        self.assertEqual(share, 0.5)
        self.assertEqual(accuracy, 1.0)

    def test_predict_writes_model_scores_and_compares(self):
        "Predict fills model_scores and compares with Jev when story_scores exists"
        self.run_quietly(train_classifier.train, self.db_path, self.model_path, self.sample_path)
        output = self.run_quietly(train_classifier.predict, self.db_path, self.model_path)
        connection = sqlite3.connect(self.db_path)
        count, = connection.execute('SELECT COUNT(*) FROM model_scores').fetchone()
        connection.close()
        self.assertEqual(count, 80)
        self.assertIn('Compared with Jev:', output)

    def test_predict_without_jev_scores(self):
        "Predict works on a db that Jev has not scored"
        self.run_quietly(train_classifier.train, self.db_path, self.model_path, self.sample_path)
        output = self.run_quietly(train_classifier.predict, self.sample_path, self.model_path)
        self.assertIn('Labelled 2 comments', output)
        self.assertNotIn('Compared with Jev:', output)


if __name__ == '__main__':
    unittest.main()
