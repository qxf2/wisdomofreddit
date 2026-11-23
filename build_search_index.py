"""
Build or update the story search index from data/comments.db (#29).

Run it again whenever comments.db gets a new month: only stories that are not
indexed yet are added to FTS5 and encoded. See story_search.py for the design.

    python build_search_index.py                       # data/comments.db -> data/search
    python build_search_index.py -c data/sample_scored.db -o data/sample_search
    python build_search_index.py -c sample_data/sample_comments.csv   # every row counts as a story
    python build_search_index.py --vectors new.parquet # vectors encoded on the GPU box
    python build_search_index.py --no-encode           # keyword index only, encode later
"""

import argparse
import os
import tempfile
import time

import story_search


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('-c', '--comments', default=os.path.join('data', 'comments.db'),
                        help='comments db with comments and story_scores, or a CSV of '
                             'stories (default: data/comments.db)')
    parser.add_argument('-o', '--out', default=story_search.DEFAULT_DIR,
                        help='search folder (default: data/search)')
    parser.add_argument('--vectors', help='parquet of precomputed vectors (_row_id or id, vector) to add')
    parser.add_argument('--no-encode', action='store_true',
                        help="don't encode stories that have no vector yet")
    args = parser.parse_args()

    if not os.path.exists(args.comments):
        parser.error('%s not found' % args.comments)
    out = os.path.abspath(args.out)
    timings = {}

    start = time.time()
    con = story_search.connect(out)
    if args.comments.endswith('.csv'):
        with tempfile.TemporaryDirectory() as tmp:
            comments_db = story_search.csv_to_comments_db(args.comments, os.path.join(tmp, 'c.db'))
            added = story_search.add_stories(con, comments_db)
    else:
        added = story_search.add_stories(con, args.comments)
    total = con.execute('SELECT COUNT(*) FROM stories').fetchone()[0]
    timings['fts5'] = time.time() - start
    print(f'FTS5: added {added} stories ({total} in total) in {timings["fts5"]:.1f} s')

    new_vectors = 0
    if args.vectors:
        start = time.time()
        indexed = {r[0] for r in con.execute('SELECT id FROM stories')}
        ids, matrix = story_search.read_vectors(args.vectors)
        keep = [i for i, row_id in enumerate(ids) if row_id in indexed]
        new_vectors += story_search.merge_vectors(out, [ids[i] for i in keep], matrix[keep])
        timings['merge'] = time.time() - start
        print(f'Vectors: took {new_vectors} from {args.vectors} in {timings["merge"]:.1f} s')

    missing = story_search.missing_vectors(con, out)
    if missing and not args.no_encode:
        start = time.time()
        print(f'Encoding {len(missing)} stories...')
        matrix = story_search.encode([body for _, body in missing])
        new_vectors += story_search.merge_vectors(out, [i for i, _ in missing], matrix)
        timings['encode'] = time.time() - start
        print(f'Encoded {len(missing)} stories in {timings["encode"]:.1f} s')
        missing = []
    elif missing:
        print(f'{len(missing)} stories have no vector yet; they are found by keyword search only')

    store = os.path.join(out, 'jammi', 'db')
    if os.path.exists(story_search.vectors_path(out)) and (new_vectors or not os.path.isdir(store)):
        start = time.time()
        count = story_search.build_vector_store(out)
        timings['import'] = time.time() - start
        print(f'Jammi: imported {count} vectors in {timings["import"]:.1f} s. '
              'Restart the app to pick them up.')

    print('Total: %.1f s' % sum(timings.values()))


if __name__ == '__main__':
    main()
