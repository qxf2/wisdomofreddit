"""
Search quality eval (#45): run a fixed set of queries against a search index
and report, per query type, how many of the top 10 results are relevant,
queries with no results, errors, quoted-phrase and exclusion checks, and
latency.

Relevance comes from labels saved in tests/search_eval/labels.jsonl, one
judgment per line:
    {"query": "...", "id": "<story id>", "judge": "jev", "relevant": true, "p": 0.91}
A result can have labels from several judges. By default a human label wins
over a Jev label; other judges (like "claude", the labels from spike #31) are
not counted, only compared. Results nobody has labelled are listed so they
can be judged, and are not counted as wrong.

Usage:
    python eval_search.py data/search
    python eval_search.py data/search --label-jev          # Jev labels what is unjudged
    python eval_search.py data/search --save after.json --compare before.json
    python eval_search.py data/search --per-query --unjudged todo.jsonl

Latency: the whole query set runs once to warm up (loads the model and the
caches), then --repeat timed passes. Each query's time is its median over the
passes. With about 10 queries per type, a type's p95 is close to its slowest
query.
"""

import argparse
import json
import logging
import os
import re
import sqlite3
import statistics
import time

import story_search

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
EVAL_DIR = os.path.join(CURRENT_DIR, 'tests', 'search_eval')
QUERIES = os.path.join(EVAL_DIR, 'queries.txt')
LABELS = os.path.join(EVAL_DIR, 'labels.jsonl')
TYPES = ['keyword', 'phrase', 'writer', 'mixed', 'awkward']
TOP = 10
JEV_THRESHOLD = 0.5
JEV_MAX_CHARS = 4000


# ---------------------------------------------------------------- inputs

def read_queries(path=QUERIES):
    "Return [(type, query)] from a queries file. Text after a second tab is a note."
    queries = []
    with open(path, encoding='utf-8') as fp:
        for line in fp:
            line = line.rstrip('\n')
            if not line.strip() or line.startswith('#'):
                continue
            kind, query = line.split('\t')[:2]
            queries.append((kind, query))
    return queries


def read_labels(path=LABELS):
    "Return {(query, id): {judge: label dict}}"
    labels = {}
    if os.path.exists(path):
        with open(path, encoding='utf-8') as fp:
            for line in fp:
                if line.strip():
                    label = json.loads(line)
                    labels.setdefault((label['query'], label['id']), {})[label['judge']] = label
    return labels


def write_labels(labels, path=LABELS):
    "Write all labels sorted, so the file diffs cleanly"
    rows = [label for judges in labels.values() for label in judges.values()]
    rows.sort(key=lambda r: (r['query'], r['id'], r['judge']))
    with open(path, 'w', encoding='utf-8') as fp:
        for row in rows:
            fp.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n')


def judgment(labels, query, story_id, judges):
    "True/False from the first judge in the list that labelled this result, or None"
    found = labels.get((query, story_id), {})
    for judge in judges:
        if judge in found:
            return found[judge]['relevant']
    return None


# ---------------------------------------------------------------- checks

_PHRASE = re.compile(r'"([^"]*)"')
_EXCLUDE = re.compile(r'(?:^|\s)-(\w[\w\'-]*)|\bNOT\s+(\w[\w\'-]*)')


def constraints(query):
    """The phrases a result must contain and the words it must not, read from
    the query on their own (not with the parser under test)"""
    phrases = [p for p in _PHRASE.findall(query) if re.search(r'\w', p)]
    unquoted = _PHRASE.sub(' ', query)
    excluded = [a or b for a, b in _EXCLUDE.findall(unquoted)]
    return phrases, excluded


def matches(con, story_id, text):
    "Does the story contain this word or phrase, the way FTS5 tokenizes it?"
    match = '"%s"' % text.replace('"', '')
    sql = ('SELECT 1 FROM stories_fts WHERE stories_fts MATCH ? '
           'AND rowid = (SELECT rowid FROM stories WHERE id = ?)')
    return con.execute(sql, (match, story_id)).fetchone() is not None


class ErrorCounter(logging.Handler):
    "Counts errors story_search logs, such as a vector search that fell back to keywords"

    def __init__(self):
        super().__init__(logging.ERROR)
        self.count = 0

    def emit(self, record):
        self.count += 1


# ---------------------------------------------------------------- running

def story_id(result):
    return result['url'].rsplit('/', 1)[-1]


def run_queries(queries, search_dir, repeat=1, top=TOP):
    """Run every query: one warm-up pass, then `repeat` timed passes.
    Returns one dict per query with ids, errors and milliseconds."""
    counter = ErrorCounter()
    story_search.logger.addHandler(counter)
    try:
        for _, query in queries:
            try:
                story_search.search(query, limit=top, search_dir=search_dir)
            except Exception:
                pass
        runs = []
        for kind, query in queries:
            times, ids, error = [], [], None
            before = counter.count
            for _ in range(max(repeat, 1)):
                start = time.perf_counter()
                try:
                    results = story_search.search(query, limit=top, search_dir=search_dir)
                    ids = [story_id(r) for r in results]
                except Exception as exc:
                    error = '%s: %s' % (type(exc).__name__, exc)
                times.append((time.perf_counter() - start) * 1000)
            if error is None and counter.count > before:
                error = 'logged %d error(s)' % (counter.count - before)
            runs.append({'type': kind, 'query': query, 'ids': ids, 'error': error,
                         'ms': statistics.median(times)})
        return runs
    finally:
        story_search.logger.removeHandler(counter)


def check_runs(runs, search_dir, labels, judges):
    "Add relevance and phrase/exclusion checks to each run"
    con = sqlite3.connect(os.path.join(search_dir, 'search.db'))
    try:
        for run in runs:
            phrases, excluded = constraints(run['query'])
            verdicts = [judgment(labels, run['query'], i, judges) for i in run['ids']]
            run['relevant'] = sum(v is True for v in verdicts)
            run['judged'] = sum(v is not None for v in verdicts)
            run['unjudged'] = [i for i, v in zip(run['ids'], verdicts) if v is None]
            run['phrase_misses'] = sum(1 for i in run['ids']
                                       if not all(matches(con, i, p) for p in phrases))
            run['excluded_hits'] = sum(1 for i in run['ids']
                                       if any(matches(con, i, w) for w in excluded))
    finally:
        con.close()
    return runs


def p95(values):
    "Nearest-rank 95th percentile"
    values = sorted(values)
    return values[max(0, -(-95 * len(values) // 100) - 1)] if values else 0.0


def summarize(runs, top=TOP):
    "Per-type and overall totals"
    rows = {}
    for kind in TYPES + sorted({r['type'] for r in runs} - set(TYPES)) + ['all']:
        group = [r for r in runs if kind == 'all' or r['type'] == kind]
        if not group:
            continue
        ms = [r['ms'] for r in group]
        judged = sum(r['judged'] for r in group)
        relevant = sum(r['relevant'] for r in group)
        rows[kind] = {
            'queries': len(group),
            'relevant': relevant,
            'max': top * len(group),
            'judged': judged,
            'precision': relevant / judged if judged else None,
            'unjudged': sum(len(r['unjudged']) for r in group),
            'zero': sum(1 for r in group if not r['ids'] and not r['error']),
            'errors': sum(1 for r in group if r['error']),
            'phrase_misses': sum(r['phrase_misses'] for r in group),
            'excluded_hits': sum(r['excluded_hits'] for r in group),
            'median_ms': statistics.median(ms),
            'p95_ms': p95(ms),
        }
    return rows


# ---------------------------------------------------------------- output

COLUMNS = [('type', 8), ('queries', 7), ('rel@10', 9), ('prec', 5), ('unjudged', 8),
           ('zero', 4), ('errors', 6), ('phr.miss', 8), ('excl.hit', 8),
           ('med ms', 7), ('p95 ms', 7)]


def format_row(kind, row):
    precision = '-' if row['precision'] is None else '%.2f' % row['precision']
    cells = [kind, row['queries'], '%d/%d' % (row['relevant'], row['max']), precision,
             row['unjudged'], row['zero'], row['errors'], row['phrase_misses'],
             row['excluded_hits'], '%.1f' % row['median_ms'], '%.1f' % row['p95_ms']]
    return '  '.join(str(c).rjust(w) if i else str(c).ljust(w)
                     for i, (c, (_, w)) in enumerate(zip(cells, COLUMNS)))


def format_table(summary):
    header = '  '.join(n.rjust(w) if i else n.ljust(w) for i, (n, w) in enumerate(COLUMNS))
    lines = [header, '-' * len(header)]
    lines += [format_row(kind, row) for kind, row in summary.items()]
    return '\n'.join(lines)


def format_compare(summary, before):
    "Relevant, zero-result and latency changes against a saved report"
    lines = ['vs %s:' % before.get('_path', 'before')]
    for kind, row in summary.items():
        old = before['summary'].get(kind)
        if not old:
            continue
        lines.append('  %-8s rel@10 %+d (%d -> %d)  zero %+d  errors %+d  phr.miss %+d  '
                     'excl.hit %+d  p95 %+.1f ms'
                     % (kind, row['relevant'] - old['relevant'], old['relevant'],
                        row['relevant'], row['zero'] - old['zero'],
                        row['errors'] - old['errors'],
                        row['phrase_misses'] - old['phrase_misses'],
                        row['excluded_hits'] - old['excluded_hits'],
                        row['p95_ms'] - old['p95_ms']))
    return '\n'.join(lines)


def format_per_query(runs):
    lines = []
    for r in runs:
        status = r['error'] or ('%d results' % len(r['ids']))
        lines.append('%-8s %3d/%-3d %7.1f ms  %-12s %s'
                     % (r['type'], r['relevant'], r['judged'], r['ms'], status, r['query']))
    return '\n'.join(lines)


def bodies(search_dir, ids):
    con = sqlite3.connect(os.path.join(search_dir, 'search.db'))
    try:
        found = {}
        ids = list(ids)
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            found.update(con.execute('SELECT id, body FROM stories WHERE id IN (%s)'
                                     % ','.join('?' * len(chunk)), chunk))
        return found
    finally:
        con.close()


def unjudged_pairs(runs):
    seen, pairs = set(), []
    for r in runs:
        for i in r['unjudged']:
            if (r['query'], i) not in seen:
                seen.add((r['query'], i))
                pairs.append((r['query'], i))
    return pairs


# ---------------------------------------------------------------- Jev labels

def jev_question():
    from typesafe_sdk import Noul
    return {'relevant': Noul(
        instructions='Someone typed `query` into a search engine for real-life stories told in '
                     'Reddit comments. Is `story` a result they would want to read?',
        criteria={
            'true': 'The story is about what the query asks for: its person, topic, situation, or '
                    'the kind of experience it describes. Text in "double quotes" is an exact '
                    'phrase the searcher cares about. A word after a minus sign or NOT is '
                    'something they do not want.',
            'false': 'The story only mentions a query word in passing, is about something else, '
                     'or is about what the searcher excluded',
        })}


def label_with_jev(pairs, search_dir, labels, workers=16):
    "Ask Jev about each (query, id) pair and add the answers to labels. Returns how many."
    from concurrent.futures import ThreadPoolExecutor
    from dotenv import load_dotenv
    from typesafe_sdk import TypeSafeClient
    load_dotenv(os.path.join(CURRENT_DIR, '.env'))
    texts = bodies(search_dir, (i for _, i in pairs))
    questions = jev_question()

    def ask(pair):
        query, story = pair
        try:
            response = client.system_one(
                state={'query': query, 'story': texts[story][:JEV_MAX_CHARS]},
                questions=questions)
        except Exception as exc:
            print('Jev failed on %r %s: %s' % (query, story, exc))
            return None
        p = response.answers['relevant'].noul
        return {'query': query, 'id': story, 'judge': 'jev', 'relevant': p >= JEV_THRESHOLD,
                'p': round(p, 3), 'model': response.model}

    added = 0
    with TypeSafeClient() as client, ThreadPoolExecutor(workers) as pool:
        for label in pool.map(ask, [p for p in pairs if p[1] in texts]):
            if label:
                labels.setdefault((label['query'], label['id']), {})['jev'] = label
                added += 1
    return added


def agreement(labels, a, b):
    "How often judges a and b agree where both labelled the same result"
    both = [j for j in labels.values() if a in j and b in j]
    same = sum(j[a]['relevant'] == j[b]['relevant'] for j in both)
    return same, len(both)


# ---------------------------------------------------------------- main

def evaluate(search_dir, queries_path=QUERIES, labels_path=LABELS, judges=('human', 'jev'),
             repeat=1, label_jev=False, top=TOP):
    "Run the eval. Returns (runs, summary, labels)."
    queries = read_queries(queries_path)
    labels = read_labels(labels_path)
    runs = run_queries(queries, search_dir, repeat, top)
    check_runs(runs, search_dir, labels, judges)
    if label_jev:
        pairs = unjudged_pairs(runs)
        if pairs:
            print('Asking Jev about %d unjudged results...' % len(pairs))
            print('Added %d Jev labels' % label_with_jev(pairs, search_dir, labels))
            write_labels(labels, labels_path)
            check_runs(runs, search_dir, labels, judges)
    return runs, summarize(runs, top), labels


def main():
    parser = argparse.ArgumentParser(description='Search quality eval (#45)')
    parser.add_argument('search_dir', nargs='?', default=story_search.DEFAULT_DIR,
                        help='Index folder (default data/search)')
    parser.add_argument('--queries', default=QUERIES)
    parser.add_argument('--labels', default=LABELS)
    parser.add_argument('--judges', default='human,jev',
                        help='Judges whose labels count, first one wins (default human,jev)')
    parser.add_argument('--repeat', type=int, default=3, help='Timed passes (default 3)')
    parser.add_argument('--label-jev', action='store_true',
                        help='Ask Jev to label unjudged results and save them to --labels')
    parser.add_argument('--per-query', action='store_true', help='Also print one line per query')
    parser.add_argument('--unjudged', metavar='FILE',
                        help='Write unjudged results (query, id, body) as JSON lines')
    parser.add_argument('--save', metavar='FILE', help='Save the report as JSON')
    parser.add_argument('--compare', metavar='FILE', help='Show changes against a saved report')
    args = parser.parse_args()

    if not os.path.exists(os.path.join(args.search_dir, 'search.db')):
        parser.error('no search.db in %s' % args.search_dir)
    judges = [j.strip() for j in args.judges.split(',') if j.strip()]
    runs, summary, labels = evaluate(args.search_dir, args.queries, args.labels, judges,
                                     args.repeat, args.label_jev)

    print('Search eval: %s, %d queries, judges %s, top %d'
          % (args.search_dir, len(runs), '>'.join(judges), TOP))
    print(format_table(summary))
    if args.per_query:
        print()
        print(format_per_query(runs))
    for other in ('claude',):
        same, total = agreement(labels, 'jev', other)
        if total:
            print('\nJev agrees with %s on %d of %d results both labelled (%.0f%%)'
                  % (other, same, total, 100.0 * same / total))
    if args.compare:
        with open(args.compare, encoding='utf-8') as fp:
            before = json.load(fp)
        before['_path'] = args.compare
        print()
        print(format_compare(summary, before))

    pairs = unjudged_pairs(runs)
    if pairs:
        texts = bodies(args.search_dir, (i for _, i in pairs))
        print('\n%d results are not labelled yet (not counted as wrong):' % len(pairs))
        for query, i in pairs[:30]:
            print('  %-30s %s  %s' % (query[:30], i, ' '.join(texts.get(i, '').split())[:80]))
        if len(pairs) > 30:
            print('  ... %d more (use --unjudged FILE or --label-jev)' % (len(pairs) - 30))
        if args.unjudged:
            with open(args.unjudged, 'w', encoding='utf-8') as fp:
                for query, i in pairs:
                    fp.write(json.dumps({'query': query, 'id': i, 'body': texts.get(i, '')},
                                        ensure_ascii=False) + '\n')
    if args.save:
        with open(args.save, 'w', encoding='utf-8') as fp:
            json.dump({'search_dir': args.search_dir, 'judges': judges, 'summary': summary,
                       'runs': runs}, fp, indent=1, ensure_ascii=False)


if __name__ == '__main__':
    main()
