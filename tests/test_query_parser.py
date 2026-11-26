"""
Unit tests for query_parser.py, the search box syntax (#46).

Run from the repo root:
    python -m unittest discover tests
"""

import unittest

from query_parser import Term, parse_query


def shape(text):
    "A query as (clauses, excluded) with each term as text, quoted ones in quotes"
    def show(t):
        return '"%s"' % t.text if t.quoted else t.text
    q = parse_query(text)
    return [[show(t) for t in clause] for clause in q.clauses], [show(t) for t in q.excluded]


class SyntaxTest(unittest.TestCase):

    def test_words(self):
        self.assertEqual(shape('worst job interview'), ([['worst'], ['job'], ['interview']], []))

    def test_phrases(self):
        self.assertEqual(shape('"night shift" nurse'), ([['"night shift"'], ['nurse']], []))
        self.assertEqual(shape('"  extra   spaces "'), ([['"extra spaces"']], []))
        self.assertEqual(shape('abc"def"'), ([['abc'], ['"def"']], []))

    def test_minus_excludes(self):
        self.assertEqual(shape('dentist -kids'), ([['dentist']], ['kids']))
        self.assertEqual(shape('vodka -"in soviet russia"'), ([['vodka']], ['"in soviet russia"']))
        self.assertEqual(shape('dentist --kids'), ([['dentist']], ['kids']))

    def test_hyphenated_words_are_not_exclusions(self):
        self.assertEqual(shape('ex-cia ex-boyfriend'), ([['ex-cia'], ['ex-boyfriend']], []))

    def test_not_excludes(self):
        self.assertEqual(shape('chess NOT tournament'), ([['chess']], ['tournament']))
        self.assertEqual(shape('chess NOT "world cup"'), ([['chess']], ['"world cup"']))
        self.assertEqual(shape('chess not tournament'), ([['chess'], ['not'], ['tournament']], []))

    def test_or_groups(self):
        self.assertEqual(shape('dog OR cat rescue'), ([['dog', 'cat'], ['rescue']], []))
        self.assertEqual(shape('a OR b OR "c d"'), ([['a', 'b', '"c d"']], []))
        self.assertEqual(shape('dog or cat'), ([['dog'], ['or'], ['cat']], []))

    def test_and_is_accepted(self):
        self.assertEqual(shape('dog AND cat'), ([['dog'], ['cat']], []))

    def test_properties(self):
        q = parse_query('"first job" boss -retail')
        self.assertTrue(q.has_phrase)
        self.assertEqual(q.phrases, ['first job'])
        self.assertEqual(q.words, ['boss'])
        self.assertEqual(q.excluded, [Term('retail')])
        self.assertFalse(q.plain)
        self.assertTrue(parse_query('worst job interview').plain)
        self.assertFalse(parse_query('dog OR cat').plain)

    def test_fts(self):
        self.assertEqual(parse_query('"first job" boss -retail').fts(),
                         '("first job" AND "boss") NOT ("retail")')
        self.assertEqual(parse_query('"first job" boss -retail').fts_required(),
                         '("first job") NOT ("retail")')
        self.assertEqual(parse_query('dog OR cat rescue').fts(), '("dog" OR "cat") AND "rescue"')
        self.assertEqual(parse_query('a -b -"c d"').fts_excluded(), '"b" OR "c d"')

    def test_vector_text(self):
        self.assertEqual(parse_query('  worst   job ever ').vector_text(), 'worst job ever')
        self.assertEqual(parse_query('🐶 my dog').vector_text(), '🐶 my dog')
        self.assertEqual(parse_query('"night shift" nurse -kids').vector_text(), 'night shift nurse')
        self.assertEqual(parse_query('dog OR cat').vector_text(), 'dog cat')


class AwkwardInputTest(unittest.TestCase):
    "Garbage never raises: it becomes an empty query or plain words"

    def test_empty_queries(self):
        for text in ['', '   ', '"', '""', '" "', '*', ';;;', 'NOT', 'AND OR', 'OR', '-', '- -',
                     '"*"', '🐶', '___', '-kids', 'NOT kids', None, 42]:
            with self.subTest(text=text):
                q = parse_query(text)
                self.assertTrue(q.empty)
                self.assertEqual(q.fts(), '')

    def test_unclosed_quote_is_plain_words(self):
        self.assertEqual(shape('"unbalanced quote'), ([['unbalanced'], ['quote']], []))
        self.assertEqual(shape('"closed" "open'), ([['"closed"'], ['open']], []))
        self.assertEqual(shape('-"open phrase'), ([['open'], ['phrase']], []))

    def test_dangling_and_doubled_operators(self):
        self.assertEqual(shape('OR cats'), ([['cats']], []))
        self.assertEqual(shape('cats OR'), ([['cats']], []))
        self.assertEqual(shape('cats NOT'), ([['cats']], []))
        self.assertEqual(shape('cats NOT OR dogs'), ([['cats', 'dogs']], []))
        self.assertEqual(shape('cats OR NOT dogs'), ([['cats']], ['dogs']))
        self.assertEqual(shape('cats OR -dogs'), ([['cats']], ['dogs']))

    def test_punctuation_is_kept_inside_terms(self):
        self.assertEqual(shape('tl;dr C++'), ([['tl;dr'], ['C++']], []))
        self.assertEqual(parse_query('tl;dr').fts(), '"tl;dr"')
        self.assertEqual(parse_query('say "hi" -"x"').fts(), '("say" AND "hi") NOT ("x")')

    def test_duplicates_are_dropped(self):
        self.assertEqual(shape('dog dog OR dog -cat -cat'), ([['dog']], ['cat']))

    def test_long_paste(self):
        text = ' '.join(['word%d' % i for i in range(300)]) + ' "unclosed'
        q = parse_query(text)
        self.assertEqual(len(q.clauses), 301)
        self.assertTrue(q.plain)


if __name__ == '__main__':
    unittest.main()
