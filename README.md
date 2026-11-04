# Wisdom of Reddit

A search engine for long, high quality reddit comments that tell a story.
The site is a Flask app (`wisdomofreddit.py`) that searches a [Whoosh](https://pypi.org/project/Whoosh/) index of comments.

## 1. Setup

You need Python 3.12 or newer.

```bash
python3 -m venv venv
source venv/bin/activate        # on Windows: venv\Scripts\activate
pip install -r requirements.txt
python -m unittest discover tests
```

## 2. Quick start with the sample data

`sample_data/sample_comments.csv` has 200 story comments from December 2025.
They are chosen so that most of the queries in `random_queries.txt` find something.
You don't need to download anything.

```bash
python index_comments.py -f sample_data/sample_comments.csv -n wor -c True
python wisdomofreddit.py
```

The first command builds the index in `./indexdir` (it takes a few seconds).
The second starts the site at http://localhost:6464. Try searching for `dad`, `"my mom"` or `time travel`, or click Random.

`-c True` creates a new index and replaces any index already in `./indexdir`.
Leave it out to add comments to the existing index.

## 3. Getting new comments (2025 onwards)

Newer comments come from the monthly reddit dumps (`RC_YYYY-MM.zst`) that Arctic Shift publishes on Academic Torrents.
Links to each month: https://github.com/ArthurHeitmann/arctic_shift/blob/master/download_links.md

A month's comments file is large (for example, about 38 GB compressed for December 2025), so you only need this if you work on the data pipeline.
Testers can ask for `sample_comments.db` and `sample_scored.db` on Drive (see [#14](https://github.com/qxf2/wisdomofreddit/issues/14) and [#15](https://github.com/qxf2/wisdomofreddit/issues/15)).

1. Download one month's comments file. Each monthly torrent also has a submissions file. Only download the comments file:
   ```bash
   aria2c --select-file=1 --seed-time=0 --max-overall-upload-limit=1K -d <download dir> <month>.torrent
   ```
2. Filter it into `./data/comments.db`. A comment is kept when its score is above 35 and it has more than 150 words:
   ```bash
   python fetch_comments.py filter -f <download dir>/reddit/comments/RC_2025-12.zst -m 2025-12
   ```
3. Delete the `.zst` file. Repeat for the previous month.
4. Make a small random sample db for testers:
   ```bash
   python fetch_comments.py sample -o data/sample_comments.db -n 2000
   ```
5. Score comments for story potential with Jev (TypeSafe). Put your key in a `.env` file in the repo root (`TYPESAFE_API_KEY=...`).
   `.env` is git ignored. Jev only sees the comment text.
   ```bash
   python score_stories.py -d data/comments.db score
   ```
6. See how many comments are stories, the tokens used, and examples to check by hand:
   ```bash
   python score_stories.py -d data/comments.db report -t 0.5 -v 2
   ```
   A comment counts as a story when `p_story >= 0.5` and `vividness >= 2`.

The site doesn't search `comments.db` directly yet. Building the index from it is [#29](https://github.com/qxf2/wisdomofreddit/issues/29).

## 4. Appendix: rebuilding the old 2007 to 2015 index

The live site's original index came from a BigQuery copy of reddit, which has since stopped updating.
These steps are kept for reference. The query processes about 450 GB.

1. Sign up for BigQuery and run:
   ```sql
   SELECT link_id,id,score,body,name,created_utc,subreddit,parent_id,gilded
   FROM [fh-bigquery:reddit_comments.2015_01],
   [fh-bigquery:reddit_comments.2015_02],
   [fh-bigquery:reddit_comments.2015_03],
   [fh-bigquery:reddit_comments.2015_04],
   [fh-bigquery:reddit_comments.2015_05],
   [fh-bigquery:reddit_comments.2015_06],
   [fh-bigquery:reddit_comments.2015_07],
   [fh-bigquery:reddit_comments.2015_08],
   [fh-bigquery:reddit_comments.2015_09],
   [fh-bigquery:reddit_comments.2015_10],
   [fh-bigquery:reddit_comments.2010],
   [fh-bigquery:reddit_comments.2011],
   [fh-bigquery:reddit_comments.2012],
   [fh-bigquery:reddit_comments.2013],
   [fh-bigquery:reddit_comments.2014],
   [fh-bigquery:reddit_comments.2007],
   [fh-bigquery:reddit_comments.2008],
   [fh-bigquery:reddit_comments.2009]
   where score>35 and (length(body) - length(replace(body,' ','')) + 1) > 150
   ```
2. Export the table to CSV. The table is big, so you will get several CSV files. Put them in `./data/`.
3. Index them (this takes hours):
   ```bash
   python index_comments.py -d ./data -n wor -c True
   ```
   When it finishes, `./indexdir` has a set of `wor_*.seg` files.

## Questions?

Contact mak@qxf2.com
