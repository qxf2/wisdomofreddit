"""Export Dec 2025 stories (p_story>=0.5, vividness>=2) from comments.db to parquet."""
import sqlite3, sys, pyarrow as pa, pyarrow.parquet as pq
db, out = sys.argv[1], sys.argv[2]
con = sqlite3.connect(db)
rows = con.execute("""select c.id, c.body, c.subreddit, c.score, c.link_id, c.created_utc
  from comments c join story_scores s on s.id=c.id
  where s.p_story>=0.5 and s.vividness>=2 order by c.created_utc""").fetchall()
cols = list(zip(*rows))
t = pa.table({"id": list(cols[0]), "body": list(cols[1]), "subreddit": list(cols[2]),
              "score": list(cols[3]), "link_id": list(cols[4]), "created_utc": list(cols[5])})
pq.write_table(t, out)
print(out, t.num_rows)
