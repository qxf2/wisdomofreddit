"""
Train a cheap local story classifier on Jev's labels, so Jev only scores the unclear comments.

The label is the story rule from score_stories.py: p_story >= 0.5 and vividness >= 2.
The model is TF-IDF (words and characters) with logistic regression.

a) train: fit on the scored comments, keep 20% back, save the model
b) evaluate: agreement with Jev on the held-out comments, plus what happens
   if comments in an unsure band of model probability go to Jev instead
c) predict: label the comments in any db and store them in model_scores.
   If the db also has Jev's story_scores, compare the two.

Comments that are in the sample db are never used for training or testing,
so testers get a fair comparison on sample_scored.db.

Usage:
    python train_classifier.py train
    python train_classifier.py evaluate
    python train_classifier.py predict -d data/sample_scored.db
"""

import argparse
import os
import sqlite3
import time

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, precision_recall_fscore_support
from sklearn.model_selection import train_test_split
from sklearn.pipeline import FeatureUnion, Pipeline

from score_stories import MIN_VIVIDNESS, STORY_THRESHOLD

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(CURRENT_DIR, 'data', 'comments.db')
SAMPLE_DB = os.path.join(CURRENT_DIR, 'data', 'sample_comments.db')
DEFAULT_MODEL = os.path.join(CURRENT_DIR, 'models', 'story_clf.joblib')
MODEL_NAME = 'tfidf-logreg-v1'
TEST_SIZE = 0.2
SEED = 42
# Unsure bands of model probability: comments inside a band go to Jev
BANDS = [(0.5, 0.5), (0.4, 0.6), (0.3, 0.7), (0.2, 0.8), (0.1, 0.9)]
# Jev cost per comment (about 800 input tokens at $0.042 per million) and backfill size
JEV_COST_PER_COMMENT = 0.034 / 1000
BACKFILL_COMMENTS = (8_000_000, 12_000_000)


def build_model():
    "TF-IDF on words and characters, then logistic regression"
    features = FeatureUnion([
        ('words', TfidfVectorizer(ngram_range=(1, 2), min_df=3, max_features=200_000,
                                  sublinear_tf=True, strip_accents='unicode')),
        ('chars', TfidfVectorizer(analyzer='char_wb', ngram_range=(3, 5), min_df=5,
                                  max_features=200_000, sublinear_tf=True)),
    ])
    classifier = LogisticRegression(C=4.0, class_weight='balanced', max_iter=2000)
    return Pipeline([('features', features), ('classifier', classifier)])


def get_ids(db_path):
    "Return the set of comment ids in a db (empty if the db is missing)"
    if not db_path or not os.path.exists(db_path):
        return set()
    connection = sqlite3.connect(db_path)
    ids = {row[0] for row in connection.execute('SELECT id FROM comments')}
    connection.close()
    return ids


def load_labelled(db_path, exclude_ids=()):
    "Return ids, texts and Jev labels (1 = story) for the scored comments"
    connection = sqlite3.connect(db_path)
    rows = connection.execute(
        'SELECT c.id, c.body, s.p_story >= ? AND s.vividness >= ? '
        'FROM comments c JOIN story_scores s ON s.id = c.id ORDER BY c.id',
        (STORY_THRESHOLD, MIN_VIVIDNESS)).fetchall()
    connection.close()
    rows = [row for row in rows if row[0] not in exclude_ids]
    return [row[0] for row in rows], [row[1] for row in rows], [int(row[2]) for row in rows]


def split(ids, texts, labels):
    "The same train/test split every time, with the same story share in both parts"
    return train_test_split(ids, texts, labels, test_size=TEST_SIZE,
                            random_state=SEED, stratify=labels)


def train(db_path=DEFAULT_DB, model_path=DEFAULT_MODEL, sample_db=SAMPLE_DB):
    "Fit the model on 80% of the labelled comments and save it with the held-out ids"
    ids, texts, labels = load_labelled(db_path, get_ids(sample_db))
    print('Labelled comments: %d (%d stories)' % (len(ids), sum(labels)))
    train_ids, test_ids, train_texts, _, train_labels, _ = split(ids, texts, labels)
    print('Training on %d, holding back %d' % (len(train_ids), len(test_ids)))
    model = build_model()
    model.fit(train_texts, train_labels)
    os.makedirs(os.path.dirname(model_path) or '.', exist_ok=True)
    joblib.dump({'model': model, 'name': MODEL_NAME, 'test_ids': test_ids,
                 'trained_at': time.strftime('%Y-%m-%d %H:%M:%S')}, model_path)
    print('Saved model to %s' % model_path)


def metrics(jev_labels, labels):
    "Accuracy, precision, recall and F1 for 'story', against Jev"
    precision, recall, f1, _ = precision_recall_fscore_support(
        jev_labels, labels, average='binary', zero_division=0)
    return accuracy_score(jev_labels, labels), precision, recall, f1


def band_rows(probabilities, jev_labels, bands=BANDS):
    "For each unsure band: share sent to Jev and the agreement of the final labels"
    rows = []
    for low, high in bands:
        to_jev = [low <= p < high for p in probabilities]
        final = [jev if unsure else int(p >= 0.5)
                 for p, jev, unsure in zip(probabilities, jev_labels, to_jev)]
        share = sum(to_jev) / len(to_jev) if to_jev else 0.0
        rows.append(((low, high), share) + metrics(jev_labels, final))
    return rows


def print_report(probabilities, jev_labels):
    "Print model-only agreement and the unsure-band table"
    accuracy, precision, recall, f1 = metrics(jev_labels, [int(p >= 0.5) for p in probabilities])
    print('Comments: %d, Jev stories: %d' % (len(jev_labels), sum(jev_labels)))
    print('Model alone: accuracy %.3f, story precision %.3f, recall %.3f, F1 %.3f\n'
          % (accuracy, precision, recall, f1))
    low_count, high_count = BACKFILL_COMMENTS
    print('Unsure band  To Jev  Accuracy  Precision  Recall    F1  Backfill Jev cost (%dM-%dM)'
          % (low_count // 1_000_000, high_count // 1_000_000))
    for (low, high), share, accuracy, precision, recall, f1 in band_rows(probabilities, jev_labels):
        band = 'none' if low == high else '%.1f-%.1f' % (low, high)
        print('%-11s  %5.1f%%  %8.3f  %9.3f  %6.3f  %.3f  $%.0f-$%.0f'
              % (band, share * 100, accuracy, precision, recall, f1,
                 share * low_count * JEV_COST_PER_COMMENT, share * high_count * JEV_COST_PER_COMMENT))
    print('All comments to Jev: $%.0f-$%.0f' % (low_count * JEV_COST_PER_COMMENT,
                                               high_count * JEV_COST_PER_COMMENT))


def evaluate(db_path=DEFAULT_DB, model_path=DEFAULT_MODEL):
    "Report agreement with Jev on the comments held back during training"
    saved = joblib.load(model_path)
    test_ids = set(saved['test_ids'])
    ids, texts, labels = load_labelled(db_path)
    rows = [(text, label) for comment_id, text, label in zip(ids, texts, labels)
            if comment_id in test_ids]
    probabilities = saved['model'].predict_proba([text for text, _ in rows])[:, 1]
    print('Model %s trained at %s, held-out comments from %s' % (saved['name'], saved['trained_at'], db_path))
    print_report(list(probabilities), [label for _, label in rows])


def predict(db_path, model_path=DEFAULT_MODEL):
    "Label every comment in the db, store it in model_scores, and compare with Jev if possible"
    saved = joblib.load(model_path)
    connection = sqlite3.connect(db_path)
    connection.execute("""CREATE TABLE IF NOT EXISTS model_scores (
                          id TEXT PRIMARY KEY,
                          p_story_model REAL,
                          is_story INTEGER,
                          model TEXT,
                          scored_at TEXT)""")
    comments = connection.execute('SELECT id, body FROM comments').fetchall()
    probabilities = saved['model'].predict_proba([body for _, body in comments])[:, 1]
    scored_at = time.strftime('%Y-%m-%d %H:%M:%S')
    connection.executemany('INSERT OR REPLACE INTO model_scores VALUES (?,?,?,?,?)',
                           [(comment_id, float(p), int(p >= 0.5), saved['name'], scored_at)
                            for (comment_id, _), p in zip(comments, probabilities)])
    connection.commit()
    print('Labelled %d comments, %d stories, in model_scores' %
          (len(comments), int(sum(p >= 0.5 for p in probabilities))))

    has_jev = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='story_scores'").fetchone()
    if has_jev:
        rows = connection.execute(
            'SELECT m.p_story_model, s.p_story >= ? AND s.vividness >= ? '
            'FROM model_scores m JOIN story_scores s ON s.id = m.id',
            (STORY_THRESHOLD, MIN_VIVIDNESS)).fetchall()
        print('\nCompared with Jev:')
        print_report([row[0] for row in rows], [int(row[1]) for row in rows])
    connection.close()


#---START OF SCRIPT
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Train a cheap story classifier on Jev's labels")
    parser.add_argument('-d', '--db', default=DEFAULT_DB, help='Path of the sqlite db')
    parser.add_argument('-m', '--model', default=DEFAULT_MODEL, help='Path of the saved model')
    subparsers = parser.add_subparsers(dest='command', required=True)
    subparsers.add_parser('train', help='Train on the scored comments and save the model')
    subparsers.add_parser('evaluate', help='Agreement with Jev on the held-out comments')
    subparsers.add_parser('predict', help='Label the comments in a db and compare with Jev')
    args = parser.parse_args()

    start_time = time.time()
    if args.command == 'train':
        train(args.db, args.model)
    elif args.command == 'evaluate':
        evaluate(args.db, args.model)
    else:
        predict(args.db, args.model)
    print('Duration: %d seconds' % int(time.time() - start_time))
