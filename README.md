#Wisdom of reddit setup
Code to get Wisdom of reddit up and running locally

----------------
1. PYTHON SETUP
----------------

a. Install Python 2.x

b. Add to your PATH environment variable

c. If you do not have it already, get pip 

d. 'pip install flask'

e. Install Whoosh

g. Install the csv library ('pip install csv')


--------------
2. DATA SETUP
--------------

a. Sign up for bigquery

b. Run this query 

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

NOTE: This query will process 450 GB when run.

c. Export the table to csv format. Since the table is big, you will have multiple csvs

d. Store the csvs in ./data/

d. Run python index_comments.py -d ./data -n wor -c True (this step takes hours)

e. NOTE: -c True should be used only if you want to create the index from scratch

f. If things go well, you should see a ./indexdir created with a bunch of wor_*.seg files

-------
3. RUN
-------

a. python wisdomofreddit.py (this will run on port 6464 of your local host)

b. If things go well, you should see the Wisdom of reddit homepage and you should be able to search

-----------
4. ISSUES?
-----------

a. Contact mak@qxf2.com

