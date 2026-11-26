"""
Tests for story_search.py and build_search_index.py. They build a tiny
comments db and search index in a temp folder, so no real data is needed.

Run from the repo root:
    python -m unittest discover tests
"""

import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock

import numpy as np

import story_search

# id, link_id, score, body, subreddit, parent_id, created_utc, p_story, vividness
STORIES = [
    ('c1', 't3_abc', 120, 'My grandfather taught me chess with a broken board.', 'chess',
     't1_p1', 1764547200, 0.9, 4),
    ('c2', 't3_def', 80, 'A lighthouse keeper told me about the storm of 1987.', 'AskReddit',
     't3_def', 1764547300, 0.8, 3),
    ('c3', 't3_ghi', 60, 'The ex-cia agent at the dentist here was weird.', 'tifu',
     't3_ghi', 1764547400, 0.7, 2),
    ('c4', 't3_jkl', 50, 'I think chess engines are overrated.', 'chess',
     't3_jkl', 1764547500, 0.2, 1),     # not a story
    ('c5', 't3_mno', 50, 'Vivid but probably not a story about chess.', 'chess',
     't3_mno', 1764547600, 0.4, 5),     # p_story too low
]


def make_comments_db(path, rows=STORIES):
    "A comments db shaped like fetch_comments.py + score_stories.py output"
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE IF NOT EXISTS comments (id TEXT PRIMARY KEY, link_id TEXT, '
                'score INTEGER, body TEXT, name TEXT, created_utc INTEGER, subreddit TEXT, '
                'parent_id TEXT, gilded INTEGER, month TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS story_scores (id TEXT PRIMARY KEY, p_story REAL, '
                'vividness REAL)')
    for id_, link, score, body, sub, parent, created, p_story, vivid in rows:
        con.execute('INSERT OR IGNORE INTO comments VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (id_, link, score, body, 't1_' + id_, created, sub, parent, 0, '2025-12'))
        con.execute('INSERT OR IGNORE INTO story_scores VALUES (?,?,?)', (id_, p_story, vivid))
    con.commit()
    con.close()
    return path


class FtsQueryTest(unittest.TestCase):

    def test_words_and_phrases_are_quoted(self):
        self.assertEqual(story_search.fts_query('"dentist here" chess'), '"dentist here" AND "chess"')

    def test_punctuation_cannot_break_the_syntax(self):
        self.assertEqual(story_search.fts_query('ex-cia tl;dr'), '"ex-cia" AND "tl;dr"')
        self.assertEqual(story_search.fts_query('"unbalanced quote'), '"unbalanced" AND "quote"')
        self.assertEqual(story_search.fts_query(';;; *'), '')

    def test_operators(self):
        self.assertEqual(story_search.fts_query('NOT cats OR'), '')
        self.assertEqual(story_search.fts_query('cats OR dogs'), '("cats" OR "dogs")')
        self.assertEqual(story_search.fts_query('cats -dogs'), '("cats") NOT ("dogs")')

    def test_rrf_rewards_items_in_both_lists(self):
        self.assertEqual(story_search.rrf([1, 2, 3], [3, 4]), [3, 1, 2, 4])


class SearchTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.comments = make_comments_db(os.path.join(self.tmp, 'comments.db'))
        self.dir = os.path.join(self.tmp, 'search')
        self.con = story_search.connect(self.dir)
        self.added = story_search.add_stories(self.con, self.comments)

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.tmp)

    def search(self, query, **kw):
        return story_search.search(query, search_dir=self.dir, **kw)

    def test_only_stories_are_indexed(self):
        self.assertEqual(self.added, 3)
        self.assertEqual(sorted(r['name'] for r in self.search('chess')), ['t1_c1'])

    def test_result_has_the_template_fields(self):
        result = self.search('lighthouse')[0]
        self.assertEqual(result['url'], 'https://www.reddit.com/comments/def/x/c2')
        self.assertEqual(result['subreddit'], 'AskReddit')
        self.assertEqual(result['parent'], 'def')
        self.assertEqual(result['score'], 80)
        self.assertEqual(result['created'], '1764547300')

    def test_stemming_and_phrases(self):
        self.assertEqual(len(self.search('grandfathers')), 1)
        self.assertEqual(len(self.search('"dentist here"')), 1)
        self.assertEqual(self.search('"here dentist"'), [])

    def test_bad_input_returns_nothing_instead_of_failing(self):
        for query in ['', '   ', ';;;', '"', 'NOT', 'cats NOT OR dogs', None]:
            with self.subTest(query=query):
                self.assertEqual(self.search(query), [])
        self.assertEqual(len(self.search('ex-cia')), 1)

    def test_missing_index_returns_nothing(self):
        self.assertEqual(story_search.search('chess', search_dir=os.path.join(self.tmp, 'nope')), [])

    def test_adding_again_only_adds_new_stories(self):
        self.assertEqual(story_search.add_stories(self.con, self.comments), 0)
        make_comments_db(self.comments, [('c6', 't3_pqr', 70, 'A new month brings a lighthouse ghost.',
                                          'Ghosts', 't3_pqr', 1767225600, 0.9, 3)])
        self.assertEqual(story_search.add_stories(self.con, self.comments), 1)
        self.assertEqual(len(self.search('lighthouse')), 2)

    def test_sample_csv_rows_all_count_as_stories(self):
        sample = os.path.join(os.path.dirname(__file__), '..', 'sample_data', 'sample_comments.csv')
        db = story_search.csv_to_comments_db(sample, os.path.join(self.tmp, 'csv.db'))
        con = story_search.connect(os.path.join(self.tmp, 'csv_search'))
        self.assertEqual(story_search.add_stories(con, db), 200)
        con.close()

    def rowids(self):
        return dict(self.con.execute('SELECT id, rowid FROM stories'))

    def names(self, results):
        return [r['name'] for r in results]

    def test_unquoted_queries_fuse_vector_hits(self):
        rowid = self.rowids()
        with mock.patch.object(story_search, 'vector_ids', return_value=[rowid['c2'], rowid['c1']]):
            self.assertEqual(self.names(self.search('chess')), ['t1_c1', 't1_c2'])
            self.assertEqual(self.names(self.search('a sad sailor')), ['t1_c2', 't1_c1'])

    def test_plain_queries_are_embedded_as_typed(self):
        with mock.patch.object(story_search, 'vector_ids', return_value=[]) as vector_ids:
            self.search('🐶 my dog saved me')
            self.assertEqual(vector_ids.call_args[0][2], '🐶 my dog saved me')
            self.search('"dentist here" chess -kids')
            self.assertEqual(vector_ids.call_args[0][2], 'dentist here chess')

    def test_phrases_stay_exact_but_use_vector_ranking(self):
        rowid = self.rowids()
        # c1 has no "dentist here", so the vector hit is dropped
        with mock.patch.object(story_search, 'vector_ids', return_value=[rowid['c1'], rowid['c3']]):
            results = self.search('"dentist here"')
            self.assertEqual(self.names(results), ['t1_c3'])
            self.assertFalse(results.related)
            # phrase + word: c3 has the phrase but not "lighthouse"; it still counts
            self.assertEqual(self.names(self.search('"dentist here" lighthouse')), ['t1_c3'])

    def test_phrase_plus_word_ranks_stories_with_both_first(self):
        make_comments_db(self.comments, [('c7', 't3_xyz', 70, 'Dentist here, and my weird patient was a lighthouse keeper.',
                                          'AskReddit', 't3_xyz', 1764547700, 0.9, 3)])
        story_search.add_stories(self.con, self.comments)
        with mock.patch.object(story_search, 'vector_ids', return_value=[]):
            self.assertEqual(self.names(self.search('"dentist here" lighthouse')), ['t1_c7', 't1_c3'])

    def test_no_exact_match_shows_related_stories(self):
        rowid = self.rowids()
        with mock.patch.object(story_search, 'vector_ids', return_value=[rowid['c2'], rowid['c1']]):
            results = self.search('"a sad sailor"')
            self.assertEqual(self.names(results), ['t1_c2', 't1_c1'])
            self.assertTrue(results.related)
            results = self.search('"a sad sailor" -lighthouse')
            self.assertEqual(self.names(results), ['t1_c1'])
            self.assertTrue(results.related)
        with mock.patch.object(story_search, 'vector_ids', return_value=[]):
            results = self.search('"a sad sailor"')
            self.assertEqual(results, [])
            self.assertFalse(results.related)

    def test_exclusions_apply_to_both_lists(self):
        rowid = self.rowids()
        with mock.patch.object(story_search, 'vector_ids', return_value=[rowid['c2'], rowid['c3']]):
            self.assertEqual(self.names(self.search('chess')), ['t1_c1', 't1_c2', 't1_c3'])
            self.assertEqual(self.names(self.search('chess -lighthouse')), ['t1_c1', 't1_c3'])
            self.assertEqual(self.names(self.search('chess NOT "dentist here"')), ['t1_c1', 't1_c2'])
            self.assertEqual(self.names(self.search('chess -grandfather')), ['t1_c2', 't1_c3'])
            self.assertEqual(self.search('-chess'), [])      # nothing left to search for

    def test_or_groups(self):
        with mock.patch.object(story_search, 'vector_ids', return_value=[]):
            self.assertEqual(sorted(self.names(self.search('chess OR lighthouse'))), ['t1_c1', 't1_c2'])
            self.assertEqual(self.search('chess lighthouse'), [])

    def test_vector_failure_falls_back_to_keywords(self):
        with mock.patch.object(story_search, 'vector_ids', side_effect=RuntimeError('boom')):
            self.assertEqual(len(self.search('chess')), 1)

    def test_vectors_are_merged_once(self):
        vectors = np.eye(3, story_search.DIMENSIONS, dtype=np.float32)
        self.assertEqual(len(story_search.missing_vectors(self.con, self.dir)), 3)
        self.assertEqual(story_search.merge_vectors(self.dir, ['c1', 'c2'], vectors[:2]), 2)
        self.assertEqual(story_search.merge_vectors(self.dir, ['c2', 'c3'], vectors[1:]), 1)
        ids, matrix = story_search.read_vectors(story_search.vectors_path(self.dir))
        self.assertEqual(ids, ['c1', 'c2', 'c3'])
        self.assertEqual(matrix.shape, (3, story_search.DIMENSIONS))
        self.assertEqual(story_search.missing_vectors(self.con, self.dir), [])


try:
    import jammi  # noqa: F401
    HAVE_JAMMI = True
except ImportError:
    HAVE_JAMMI = False


@unittest.skipUnless(HAVE_JAMMI, 'jammi-ai is not installed')
class VectorStoreTest(unittest.TestCase):
    "Imports vectors into a real Jammi store; uses fixed vectors so no model is downloaded"

    def test_store_finds_the_nearest_story(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        search_dir = os.path.join(tmp, 'search')
        con = story_search.connect(search_dir)
        story_search.add_stories(con, make_comments_db(os.path.join(tmp, 'comments.db')))
        vectors = np.eye(3, story_search.DIMENSIONS, dtype=np.float32)
        story_search.merge_vectors(search_dir, ['c1', 'c2', 'c3'], vectors)
        self.assertEqual(story_search.build_vector_store(search_dir), 3)
        db = story_search._vector_db(search_dir)
        hits = db.search(story_search.SOURCE, query=vectors[1].tolist(), k=1, select=['id'])
        self.assertEqual(hits.column('id').to_pylist(), ['c2'])
        con.close()


if __name__ == '__main__':
    unittest.main()
