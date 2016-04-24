"""
wisdomofreddit is a search app for high quality reddit comments
"""

from whoosh import index
from whoosh import scoring
from whoosh.qparser import QueryParser
from flask import Flask
from flask import render_template
from flask import request
import os,csv,re,random

app = Flask(__name__)


def open_index(index_dir,index_name):
    "Open a given index"
    ix = index.open_dir(index_dir,indexname=index_name)

    return ix


def get_random_query():
    "Return a random query"
    query = "Kasparov"
    random_query_file = os.path.join(os.path.dirname(__file__),'random_queries.txt')
    with open(random_query_file,'r') as fp:
        lines = fp.readlines()
        query = random.choice(lines)
        query = query.strip()

    return query


def search_comments(query):
    "Ask whoosh to return the top 20 matches"
    all_results = []
    try:
        index_dir = os.path.join(os.path.dirname(__file__),'indexdir')
        ix = open_index(index_dir,index_name='wor')
        if os.path.exists(r'/tmp/'):
            fp = open('/tmp/query.log','a')
            fp.write(str(query)+"\n")
            fp.close()
        with ix.searcher() as searcher:
            parser = QueryParser("comment",ix.schema)
            results = searcher.search(parser.parse(query),limit=25)
            for result in results:
                all_results.append(result)
            if os.path.exists(r'/tmp/'):
                fp = open('/tmp/results.log','a')
                fp.write(str(all_results)[:1]+"\n")
                fp.close()
    except Exception,e:
        if os.path.exists(r'/tmp/'):
            fp = open('/tmp/error.log','a')
            fp.write(str(e))
            fp.close()
        
    return all_results


@app.route("/")
def index_page():
    "The search page"
    return render_template('index.html')


@app.route("/search")
def search():
    "Return relevant comments"
    query = request.args.get('query')
    if query.strip() == "":
        return return_random_prompt()
    else:
        results = search_comments(query)
        return render_template('results.html', query=query, results=results)


@app.route("/random")
def return_random_prompt():
    "Return a random comment"
    query = get_random_query()
    results = []
    while results == []:
        results = search_comments(query)

    return render_template('random.html', results=results)



@app.route("/about")
def about():
    "The about page"
    return render_template('about.html')


@app.route("/why")
def why():
    "The about page"
    return render_template('why.html')


#---START
if __name__=='__main__':
    app.run(host='0.0.0.0',port=6464)
