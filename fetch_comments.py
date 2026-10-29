"""
Filter a monthly reddit comments dump into a sqlite db.

Dumps are the monthly RC_YYYY-MM.zst files (zstd compressed, one JSON
comment per line) published by Pushshift/Arctic Shift.

We keep comments that match the original 2016 Wisdom of reddit rules:
a) score is more than 35
b) more than 150 words (counted as number of spaces + 1, like the old BigQuery query)

Usage:
    python fetch_comments.py filter -f RC_2025-12.zst -m 2025-12
    python fetch_comments.py sample -o data/sample_comments.db -n 2000
"""

import argparse
import io
import json
import os
import sqlite3
import time

import zstandard

MIN_SCORE = 35
MIN_WORDS = 150
FLAG_COMMENT_COUNT = 10000000
BATCH_SIZE = 10000
DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'comments.db')

COLUMNS = ['id', 'link_id', 'score', 'body', 'name', 'created_utc',
           'subreddit', 'parent_id', 'gilded', 'month']


def get_connection(db_path):
    "Open the db and create the tables if needed"
    db_dir = os.path.dirname(os.path.abspath(db_path))
    if not os.path.exists(db_dir):
        os.makedirs(db_dir)
    connection = sqlite3.connect(db_path)
    connection.execute("""CREATE TABLE IF NOT EXISTS comments (
                          id TEXT PRIMARY KEY,
                          link_id TEXT,
                          score INTEGER,
                          body TEXT,
                          name TEXT,
                          created_utc INTEGER,
                          subreddit TEXT,
                          parent_id TEXT,
                          gilded INTEGER,
                          month TEXT)""")
    connection.execute("""CREATE TABLE IF NOT EXISTS months_done (
                          month TEXT PRIMARY KEY,
                          lines_read INTEGER,
                          comments_kept INTEGER,
                          finished_at TEXT)""")

    return connection


def word_count(body):
    "Count words the same way the original BigQuery query did"
    return body.count(' ') + 1


def is_good_comment(comment):
    "Does the comment pass our filter?"
    body = comment.get('body') or ''
    if body in ('[deleted]', '[removed]'):
        return False
    try:
        score = int(comment.get('score') or 0)
    except (TypeError, ValueError):
        return False

    return score > MIN_SCORE and word_count(body) > MIN_WORDS


def get_row(comment, month):
    "Convert a comment from the dump into a db row"
    return (comment['id'],
            comment.get('link_id'),
            int(comment['score']),
            comment['body'],
            comment.get('name') or 't1_' + comment['id'],
            int(comment.get('created_utc') or 0),
            comment.get('subreddit'),
            comment.get('parent_id'),
            int(comment.get('gilded') or 0),  # Reddit removed gilding in 2023
            month)


def read_dump(zst_file):
    "Yield one comment (dict) at a time from a zst dump"
    with open(zst_file, 'rb') as fp:
        # Pushshift dumps need a larger window than the zstd default
        reader = zstandard.ZstdDecompressor(max_window_size=2**31).stream_reader(fp)
        for line in io.TextIOWrapper(reader, encoding='utf-8', errors='replace'):
            try:
                yield json.loads(line)
            except ValueError:
                print('Skipping malformed line: %s' % line[:100])


def insert_rows(connection, rows):
    "Insert rows, ignoring comments we already have"
    connection.executemany('INSERT OR IGNORE INTO comments VALUES (%s)' % ','.join('?' * len(COLUMNS)),
                           rows)
    connection.commit()


def filter_dump(zst_file, month, db_path=DEFAULT_DB):
    "Filter one monthly dump into the db"
    connection = get_connection(db_path)
    if connection.execute('SELECT 1 FROM months_done WHERE month=?', (month,)).fetchone():
        print('Month %s is already done. Skipping.' % month)
        connection.close()
        return
    lines_read = 0
    comments_kept = 0
    rows = []
    for comment in read_dump(zst_file):
        lines_read += 1
        if is_good_comment(comment):
            rows.append(get_row(comment, month))
            comments_kept += 1
        if len(rows) >= BATCH_SIZE:
            insert_rows(connection, rows)
            rows = []
        if lines_read % 1000000 == 0:
            print('%s: read %d lines, kept %d comments' % (month, lines_read, comments_kept))
    insert_rows(connection, rows)
    connection.execute('INSERT INTO months_done VALUES (?,?,?,?)',
                       (month, lines_read, comments_kept, time.strftime('%Y-%m-%d %H:%M:%S')))
    connection.commit()
    total = connection.execute('SELECT COUNT(*) FROM comments').fetchone()[0]
    connection.close()
    print('%s: done. Read %d lines, kept %d comments. Total in db: %d'
          % (month, lines_read, comments_kept, total))
    if total >= FLAG_COMMENT_COUNT:
        print('FLAG: the db has reached %d comments.' % total)


def make_sample(sample_path, size, db_path=DEFAULT_DB):
    "Copy a random sample of comments into a new db for testers"
    if os.path.exists(sample_path):
        os.remove(sample_path)
    get_connection(sample_path).close()
    connection = sqlite3.connect(db_path)
    connection.execute('ATTACH DATABASE ? AS sample', (sample_path,))
    connection.execute('INSERT INTO sample.comments SELECT * FROM comments ORDER BY RANDOM() LIMIT ?',
                       (size,))
    connection.execute('INSERT INTO sample.months_done SELECT * FROM months_done')
    connection.commit()
    count = connection.execute('SELECT COUNT(*) FROM sample.comments').fetchone()[0]
    connection.close()
    print('Wrote %d comments to %s' % (count, sample_path))


#---START OF SCRIPT
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Filter reddit comment dumps into a sqlite db')
    parser.add_argument('-d', '--db', default=DEFAULT_DB, help='Path of the sqlite db')
    subparsers = parser.add_subparsers(dest='command', required=True)
    filter_parser = subparsers.add_parser('filter', help='Filter one monthly dump into the db')
    filter_parser.add_argument('-f', '--filename', required=True, help='Path of the RC_YYYY-MM.zst file')
    filter_parser.add_argument('-m', '--month', required=True, help='Month of the dump, e.g. 2025-12')
    sample_parser = subparsers.add_parser('sample', help='Make a random sample db for testers')
    sample_parser.add_argument('-o', '--output', required=True, help='Path of the sample db')
    sample_parser.add_argument('-n', '--size', type=int, default=2000, help='Number of comments')
    args = parser.parse_args()

    start_time = time.time()
    if args.command == 'filter':
        filter_dump(args.filename, args.month, args.db)
    else:
        make_sample(args.output, args.size, args.db)
    print('Duration: %d seconds' % int(time.time() - start_time))
