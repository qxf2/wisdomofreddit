"""
wisdomofreddit is a search app for high quality reddit comments
"""

from whoosh import index
from whoosh import scoring
from whoosh.qparser import QueryParser
from flask import Flask
from flask import render_template
from flask import request
import os,csv,re

app = Flask(__name__)


def open_index(index_dir,index_name):
    "Open a given index"
    ix = index.open_dir(index_dir,indexname=index_name)

    return ix


def search_comments(query):
    "Ask whoosh to return the top 20 matches"
    all_results = []
    try:
        index_dir = os.path.join(os.path.dirname(__file__),'indexdir')
        ix = open_index(index_dir,index_name='wor')
        fp = open('/tmp/query.log','a')
        fp.write(str(query)+"\n")
        fp.close()
        with ix.searcher() as searcher:
            parser = QueryParser("comment",ix.schema)
            results = searcher.search(parser.parse(query),limit=25)
            for result in results:
                all_results.append(result)
            fp = open('/tmp/results.log','a')
            fp.write(str(all_results)[:1]+"\n")
            fp.close()
    except Exception,e:
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
        return render_template('index.html')
    else:
        results = search_comments(query)
        return render_template('results.html', query=query, results=results)


@app.route("/about")
def about():
    "The about page"
    return render_template('about.html')


#---START
if __name__=='__main__':
    app.run(host='0.0.0.0',port=6464)
