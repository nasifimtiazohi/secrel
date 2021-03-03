import json 
import sql
import requests
import time
from dateutil import parser as dt
import logging, coloredlogs 
coloredlogs.install()

def getPackageId(package, ecosystem):
    ''' returns packageId if exists, else creates '''
    selectQ = 'select id from package where name=%s and ecosystem=%s'
    results = sql.execute(selectQ,(package,ecosystem))
    if not results:
        insertQ = 'insert into package values (null,%s,%s)'
        sql.execute(insertQ,(package,ecosystem))
        results = sql.execute(selectQ,(package,ecosystem))
    return results[0]['id']

def add_cve_publish_date():
    cves = 'select * from advisoryCVE where publish_date is null and state is null'
    results = sql.execute(cves)
    logging.info('%s cves need to be processed',len(results))

    for item in results:
        advisory_id = item['advisory_id']
        cve = item['cve']

        logging.info('fetching cve started: %s', cve)
        url='https://cve.circl.lu/api/cve/'+cve 
        response=requests.get(url)

        while response.status_code != 200 :
            logging.warning('failed cve response: %s', response.content)
            response=requests.get(url)
        
        data = json.loads(response.content)
        if not data:
            #REJECTED CVE
            updateQ = 'update advisoryCVE set state = %s where advisory_id = %s and cve = %s'
            sql.execute(updateQ,('rejected',advisory_id, cve))
            logging.info('fetching cve ended')
            continue 

        publishDate = dt.parse(data['Published'])
        updateQ = 'update advisoryCVE set publish_date = %s where advisory_id = %s and cve = %s'
        sql.execute(updateQ,(publishDate,advisory_id, cve))
        logging.info('fetching cve ended')
    
def addReferences(advisory):
    insertQ = 'insert into advisory_references values(%s,%s,%s)'
    advisoryId = advisory['vulId']

    for k in advisory['references'].keys():
        for url in advisory['references'][k]:
            try:
                sql.execute(insertQ,(advisoryId,k,url))
            except sql.pymysql.IntegrityError as error:
                if error.args[0] == sql.PYMYSQL_DUPLICATE_ERROR:
                    pass
                    #safely continue
                else:
                    print(error)
                    exit()
def addAdvisories(datafile):
    with open("../snyk/data/{}".format(datafile),"r") as read_file:
        advisories = json.load(read_file)

    for i,advisory in enumerate(advisories):
        logging.info('processing %dth data',i)
        try:
            selectQ = 'select * from advisory where id = %s'
            if not sql.execute(selectQ,(advisory['vulId'],)):
                insertQ = 'insert into advisory values (%s,%s,%s,%s,%s,%s,%s,%s,%s)'
                sql.execute(insertQ, (
                    advisory['vulId'],
                    advisory['vulType'],
                    getPackageId(advisory['package'],advisory['ecosystem']),
                    advisory['severity'],
                    advisory['score'],
                    advisory['vector'],
                    advisory['details'].get('Credit',None),
                    dt.parse(advisory['details']['Disclosed']),
                    dt.parse(advisory['details']['Published'])
                ))    

            if 'CVE' in advisory['details']:
                cve = advisory['details']['CVE']
                cves = cve.split('\n\n')
                for cve in cves:
                    selectQ = 'select * from advisoryCVE where advisory_id = %s and cve = %s'
                    if not sql.execute(selectQ,(advisory['vulId'],cve)):
                        q = 'insert into advisoryCVE values (%s,%s,null,null)'
                        sql.execute(q,(advisory['vulId'],cve))
            
            if 'CWE' in advisory['details']:
                cwe = advisory['details']['CWE']
                cwes = cwe.split('\n\n')
                for cwe in cwes:
                    selectQ = 'select * from advisoryCWE where advisory_id = %s and cwe = %s'
                    if not sql.execute(selectQ,(advisory['vulId'],cwe)):
                        q = 'insert into advisoryCWE values (%s,%s)'
                        sql.execute(q,(advisory['vulId'],cwe))

            selectQ = 'select * from advisory_versions where advisory_id = %s'
            if not sql.execute(selectQ,(advisory['vulId'],)):
                q = 'insert into advisory_versions values (%s,%s)'
                sql.execute(q,(advisory['vulId'],advisory['affected_versions']))
            else:
                q='update adviosry_versions set versions = %s where advisory_id = %s'
                sql.execute(q,(advisory['affected_versions'],advisory['vulId']))

            addReferences(advisory)

        except Exception as e:
            logging.info(advisory)
            print('Exception:', e)
            break

if __name__=='__main__':
    
    addAdvisories('snykMar2.json')
    add_cve_publish_date()