"""
Story search: SQLite FTS5 for keywords plus Jammi vector search for
natural-language queries. The design comes from spike #31.

Everything lives in one folder (default ./data/search):
  search.db        the stories (p_story >= 0.5, vividness >= 2) and an FTS5 index
  vectors.parquet  one all-MiniLM-L6-v2 vector per story (columns _row_id, vector)
  jammi/           a Jammi vector store over the story ids only, built from vectors.parquet

Build or update it with build_search_index.py. The app calls search().
"""

import logging
import os
import shutil
import sqlite3
import threading

from query_parser import parse_query

MODEL = 'sentence-transformers/all-MiniLM-L6-v2'
DIMENSIONS = 384
MAX_TOKENS = 512        # Jammi's encoder window; sentence-transformers must match
SOURCE = 'stories'
P_STORY_MIN = 0.5       # same as score_stories.STORY_THRESHOLD and MIN_VIVIDNESS;
VIVIDNESS_MIN = 2       # not imported so the app does not need typesafe_sdk
CANDIDATES = 50         # hits taken from each engine before fusing
RRF_K = 60
FILTER_FACTOR = 4      # extra vector hits to fetch when some will be filtered out

DEFAULT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'search')

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS stories (
    rowid INTEGER PRIMARY KEY,
    id TEXT UNIQUE NOT NULL,
    link_id TEXT,
    score INTEGER,
    body TEXT,
    name TEXT,
    created_utc INTEGER,
    subreddit TEXT,
    parent_id TEXT,
    gilded INTEGER,
    month TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS stories_fts USING fts5(
    body, content='stories', content_rowid='rowid', tokenize='porter unicode61');
"""

COLUMNS = ['id', 'link_id', 'score', 'body', 'name', 'created_utc', 'subreddit',
           'parent_id', 'gilded', 'month']


# ---------------------------------------------------------------- building

def connect(search_dir):
    "Open search.db, creating the tables if needed"
    os.makedirs(search_dir, exist_ok=True)
    con = sqlite3.connect(os.path.join(search_dir, 'search.db'))
    con.executescript(SCHEMA)
    return con


def add_stories(con, comments_db):
    "Copy stories from comments.db that are not indexed yet. Returns how many were added."
    con.execute('ATTACH DATABASE ? AS src', (comments_db,))
    try:
        last = con.execute('SELECT COALESCE(MAX(rowid), 0) FROM stories').fetchone()[0]
        cols = ', '.join('c.' + c for c in COLUMNS)
        con.execute(f"""
            INSERT INTO stories ({', '.join(COLUMNS)})
            SELECT {cols} FROM src.comments c JOIN src.story_scores s ON s.id = c.id
            WHERE s.p_story >= ? AND s.vividness >= ?
              AND c.id NOT IN (SELECT id FROM stories)
            ORDER BY c.created_utc""", (P_STORY_MIN, VIVIDNESS_MIN))
        con.execute('INSERT INTO stories_fts(rowid, body) '
                    'SELECT rowid, body FROM stories WHERE rowid > ?', (last,))
        added = con.execute('SELECT COUNT(*) FROM stories WHERE rowid > ?', (last,)).fetchone()[0]
        con.commit()
    finally:
        con.execute('DETACH DATABASE src')
    return added


def csv_to_comments_db(csv_path, db_path):
    """Load a CSV with the fetch_comments columns (like sample_data/sample_comments.csv)
    into a comments db, scoring every row as a story. Returns db_path."""
    import csv
    con = sqlite3.connect(db_path)
    con.execute('CREATE TABLE comments (%s)' % ', '.join(COLUMNS))
    con.execute('CREATE TABLE story_scores (id TEXT PRIMARY KEY, p_story REAL, vividness REAL)')
    with open(csv_path, newline='', encoding='utf-8') as fp:
        for row in csv.DictReader(fp):
            row['month'] = row.get('month') or ''
            con.execute('INSERT INTO comments VALUES (%s)' % ','.join('?' * len(COLUMNS)),
                        [row.get(c) for c in COLUMNS])
            con.execute('INSERT OR IGNORE INTO story_scores VALUES (?, 1, 5)', (row['id'],))
    con.commit()
    con.close()
    return db_path


def vectors_path(search_dir):
    return os.path.join(search_dir, 'vectors.parquet')


def read_vectors(path):
    "Return (ids, float32 matrix) from a vectors parquet, or empty ones"
    import numpy as np
    import pyarrow.parquet as pq
    if not os.path.exists(path):
        return [], np.zeros((0, DIMENSIONS), dtype=np.float32)
    table = pq.read_table(path)
    key = '_row_id' if '_row_id' in table.column_names else 'id'
    ids = table.column(key).to_pylist()
    flat = table.column('vector').combine_chunks().flatten().to_numpy()
    return ids, flat.reshape(len(ids), DIMENSIONS).astype(np.float32)


def write_vectors(path, ids, matrix):
    import pyarrow as pa
    import pyarrow.parquet as pq
    vectors = pa.FixedSizeListArray.from_arrays(pa.array(matrix.ravel(), pa.float32()), DIMENSIONS)
    tmp = path + '.tmp'
    pq.write_table(pa.table({'_row_id': pa.array(ids, pa.string()), 'vector': vectors}), tmp)
    os.replace(tmp, path)


def merge_vectors(search_dir, ids, matrix):
    "Add vectors for ids that don't have one yet. Returns how many were added."
    import numpy as np
    old_ids, old = read_vectors(vectors_path(search_dir))
    have = set(old_ids)
    keep = [i for i, row_id in enumerate(ids) if row_id not in have]
    if not keep:
        return 0
    write_vectors(vectors_path(search_dir), old_ids + [ids[i] for i in keep],
                  np.vstack([old, matrix[keep]]))
    return len(keep)


def missing_vectors(con, search_dir):
    "Stories in search.db without a vector, as (id, body) pairs"
    have = set(read_vectors(vectors_path(search_dir))[0])
    return [(i, b) for i, b in con.execute('SELECT id, body FROM stories ORDER BY rowid')
            if i not in have]


def encode(texts, batch=2000, progress=print):
    """Encode texts with sentence-transformers if it is installed (use this on
    the GPU box), otherwise with Jammi's own CPU encoder (slow: ~0.5 s a story
    on a laptop). Both give the same vectors at 512 tokens."""
    import numpy as np
    out = np.zeros((len(texts), DIMENSIONS), dtype=np.float32)
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(MODEL)
        model.max_seq_length = MAX_TOKENS
        order = np.argsort([len(t) for t in texts])   # less padding per batch
        for start in range(0, len(texts), batch):
            idx = order[start:start + batch]
            out[idx] = model.encode([texts[i] for i in idx], batch_size=32)
            progress(f'encoded {start + len(idx)}/{len(texts)}')
        return out
    except ImportError:
        pass
    import tempfile
    import jammi
    scratch = tempfile.mkdtemp()
    try:
        db = jammi.connect('file://' + scratch)
        for i, text in enumerate(texts):
            out[i] = db.encode_query(model=MODEL, query=text)
            if (i + 1) % 100 == 0 or i + 1 == len(texts):
                progress(f'encoded {i + 1}/{len(texts)} (Jammi CPU encoder)')
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return out


def build_vector_store(search_dir):
    """Rebuild the Jammi store from vectors.parquet. Jammi's import_embeddings
    replaces the table instead of appending, so a new month means importing all
    vectors again; the vectors themselves are only encoded once."""
    import jammi
    import pyarrow as pa
    import pyarrow.parquet as pq
    ids, _ = read_vectors(vectors_path(search_dir))
    store = os.path.join(search_dir, 'jammi')
    shutil.rmtree(store, ignore_errors=True)
    os.makedirs(store)
    source = os.path.join(store, 'ids.parquet')
    pq.write_table(pa.table({'id': pa.array(ids, pa.string())}), source)
    db = jammi.connect('file://' + os.path.join(store, 'db'))
    db.add_source(SOURCE, url=source, format='parquet')
    db.import_embeddings(source=SOURCE, model=MODEL, vectors_url=vectors_path(search_dir),
                         key='id', text_columns=['body'], dimensions=DIMENSIONS)
    return len(ids)


# ---------------------------------------------------------------- searching

def fts_query(query):
    """Turn user input into a safe FTS5 query (see query_parser). Every word and
    "quoted phrase" is wrapped in double quotes, so punctuation like ex-cia or
    tl;dr can't break the syntax."""
    return parse_query(query).fts()


def _match(con, match, k):
    "Story rowids for an FTS5 query, best first"
    if not match:
        return []
    try:
        return [r[0] for r in con.execute(
            'SELECT rowid FROM stories_fts WHERE stories_fts MATCH ? '
            'ORDER BY bm25(stories_fts) LIMIT ?', (match, k))]
    except sqlite3.OperationalError:
        logger.warning('FTS5 rejected %r', match)
        return []


def _all_matches(con, match):
    """Every rowid that matches an FTS5 query, as a set. One query for the whole
    set is much faster than testing candidates one by one with rowid IN (...)."""
    if not match:
        return set()
    try:
        return {r[0] for r in con.execute(
            'SELECT rowid FROM stories_fts WHERE stories_fts MATCH ?', (match,))}
    except sqlite3.OperationalError:
        logger.warning('FTS5 rejected %r', match)
        return set()


def keyword_ids(con, parsed, k=CANDIDATES):
    """Story rowids from FTS5, best first. With a phrase plus words, stories that
    have the phrase and all the words come first, then ones with just the phrase."""
    ids = _match(con, parsed.fts(), k)
    if parsed.has_phrase and parsed.words and len(ids) < k:
        seen = set(ids)
        ids += [i for i in _match(con, parsed.fts_required(), k) if i not in seen][:k - len(ids)]
    return ids


_stores = {}
_stores_lock = threading.Lock()


def _vector_db(search_dir):
    "The Jammi connection for this folder, or None if there are no vectors or no Jammi"
    with _stores_lock:
        if search_dir not in _stores:
            db = None
            path = os.path.join(search_dir, 'jammi', 'db')
            if os.path.isdir(path):
                try:
                    import jammi
                    db = jammi.connect('file://' + path)
                except ImportError:
                    logger.warning('jammi is not installed; using keyword search only')
            _stores[search_dir] = db
        return _stores[search_dir]


def vector_ids(con, search_dir, text, k=CANDIDATES):
    "Story rowids from Jammi vector search for some text, best first"
    db = _vector_db(search_dir)
    if db is None or not text:
        return []
    vector = db.encode_query(model=MODEL, query=text)
    table = db.search(SOURCE, query=vector, k=k, select=['id'])
    ids = table.column('id').to_pylist() if table.num_rows else []
    if not ids:
        return []
    rowid = dict(con.execute('SELECT id, rowid FROM stories WHERE id IN (%s)'
                             % ','.join('?' * len(ids)), ids))
    return [rowid[i] for i in ids if i in rowid]


def semantic_ids(con, search_dir, parsed, k=CANDIDATES):
    """Vector hits for the whole query, as (exact, related) rowid lists. Both
    leave out stories with an excluded word; exact also keeps only stories with
    every quoted phrase. Both are [] if vector search fails."""
    filtered = parsed.excluded or parsed.has_phrase
    try:
        ids = vector_ids(con, search_dir, parsed.vector_text(), k * FILTER_FACTOR if filtered else k)
    except Exception:
        logger.exception('vector search failed; using keyword results only')
        return [], []
    if parsed.excluded:
        excluded = _all_matches(con, parsed.fts_excluded())
        ids = [i for i in ids if i not in excluded]
    related = ids
    if parsed.has_phrase:
        required = _all_matches(con, parsed.fts_required())
        ids = [i for i in ids if i in required]
    return ids[:k], related[:k]


def rrf(*ranked_lists):
    "Reciprocal rank fusion"
    scores = {}
    for ranked in ranked_lists:
        for rank, item in enumerate(ranked):
            scores[item] = scores.get(item, 0) + 1.0 / (RRF_K + rank + 1)
    return sorted(scores, key=scores.get, reverse=True)


def to_result(row):
    "A stories row as the fields the templates expect (the old Whoosh schema)"
    (id_, link_id, score, body, name, created_utc, subreddit, parent_id, gilded) = row
    return {'url': 'https://www.reddit.com/comments/%s/x/%s' % ((link_id or '')[3:], id_),
            'comment': body,
            'score': score,
            'created': str(created_utc),
            'subreddit': subreddit,
            'parent': (parent_id or '')[3:],
            'gilded': gilded,
            'name': name}


class Results(list):
    """Search results. related is True when nothing matched a quoted phrase
    exactly and these are related stories from vector search instead."""
    related = False


def search(query, limit=25, search_dir=DEFAULT_DIR):
    """Parse the query (query_parser), then fuse FTS5 with vector search. Quoted
    phrases stay exact: vector hits without them are dropped. Excluded words are
    dropped from both lists. When a phrase matches nothing, return related
    stories with Results.related set."""
    parsed = parse_query(query)
    results = Results()
    if parsed.empty or not os.path.exists(os.path.join(search_dir, 'search.db')):
        return results
    con = sqlite3.connect(os.path.join(search_dir, 'search.db'))
    try:
        exact, related = semantic_ids(con, search_dir, parsed)
        ranked = rrf(keyword_ids(con, parsed), exact)
        if not ranked and parsed.has_phrase:
            ranked = related
            results.related = bool(ranked)
        ranked = ranked[:limit]
        if not ranked:
            return results
        rows = con.execute(
            'SELECT rowid, id, link_id, score, body, name, created_utc, subreddit, parent_id, gilded '
            'FROM stories WHERE rowid IN (%s)' % ','.join('?' * len(ranked)), ranked).fetchall()
        by_rowid = {r[0]: to_result(r[1:]) for r in rows}
        results.extend(by_rowid[r] for r in ranked if r in by_rowid)
        return results
    finally:
        con.close()
