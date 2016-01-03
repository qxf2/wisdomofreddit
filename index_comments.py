"""
Index comments within a csv file. 

Current behavior:
a) Accepts index name as optional command line argument
b) By default creates index in the ./index directory relative to this file
c) Will not create an index unless command line parameter is true
"""

import os,csv,re,time
from optparse import OptionParser
from whoosh import index
from whoosh.fields import Schema, ID, TEXT, NUMERIC
from whoosh.analysis import StemmingAnalyzer


def get_schema():
    "Return the schema"
    schema = Schema(url=TEXT(stored=True), 
                    comment=TEXT(stored=True,analyzer=StemmingAnalyzer()),
                    score=NUMERIC(stored=True),
                    created=TEXT(stored=True),
                    subreddit=TEXT(stored=True),
                    parent=TEXT(stored=True),
                    gilded=NUMERIC(stored=True),
                    name=TEXT(stored=True)
                    )
 
    return schema


def create_index(index_dir,schema,index_name):
    "Create a new index"
    if not os.path.exists(index_dir):
        os.mkdir(index_dir)
    ix = index.create_in(index_dir,schema=schema,indexname=index_name)
    ix = open_index(index_dir,index_name)

    return ix


def open_index(index_dir,index_name):
    "Open a given index"
    return index.open_dir(index_dir,indexname=index_name)


def get_index(index_dir,schema,index_name,new_index_flag):
    "Get the index handler object"
    if new_index_flag.lower()=='true':
        ix = create_index(index_dir,schema,index_name)
    else:
        ix = open_index(index_dir,index_name)

    return ix


def pre_process_csv(csvfile):
    "Pre-process the CSV file"
    #a. remove new lines that are not needed
    #b. remove non ASCII character
    #c. remove empty lines
    #d. remove header line
    print "Pre-processing csv file ..."
    header_row = ['link_id','id','score','body','name','created_utc','subreddit','parent_id','gilded']
    clean_lines = []
    fp = open(csvfile,'rb')
    lines = fp.read().splitlines()
    fp.close()
    current_line = ''
    for line in lines:
        if line.strip() == '':
            continue
        if line.split(',') == header_row:
            continue
        line = re.sub(r'[^\x00-\x7F]+',' ', line)
        line = line.strip()
        if len(line)>3:
            if line[0:3] == 't3_':#Check if it is a new row
                if current_line != '':
                    clean_lines.append(current_line)
                current_line = line
            else: #If not new row, stitch to current line
                current_line += ' ' + line
        else:
            current_line += ' ' + line

    clean_lines.append(current_line)

    return clean_lines


def update_index(csvfile,index_name=None,new_index_flag='false'):
    "Create or update an index with the data in the csvfile"
    csvfile = os.path.abspath(csvfile)
    csvfile_exists = os.path.exists(csvfile)
    if csvfile_exists:
        line_count = 0
        schema = get_schema()
        index_dir = os.path.join(os.path.dirname(__file__),'indexdir')
        if not os.path.exists(index_dir):
            os.mkdir(index_dir)
        ix = get_index(index_dir,schema,index_name,new_index_flag)
        writer = ix.writer()
        my_csv = pre_process_csv(csvfile)
        line_count += 1
        my_reader = csv.reader(my_csv,delimiter=',',quotechar='"')
        print 'About to index the file'
        for row in my_reader:
            line_count += 1
            if len(row) != 9:
                print 'Error in file. Row is malformed'
                print 'Offending row:',row
                continue
            #print 'About to process: ',row[0],row[1],row[2],row[3][0:140]
            #1. URL
            url = 'http://www.reddit.com/comments/%s/x/%s'%(row[0].split('t3_')[-1],row[1])
            url = unicode(url,errors='ignore')
            #2. Comment
            comment = unicode(row[3],errors='ignore')
            #3. Score
            try:
                score = int(row[2])
            except Exception,e:
                print 'Unable to process score: ',row[2]
                score = 35
            #4. Created
            created = unicode(row[5])
            #5. Subreddit
            subreddit = unicode(row[6])
            #6. Parent
            parent = unicode(row[7].split('_')[-1])
            #7. Gilded
            try:
                gilded = int(row[8])
            except Exception,e:
                print 'Unable to process gilded: ',row[8]
                gilded = 0
            #8. Name
            name = unicode(row[4])
            writer.add_document(url=url,
                                comment=comment,
                                score=score,
                                created=created,
                                subreddit=subreddit,
                                parent=parent,
                                gilded=gilded,
                                name=name)
            if line_count%200 == 0:
                print '.',
        writer.commit()
    else:
        print 'Unable to locate the csv file: ',csvfile


#---START OF SCRIPT
if __name__=='__main__':
    start_time = time.time()
    print "Script start"
    usage = "\n----\n%prog -f csv file to be indexed -n <OPTIONAL: Index name> -c <OPTIONAL: Create new index> \n----\nE.g.: %prog -n wor -c True \n---"
    parser = OptionParser(usage=usage)
    
    parser.add_option("-f","--filename",
                      dest="csvfile",
                      help="Path of the csv file you want indexed")
    parser.add_option("-n","--indexname",
                      dest="index_name",
                      help="Name of the index you want to use")
    parser.add_option("-c","--newindex",
                      dest="new_index_flag",
                      default="false",
                      help="Create a new index?")
    parser.add_option("-d","--directory",
                      dest="csv_dir",
                      help="Directory with csvs to be indexed")
    (options,args) = parser.parse_args()

    if options.csv_dir is not None:
        for my_file in os.listdir(os.path.abspath(options.csv_dir)):
            my_file = os.path.abspath(options.csv_dir) + os.sep + my_file
            if os.path.isfile(my_file) is True:
                print 'About to index file: ',my_file.split(os.sep)[-1]
                update_index(my_file,
                             index_name=options.index_name,
                             new_index_flag=options.new_index_flag)
                options.new_index_flag = 'false'
    else:
        update_index(options.csvfile,
                     index_name=options.index_name,
                     new_index_flag=options.new_index_flag)
    duration = int(time.time()-start_time)
    print 'Duration: %d'%duration
