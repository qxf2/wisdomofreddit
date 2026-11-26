"""
Parse what people type into the search box (#46).

Supported syntax:
    words             all of them, ranked (how strictly is up to story_search)
    "a phrase"        must appear exactly, in this order
    a OR b            either one; OR must be upper case
    -word, -"phrase"  leave out stories that contain it
    NOT word          same as -word; NOT must be upper case
    AND               allowed, but words are ANDed anyway

Garbage never raises. Anything without a letter or digit is dropped, an
unclosed quote counts as plain words, and operators with nothing to act on
are ignored. A query that is only operators or punctuation parses as empty.
"""

import re
from dataclasses import dataclass, field

# Dropped from the keyword (FTS5) side of a query, never from inside a quoted
# phrase or from the text sent to vector search (#47). Common English function
# words plus filler people type when they describe a story.
STOP_WORDS = frozenset("""
a about above after again against all am an and any are as at be because been
before being below between both but by can could did do does doing down during
each few for from further had has have having he her here hers herself him
himself his how i i'd i'll i'm i've if in into is it it's its itself just me
more most my myself no nor not of off on once only or other our ours ourselves
out over own same she should so some such than that that's the their theirs
them themselves then there these they this those through to too under until up
very was we were what when where which while who whom why will with would you
your yours yourself yourselves
ever really thing things stuff like story stories time times got get getting
someone something somebody anyone one ones also even still
""".split())

_TOKEN = re.compile(r'(-?)"([^"]*)("?)|([^\s"]+)')
_OPERATORS = {'AND', 'OR', 'NOT'}


def _has_text(text):
    "Does the text have a letter or digit? (FTS5 would find no tokens otherwise)"
    return re.search(r'[^\W_]', text) is not None


@dataclass(frozen=True)
class Term:
    text: str
    quoted: bool = False

    def fts(self):
        "The term as an FTS5 string. Quoting every term keeps punctuation from breaking the syntax."
        return '"%s"' % self.text.replace('"', '')


@dataclass
class Query:
    clauses: list = field(default_factory=list)    # AND of clauses; each clause is an OR of Terms
    excluded: list = field(default_factory=list)   # Terms a result must not contain
    text: str = ''                                 # what was typed
    operators: bool = False                        # did it use AND, OR or NOT?

    @property
    def empty(self):
        return not self.clauses

    @property
    def has_phrase(self):
        return any(t.quoted for clause in self.clauses for t in clause)

    @property
    def phrases(self):
        return [t.text for clause in self.clauses for t in clause if t.quoted]

    @property
    def words(self):
        return [t.text for clause in self.clauses for t in clause if not t.quoted]

    def required_clauses(self):
        "The clauses with a quoted phrase: every result must match these"
        return [c for c in self.clauses if any(t.quoted for t in c)]

    def without_stop_words(self):
        """The query for the keyword side: unquoted stop words dropped, phrases
        and exclusions kept. Returns the query unchanged if nothing would be left."""
        clauses = []
        for clause in self.clauses:
            kept = [t for t in clause if t.quoted or t.text.lower() not in STOP_WORDS]
            if kept:
                clauses.append(kept)
        if not clauses or len(clauses) == len(self.clauses) and all(
                len(a) == len(b) for a, b in zip(clauses, self.clauses)):
            return self
        return Query(clauses=clauses, excluded=list(self.excluded), text=self.text,
                     operators=self.operators)

    def fts_any(self):
        "FTS5 query matching any searched term, minus the exclusions"
        terms = [t for clause in self.clauses for t in clause]
        return self.fts([terms]) if terms else ''

    def fts(self, clauses=None):
        """FTS5 query for the given clauses (default all) minus the exclusions.
        Empty string when there is nothing to match."""
        clauses = self.clauses if clauses is None else clauses
        if not clauses:
            return ''
        parts = []
        for clause in clauses:
            if len(clause) == 1:
                parts.append(clause[0].fts())
            else:
                parts.append('(%s)' % ' OR '.join(t.fts() for t in clause))
        match = ' AND '.join(parts)
        if self.excluded:
            if len(parts) > 1:
                match = '(%s)' % match
            match = '%s NOT (%s)' % (match, self.fts_excluded())
        return match

    def fts_required(self):
        "FTS5 query for just the phrase clauses, minus the exclusions"
        return self.fts(self.required_clauses())

    def fts_excluded(self):
        "FTS5 query matching any excluded term"
        return ' OR '.join(t.fts() for t in self.excluded)

    @property
    def plain(self):
        "Only words: no quotes, exclusions or operators"
        return not (self.has_phrase or self.excluded or self.operators)

    def vector_text(self):
        """The text to embed. Plain queries are embedded as typed (so an emoji or
        a sentence keeps its meaning); otherwise every searched term, without
        quotes, operators or exclusions."""
        if self.plain and not self.empty:
            return ' '.join(self.text.split())
        return ' '.join(t.text for clause in self.clauses for t in clause)


def _tokens(text):
    "Yield ('op', name), ('term', Term) or ('exclude', Term)"
    for minus, inner, closed, word in _TOKEN.findall(text):
        if not word and not closed:
            # an unclosed quote: its words are plain words
            for w in inner.split():
                if _has_text(w):
                    yield 'term', Term(w)
            continue
        if not word:
            if _has_text(inner):
                yield ('exclude' if minus else 'term'), Term(' '.join(inner.split()), quoted=True)
            continue
        if word in _OPERATORS:
            yield 'op', word
        elif word.startswith('-') and _has_text(word):
            yield 'exclude', Term(word.lstrip('-'))
        elif _has_text(word):
            yield 'term', Term(word)


def parse_query(text):
    "Parse search box input into a Query. Never raises."
    query = Query()
    if not isinstance(text, str):
        return query
    query.text = text
    pending_or = pending_not = False
    for kind, value in _tokens(text):
        if kind == 'op':
            query.operators = True
            if value == 'OR':
                pending_or, pending_not = bool(query.clauses), False
            elif value == 'NOT':
                pending_or, pending_not = False, True
            continue
        if kind == 'exclude' or pending_not:
            if value not in query.excluded:
                query.excluded.append(value)
        elif pending_or:
            if value not in query.clauses[-1]:
                query.clauses[-1].append(value)
        elif [value] not in query.clauses:
            query.clauses.append([value])
        pending_or = pending_not = False
    return query
