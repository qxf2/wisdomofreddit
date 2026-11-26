"""
Tests for eval_search.py. They build the tiny index from test_story_search,
so no real data, Jammi model or Jev call is needed.

Run from the repo root:
    python -m unittest discover tests
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

import eval_search
import story_search
from test_story_search import make_comments_db


class InputTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_queries_file_skips_comments_and_notes(self):
        path = os.path.join(self.tmp, 'q.txt')
        with open(path, 'w', encoding='utf-8') as fp:
            fp.write('# comment\n\nphrase\t"dentist here"\t#31\nawkward\t"\n')
        self.assertEqual(eval_search.read_queries(path),
                         [('phrase', '"dentist here"'), ('awkward', '"')])

    def test_shipped_query_set(self):
        queries = eval_search.read_queries()
        self.assertEqual(len(queries), 50)
        self.assertEqual({k for k, _ in queries}, set(eval_search.TYPES))
        self.assertEqual(len(set(q for _, q in queries)), 50)

    def test_shipped_labels_are_valid(self):
        for (query, story), judges in eval_search.read_labels().items():
            for judge, label in judges.items():
                self.assertEqual((label['query'], label['id'], label['judge']), (query, story, judge))
                self.assertIsInstance(label['relevant'], bool)

    def test_labels_round_trip_and_first_judge_wins(self):
        path = os.path.join(self.tmp, 'labels.jsonl')
        labels = {('q', 'a'): {'jev': {'query': 'q', 'id': 'a', 'judge': 'jev', 'relevant': False},
                               'human': {'query': 'q', 'id': 'a', 'judge': 'human', 'relevant': True}}}
        eval_search.write_labels(labels, path)
        labels = eval_search.read_labels(path)
        self.assertTrue(eval_search.judgment(labels, 'q', 'a', ['human', 'jev']))
        self.assertFalse(eval_search.judgment(labels, 'q', 'a', ['jev', 'human']))
        self.assertIsNone(eval_search.judgment(labels, 'q', 'a', ['claude']))
        self.assertIsNone(eval_search.judgment(labels, 'q', 'b', ['human']))


class HelperTest(unittest.TestCase):

    def test_constraints(self):
        self.assertEqual(eval_search.constraints('"night shift" nurse'), (['night shift'], []))
        self.assertEqual(eval_search.constraints('"first job" boss -retail'), (['first job'], ['retail']))
        self.assertEqual(eval_search.constraints('chess NOT tournament'), ([], ['tournament']))
        self.assertEqual(eval_search.constraints('ex-cia "-quoted" NOT'), (['-quoted'], []))
        self.assertEqual(eval_search.constraints('"'), ([], []))

    def test_p95(self):
        self.assertEqual(eval_search.p95([]), 0.0)
        self.assertEqual(eval_search.p95([5]), 5)
        self.assertEqual(eval_search.p95(list(range(1, 101))), 95)
        self.assertEqual(eval_search.p95(list(range(1, 11))), 10)


class EvaluateTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.dir = os.path.join(self.tmp, 'search')
        con = story_search.connect(self.dir)
        story_search.add_stories(con, make_comments_db(os.path.join(self.tmp, 'comments.db')))
        con.close()
        self.queries = os.path.join(self.tmp, 'queries.txt')
        with open(self.queries, 'w', encoding='utf-8') as fp:
            fp.write('keyword\tchess\nphrase\t"dentist here"\nphrase\t"no such phrase"\n'
                     'mixed\tlighthouse -storm\nawkward\t"\n')
        self.labels = os.path.join(self.tmp, 'labels.jsonl')
        eval_search.write_labels({('chess', 'c1'): {'human': {
            'query': 'chess', 'id': 'c1', 'judge': 'human', 'relevant': True}}}, self.labels)

    def evaluate(self, **kw):
        with mock.patch.object(story_search, 'vector_ids', return_value=[]):
            return eval_search.evaluate(self.dir, self.queries, self.labels, repeat=1, **kw)

    def test_summary(self):
        runs, summary, _ = self.evaluate()
        self.assertEqual(summary['keyword']['relevant'], 1)
        self.assertEqual(summary['keyword']['judged'], 1)
        self.assertEqual(summary['phrase']['unjudged'], 1)       # c3 for "dentist here"
        self.assertEqual(summary['phrase']['zero'], 1)
        self.assertEqual(summary['mixed']['excluded_hits'], 0)   # c2 has "storm", so it is left out
        self.assertEqual(summary['mixed']['zero'], 1)
        self.assertEqual(summary['all']['queries'], 5)
        self.assertEqual(summary['all']['errors'], 0)
        self.assertEqual(eval_search.unjudged_pairs(runs), [('"dentist here"', 'c3')])
        table = eval_search.format_table(summary)
        self.assertIn('keyword', table)
        self.assertIn('1/10', table)

    def test_phrase_misses_are_counted(self):
        with mock.patch.object(story_search, 'search', return_value=[
                {'url': 'https://www.reddit.com/comments/abc/x/c1'}]):
            runs, summary, _ = eval_search.evaluate(self.dir, self.queries, self.labels, repeat=1)
        self.assertEqual(summary['phrase']['phrase_misses'], 2)

    def test_excluded_hits_are_counted(self):
        with mock.patch.object(story_search, 'search', return_value=[
                {'url': 'https://www.reddit.com/comments/def/x/c2'}]):
            _, summary, _ = eval_search.evaluate(self.dir, self.queries, self.labels, repeat=1)
        self.assertEqual(summary['mixed']['excluded_hits'], 1)

    def test_related_results_are_not_phrase_misses(self):
        related = story_search.Results([{'url': 'https://www.reddit.com/comments/abc/x/c1'}])
        related.related = True
        with mock.patch.object(story_search, 'search', return_value=related):
            _, summary, _ = eval_search.evaluate(self.dir, self.queries, self.labels, repeat=1)
        self.assertEqual(summary['phrase']['phrase_misses'], 0)
        self.assertEqual(summary['phrase']['related'], 2)
        self.assertEqual(summary['phrase']['zero'], 0)

    def test_errors_are_counted_not_raised(self):
        with mock.patch.object(story_search, 'search', side_effect=RuntimeError('boom')):
            runs, summary, _ = eval_search.evaluate(self.dir, self.queries, self.labels, repeat=1)
        self.assertEqual(summary['all']['errors'], 5)
        self.assertIn('boom', runs[0]['error'])

    def test_logged_vector_failure_counts_as_error(self):
        with mock.patch.object(story_search, 'vector_ids', side_effect=RuntimeError('boom')), \
                self.assertLogs(story_search.logger, 'ERROR'):
            _, summary, _ = eval_search.evaluate(self.dir, self.queries, self.labels, repeat=1)
        self.assertEqual(summary['keyword']['errors'], 1)
        self.assertEqual(summary['phrase']['errors'], 2)          # phrases use vectors too (#46)

    def test_jev_labels_are_saved(self):
        def fake(pairs, search_dir, labels, workers=16):
            for query, story in pairs:
                labels.setdefault((query, story), {})['jev'] = {
                    'query': query, 'id': story, 'judge': 'jev', 'relevant': True, 'p': 0.9}
            return len(pairs)
        with mock.patch.object(eval_search, 'label_with_jev', side_effect=fake):
            _, summary, _ = self.evaluate(label_jev=True)
        self.assertEqual(summary['all']['unjudged'], 0)
        self.assertEqual(summary['all']['relevant'], 2)
        self.assertEqual(len(eval_search.read_labels(self.labels)), 2)

    def test_compare(self):
        _, summary, _ = self.evaluate()
        before = json.loads(json.dumps({'summary': summary}))
        before['summary']['keyword']['relevant'] = 0
        self.assertIn('rel@10 +1 (0 -> 1)', eval_search.format_compare(summary, before))


if __name__ == '__main__':
    unittest.main()
