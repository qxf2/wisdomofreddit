"""
wisdomofreddit is a search app for high quality reddit comments
"""

from whoosh import index
from whoosh import scoring
from whoosh.qparser import QueryParser
from flask import Flask
from flask import render_template
from flask import request
from flask import redirect, url_for
from flask import _request_ctx_stack
import os,csv,re,random,sqlite3
from ast import literal_eval

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
    "The why page"
    return render_template('why.html')


@app.route("/uses")
def use_cases():
    "The uses page"
    return render_template('uses.html')


@app.route("/pro-tips")
def pro_tips():
    "The pro-tips page"
    return render_template('pro-tips.html')


@app.route("/examples")
def examples():
    "The examples page"
    return render_template('examples.html')


@app.route("/blog")
def blog():
    "The blog"
    return render_template('blog.html')


@app.route("/blogposts/real-scary-creepy-paranormal-stories")
def paranormal():
    "Paranormal stories"
    return render_template('blogposts/real-scary-creepy-paranormal-stories.html')


@app.route("/blogposts/mundane-coincidence-stories")
def mundane_coincidences():
    "Mundane coincidences"
    return render_template('blogposts/mundane-coincidence-stories.html')


@app.route('/api-tutorial-main')
def api_tutorial_main():
    "Api Tutorial main page- If method is post redirect to api tutorial redirect with name and comments"        
    return render_template('api-tutorial-main.html')
        

@app.route('/api-tutorial-redirect',methods=['GET','POST'])
def api_tutorial_redirect():
    "Api Tutorial Redirect page- Saves the name and comments and displays all the name and comments"
    db_file = os.path.join(os.path.dirname(__file__),'tmp','wisdomofreddit.db') #Create a variabe as db_file to create the DB file in the temp directory
    connection_obj = sqlite3.connect(db_file) #Connect to the db
    cursor_obj = connection_obj.cursor()
    if request.method == 'POST':
        user_name = request.form['submitname']
        user_comments = request.form['submitcomments']
        value = [user_name,user_comments]
        cursor_obj.execute("INSERT INTO comments VALUES (?,?)",value) #Insert values into the table. FYI comments table has already been created in the DB
        connection_obj.commit() #Save the changes
    results = cursor_obj.execute("SELECT * FROM comments") #Hold all the name and comments in a variable
    
    return render_template('api-tutorial-redirect.html', results=results.fetchall())


@app.route('/trial_page_bug')
def trial_page_bug():
    "Trial page for practicing bug reports"
    return render_template('trial_page_bug')


@app.route('/trial_redirect_page_bug')
def trial_redirect_page_bug():
    "Trial redirects page specifies there is no validation for login"     
    return render_template('trial_redirect_page_bug.html')


@app.route('/retrive_wrong_data')
def retrive_wrong_data():
    "Trial page for practicing bug reports redirect with name and comments"        
    return render_template('retrive_wrong_data.html')
        

@app.route('/retrive_wrong_data_redirect_page',methods=['GET','POST'])
def retrive_wrong_data_redirect_page():
    "Trial redirects page specifies that retieved username and comments are not correct"
    db_file = os.path.join(os.path.dirname(__file__),'tmp','wisdomofreddit.db') #Create a variabe as db_file to create the DB file in the temp directory
    connection_obj = sqlite3.connect(db_file) #Connect to the db
    cursor_obj = connection_obj.cursor()
    if request.method == 'POST':
        user_name = request.form['submitname']
        user_comments = request.form['submitcomments']
        value = [user_name,user_comments]
        cursor_obj.execute("INSERT INTO comments VALUES (?,?)",value) #Insert values into the table. FYI comments table has already been created in the DB
        connection_obj.commit() #Save the changes
    results = cursor_obj.execute("SELECT * FROM comments") #Hold all the name and comments in a variable
    
    return render_template('retrive_wrong_data_redirect_page', results=results.fetchall())



#---START
if __name__=='__main__':
    app.run(host='0.0.0.0',port=6464)
