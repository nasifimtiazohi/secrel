from typing import OrderedDict
import common, sql
import os, json
import subprocess, shlex
from dateutil import parser as dt
import dateutil
from bs4 import BeautifulSoup as BS
import pandas as pd
import requests
import logging, coloredlogs
coloredlogs.install()
import time
ecosystem = 'Go'
import git_analysis as ga
from maven_version import MavenVersion
from multiprocessing import Pool
import semver

def isValidVersion(v):
    try:
        v = semver.VersionInfo.parse(v)
        return True
    except:
        return False

def get_repository_url(package):
    repository = None
    
    url = 'https://pkg.go.dev/{}'.format(package)
    page = requests.get(url)
    
    soup = BS(page.content, 'html.parser')
    elems = soup.findAll("div",class_='UnitMeta')
    if not elems:
        repository = common.norepo
    else:
        assert len(elems) == 1
        soup = elems[0]
        links = soup.findAll("a")
        assert len(links) == 1
        repository = (links[0].text).strip()
    
    return repository

def get_release_info(package,version, repo_url):
    prior_release = release_date = None 
    releases = ga.get_all_tags(package_id, repo_url)
    candidate_tags = []
    for k in releases.keys():
        if k.endswith(version):
            candidate_tags.append(k)
    if len(candidate_tags) == 1:
        release_date =  releases[candidate_tags[0]]['tag_date'].astimezone(dateutil.tz.tzutc())

    return release_date, prior_release


def pr_mp(item):
    release_id, package_id, version, repo_url = item['id'], item['package_id'], item['version'], item['repository_url']
    print(release_id, package_id, version, repo_url)
    conn = sql.create_db_connection()
    
    releases = ga.get_all_tags(package_id, repo_url)
    candidate_tags, final_tag = [], None
    
    for k in releases.keys():
        if k.endswith(version):
            candidate_tags.append(k)

    if len(candidate_tags) == 1:
        final_tag = candidate_tags[0]

    if final_tag:
        tags = list(sorted(releases, key = lambda k: releases[k]['tag_date']))
        idx = tags.index(final_tag)
        prior_release = tags[idx-1]
        if prior_release.startswith('kubernetes-'):
            prior_release = prior_release[len('kubernetes-'):]
        if prior_release.startswith('v'):
            prior_release =  prior_release[1:] 
        for (i,v) in enumerate(tags):
            if v.startswith('v'):
                tags[i] = v[1:]
            if v.startswith('kubernetes-'):
                v = v[len('kubernetes-'):]
        
        if not isValidVersion(version) or not isValidVersion(prior_release):
            logging.info('a not valid semver formatting')
            prior_release = 'not valid semver formatting'
            sql.execute('update release_info set prior_release=%s where id=%s',(prior_release,release_id), connection=conn)
            return
        
        if prior_release.split('.')[0] != version.split('.')[0]:
            try:
                if (ga.parse_release_type(version) == 'major' and (int(version.split('.')[0]) - int(prior_release.split('.')[0])==1)):
                    logging.info('major version release')
                    print(version, prior_release, repo_url)
                else:
                    a = semver.VersionInfo.parse(version)
                    b = semver.VersionInfo.parse(prior_release)
                    # can be prerelease to major
                    if (a.major == b.major and a.minor ==b.minor and a.patch == b.patch):
                        logging.info('no problem')
                        print(version, prior_release, repo_url)
                    else:
                        temp = get_prior_release_from_semver_ordering(tags, final_tag)
                        if temp:
                            prior_release = temp
                        else:
                            split = [int(k) for k in version.split('.')]
                            if split[2] > 0:
                                candidate = '{}.{}.{}'.format(split[0], split[1], split[2]-1)
                                if candidate in tags:
                                    prior_release = candidate
                                    print(version, prior_release, repo_url)
                                else:
                                    logging.info('c not valid semver formatting')
                sql.execute('update release_info set prior_release=%s where id=%s',(prior_release,release_id), connection=conn)
            except:
                logging.info('what happened')
                print(version, prior_release, repo_url)
                return
        
        elif prior_release.split('.')[1] != version.split('.')[1]:
            try:
                if ga.parse_release_type(version) == 'minor' and (int(version.split('.')[1]) - int(prior_release.split('.')[1])==1):
                    logging.info('minor version release')
                    print(version, prior_release, repo_url)
                else:
                    temp = get_prior_release_from_semver_ordering(tags, final_tag)
                    if temp:
                        prior_release = temp
                    else:
                        split = [int(k) for k in version.split('.')]
                        if split[2] > 0:
                            candidate = '{}.{}.{}'.format(split[0], split[1], split[2]-1)
                            if candidate in tags:
                                prior_release = candidate
                                print(version, prior_release, repo_url)
                            else:
                                logging.info('c not valid semver formatting')
                                prior_release = 'not valid semver formatting'
                sql.execute('update release_info set prior_release=%s where id=%s',(prior_release,release_id), connection=conn)
            except:
                logging.info('c what happened')
                print(version, prior_release, repo_url)
                return
        
        else:
            print(version, prior_release)
            a = semver.VersionInfo.parse(version)
            b = semver.VersionInfo.parse(prior_release)
            # semver library cannot compare prerelease accurately
            if ( a > b ) or (a.major == b.major and a.minor ==b.minor and a.patch == b.patch):
                logging.info('no problem')
                print(version, prior_release, repo_url)
            else:
                temp = get_prior_release_from_semver_ordering(tags, final_tag)
                if temp:
                    prior_release = temp
                else:
                    logging.info('d not valid semver formatting')
                    prior_release = 'not valid semver formatting'
            sql.execute('update release_info set prior_release=%s where id=%s',(prior_release,release_id), connection=conn)

def get_prior_release():
    q='''select *
        from release_info ri
        join package p on ri.package_id = p.id
        where ecosystem = 'Go'
        -- and prior_release is null
        and publish_date is not null
        and prior_release = 'not valid semver formatting' '''
    results = sql.execute(q)

    pool = Pool(os.cpu_count())
    pool.map(pr_mp, results)

def get_prior_release_from_semver_ordering(tags, version_tag):
    try:
        tags.sort(key=semver.compare)
        idx = tags.index(version_tag)
        prior_release = tags[idx-1]
        return prior_release
    except:
        return None
        
if __name__ == '__main__':
    get_prior_release()
    # #get repository remote url of packages
    # packages = common.getPackagesToSearchRepository(ecosystem)
    # for item in packages:
    #     id, repo = item['id'], get_repository_url(item['name'])
    #     print(item['name'],repo)
    #     sql.execute('update package set repository_url=%s where id = %s',(repo,id))
    
    # #get release info (publish date and prior release) for each fixing release
    # packages = common.getPackagesToProcessRelease(ecosystem)
    # for item in packages:
    #     package_id, package, version, repo_url = item['package_id'], item['package'], item['version'], item['repo_url']
    #     print(repo_url)
    #     publish_date, prior_release = get_release_info(package,version, repo_url)
    #     print(package, package_id, version, publish_date, prior_release)
    #     sql.execute('insert into release_info values(null,%s,%s,%s,%s)',(package_id, version, publish_date, prior_release))