#!/usr/bin/env python3

import bugzilla
import github
import config

bzapi=bugzilla.Bugzilla(config.BZURL)
gh = github.Github(config.GH_ACCESS_TOKEN)
repo = gh.get_repo(config.GH_REPO)

issue_id=0
while True:
    issue_id += 1
    
    # Ensure an issue with this number does not yet exist in your github repo
    exists = True
    try:
        issue = repo.get_issue(issue_id)
    except github.UnknownObjectException:
        exists = False
    if exists:
        print("Skipping bugzilla %d because an issue with this number already exists within your github repository." % issue_id)
        continue

    # After this point the issue ID can be used
    bug = None
    try:
        bug = bzapi.getbug(issue_id)#(idlist=[issue_id])# include_fields=["id", "short_desc", "product", "component"])
    except Exception as e:
        print("failed to query for bugzilla %d: %s" % (issue_id, e))
        break
    
    imported_from_url = "%s/show_bug.cgi?id=%d" % (config.BZURL, issue_id)
    label = bug.product + "/" + bug.component
    body="This issue was imported from Bugzilla %s."
    print("Importing BZ %s" % imported_from_url)
    repo.create_issue(title=bug.short_desc, labels=[label, "dummy import from bugzilla"], body=body % imported_from_url)
    
    # Now lock the issue to prevent anything happening on this issue.
    # Unfortunately github requires to specify a lock reason from a fixed list. 
    # https://developer.github.com/v3/issues/#parameters-6
    issue = repo.get_issue(issue_id)
    issue.lock("too heated") 
    