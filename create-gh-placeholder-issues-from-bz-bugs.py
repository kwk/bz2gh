#!/usr/bin/env python3

import bugzilla
import github
import config
import sys

bzapi = bugzilla.Bugzilla(config.BZURL)
gh = github.Github(config.GH_ACCESS_TOKEN)
repo = gh.get_repo(config.GH_REPO)

issue_id = 0
# optionally start at a given id
if len(sys.argv) == 2:
    issue_id = int(sys.argv[1]) - 1

while True:
    issue_id += 1

    # Make sure the bug exists in bugzilla (if not, we'll stop right here)
    bug = None
    try:
        # (idlist=[issue_id])# include_fields=["id", "short_desc", "product", "component"])
        bug = bzapi.getbug(issue_id)
    except Exception as e:
        print("failed to query for bugzilla %d: %s" % (issue_id, e))
        break

    # Decide if issue will be created or updated
    issue = None
    try:
        issue = repo.get_issue(issue_id)
    except github.UnknownObjectException:
        pass

    # Prepare values for github issue
    imported_from_url = "%s/show_bug.cgi?id=%d" % (config.BZURL, issue_id)
    labels = [bug.product + "/" + bug.component,
              "dummy import from bugzilla",
              "BZ-BUG-STATUS: %s" % bug.bug_status]
    if bug.resolution != "":
        labels.append("BZ-RESOLUTION: %s" % bug.resolution)

    body = "This issue was imported from Bugzilla %s." % imported_from_url
    title = bug.short_desc
    # logic to decide if an issue is supposed to be closed or kept open.
    state = "open"
    resolution_switcher = {
        "FIXED": "closed",
        "INVALID": "closed",
        "WONTFIX": "closed",
        "LATER": "open",
        "REMIND": "open",
        "DUPLICATE": "open",
        "WORKSFORME": "open",
        "MOVED": "open"
    }
    if bug.bug_status == "RESOLVED" or bug.status == "CLOSED":
        if resolution_switcher.get(bug.resolution, "closed") == "closed":
            state = "closed"

    if issue == None:
        print("Importing BZ from %s" % imported_from_url)
        repo.create_issue(title=title, labels=labels, body=body)
        issue = repo.get_issue(issue_id)
    else:
        print("Updating BZ from %s" % imported_from_url)
        issue.edit(title=title, body=body, labels=labels, state=state)

    # Now lock the issue to prevent anything happening on this issue.
    # Unfortunately github requires to specify a lock reason from a fixed list.
    # https://developer.github.com/v3/issues/#parameters-6
    issue.lock("too heated")
