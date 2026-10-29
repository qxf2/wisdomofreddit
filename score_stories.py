"""
Use Jev (TypeSafe) to judge which comments tell a real-life story an author could use.

Jev only sees the comment text. For each comment we store:
a) p_story: probability that the comment tells a real-life story or experience
b) vividness: how concrete and vivid that story is (0 to 3)

Scores go into the story_scores table next to the comments table.
A comment counts as a story when p_story >= 0.5 and vividness >= 2.
Comments are never deleted, so the thresholds can change without calling Jev again.

Needs TYPESAFE_API_KEY in the environment or in a .env file.

Usage:
    python score_stories.py score -d data/sample_comments.db
    python score_stories.py report -d data/sample_comments.db
"""

import argparse
import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from typesafe_sdk import Noul, Score, TypeSafeClient

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(CURRENT_DIR, 'data', 'comments.db')
STORY_THRESHOLD = 0.5
MIN_VIVIDNESS = 2
COMMIT_EVERY = 100

QUESTIONS = {
    'is_story': Noul(
        instructions='Does `comment` tell a real-life story or experience that an author could quote as lived wisdom?',
        criteria={
            'true': "The commenter recounts something that really happened to them or to someone they know "
                    "(family, friend, colleague), or draws on their own job, life, or expertise "
                    "(e.g. 'chess player here...', 'my dad once saw...', 'I worked as a nurse and...')",
            'false': 'Jokes, insults, puns, generic opinions, restated facts, links, or arguments '
                     'with no real-life experience behind them',
        }),
    'vividness': Score(
        instructions='How concrete and vivid is the real-life story or experience in `comment`?',
        criteria=[
            'No real-life story or experience at all',
            'Vague mention of an experience with no detail',
            'Real-life experience with some specific detail',
            'Rich first-hand account with concrete people, places, or events',
        ]),
}


def get_connection(db_path):
    "Open the db and create the story_scores table if needed"
    connection = sqlite3.connect(db_path)
    connection.execute("""CREATE TABLE IF NOT EXISTS story_scores (
                          id TEXT PRIMARY KEY,
                          p_story REAL,
                          vividness REAL,
                          vividness_confidence REAL,
                          model TEXT,
                          input_tokens INTEGER,
                          output_tokens INTEGER,
                          scored_at TEXT)""")

    return connection


def get_unscored(connection, limit=None):
    "Return (id, body) for comments that have not been scored yet"
    query = 'SELECT id, body FROM comments WHERE id NOT IN (SELECT id FROM story_scores)'
    if limit:
        query += ' LIMIT %d' % limit

    return connection.execute(query).fetchall()


def score_comment(client, comment_id, body):
    "Ask Jev about one comment and return a story_scores row"
    response = client.system_one(state={'comment': body}, questions=QUESTIONS)
    vividness = response.answers['vividness']

    return (comment_id,
            response.answers['is_story'].noul,
            vividness.score,
            vividness.confidence,
            response.model,
            response.usage.input_tokens,
            response.usage.output_tokens,
            time.strftime('%Y-%m-%d %H:%M:%S'))


def score_comments(client, db_path=DEFAULT_DB, limit=None, workers=16):
    "Score all unscored comments in the db"
    connection = get_connection(db_path)
    comments = get_unscored(connection, limit)
    print('Comments to score: %d' % len(comments))

    def safe_score(comment):
        try:
            return score_comment(client, *comment)
        except Exception as error:
            # The comment stays unscored, so a rerun will try it again
            print('Unable to score %s: %s' % (comment[0], error))
            return None

    scored = 0
    errors = 0
    with ThreadPoolExecutor(workers) as pool:
        for row in pool.map(safe_score, comments):
            if row is None:
                errors += 1
                continue
            connection.execute('INSERT OR REPLACE INTO story_scores VALUES (?,?,?,?,?,?,?,?)', row)
            scored += 1
            if scored % COMMIT_EVERY == 0:
                connection.commit()
                print('Scored %d of %d' % (scored, len(comments)))
    connection.commit()
    connection.close()
    print('Scored %d comments, %d errors' % (scored, errors))


def clip(text, length=230):
    "Return the text on one line, cut to length"
    text = ' '.join(text.split())
    return text if len(text) <= length else text[:length] + '...'


def is_story(p_story, vividness, threshold=STORY_THRESHOLD, min_vividness=MIN_VIVIDNESS):
    "Does a scored comment count as a story?"
    return p_story >= threshold and vividness >= min_vividness


def report(db_path=DEFAULT_DB, threshold=STORY_THRESHOLD, min_vividness=MIN_VIVIDNESS, size=10):
    "Print the story split, token usage and examples for a human to check"
    connection = get_connection(db_path)
    total, stories, input_tokens, output_tokens = connection.execute(
        'SELECT COUNT(*), SUM(p_story >= ? AND vividness >= ?), SUM(input_tokens), SUM(output_tokens) '
        'FROM story_scores', (threshold, min_vividness)).fetchone()
    print('%d of %d scored comments are stories (p_story >= %.2f and vividness >= %.1f)'
          % (stories or 0, total, threshold, min_vividness))
    print('Tokens used: %s input, %s output\n' % (input_tokens, output_tokens))
    select = 'SELECT s.p_story, s.vividness, c.body FROM story_scores s JOIN comments c ON c.id = s.id '
    groups = [('TOP STORIES', select + 'ORDER BY s.p_story DESC, s.vividness DESC LIMIT ?', (size,)),
              ('CLEAREST NON-STORIES', select + 'ORDER BY s.p_story LIMIT ?', (size,)),
              ('BORDERLINE', select + 'ORDER BY ABS(s.p_story - ?) LIMIT ?', (threshold, size))]
    for name, query, params in groups:
        print('=== %s ===' % name)
        for p_story, vividness, body in connection.execute(query, params):
            label = 'STORY' if is_story(p_story, vividness, threshold, min_vividness) else 'not story'
            print('[%-9s] P=%.2f vivid=%.1f | %s' % (label, p_story, vividness, clip(body)))
        print()
    connection.close()


#---START OF SCRIPT
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Score comments for story potential with Jev')
    parser.add_argument('-d', '--db', default=DEFAULT_DB, help='Path of the sqlite db')
    subparsers = parser.add_subparsers(dest='command', required=True)
    score_parser = subparsers.add_parser('score', help='Score unscored comments')
    score_parser.add_argument('-n', '--limit', type=int, help='Only score this many comments')
    score_parser.add_argument('-w', '--workers', type=int, default=16, help='Parallel requests')
    report_parser = subparsers.add_parser('report', help='Show the story split and examples')
    report_parser.add_argument('-t', '--threshold', type=float, default=STORY_THRESHOLD,
                               help='Minimum p_story to count as a story')
    report_parser.add_argument('-v', '--vividness', type=float, default=MIN_VIVIDNESS,
                               help='Minimum vividness (0 to 3) to count as a story')
    args = parser.parse_args()

    start_time = time.time()
    if args.command == 'score':
        load_dotenv(os.path.join(CURRENT_DIR, '.env'))
        with TypeSafeClient() as client:
            score_comments(client, args.db, args.limit, args.workers)
    else:
        report(args.db, args.threshold, args.vividness)
    print('Duration: %d seconds' % int(time.time() - start_time))
