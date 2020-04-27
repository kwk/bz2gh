#!/usr/bin/env python3

import bugzilla
import github
import config
import sys
import time
import logging

# Setup APIs to talk to bugzilla and github
bzapi = bugzilla.Bugzilla(config.BZURL)
gh = github.Github(config.GH_ACCESS_TOKEN)
repo = gh.get_repo(config.GH_REPO)

# Setup logging to file and to stdout/stderr
logger = logging.getLogger("bz2gh")
logger.setLevel(logging.DEBUG)

logFormatter = logging.Formatter("%(asctime)s [%(levelname)-5.5s]  %(message)s")
fileHandler = logging.FileHandler("bz2gh.log")
fileHandler.setFormatter(logFormatter)
logger.addHandler(fileHandler)

consoleHandler = logging.StreamHandler()
consoleHandler.setFormatter(logFormatter)
logger.addHandler(consoleHandler)

# Log all github requests made into github-requests.log
ghlogger = logging.getLogger("github")
ghlogger.setLevel(logging.DEBUG)
ghFileHandler = logging.FileHandler("github-requests.log")
ghFileHandler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)-5.5s]  %(message)s\n"))
ghlogger.addHandler(ghFileHandler)

# Get remaining github requests once and later check and update it but work
# with estimated numbers from here on.
remaining_requests = gh.get_rate_limit().core.remaining
remaining_requests_last_refreshed = time.time()
logger.debug("Remaining github requests: %d", remaining_requests)

issue_id = 0
# optionally start at a given id
if len(sys.argv) == 2:
    issue_id = int(sys.argv[1]) - 1

def retry_github_action(func, type, max_retries=10, **kwargs):
    while max_retries > 0:
        try:
            res = func(**kwargs)
            return res
        except github.GithubException:
            logger.warn("Retrying github '%s' call for at most %d more time(s)", type, max_retries)
            max_retries -= 1
            pass

while True:
    issue_id += 1

    # At most we will do 6 queries when we import into a github issue.
    # Make sure, that our rate limit is high enough.
    min_num_req = 6
    if remaining_requests <= min_num_req or (time.time() - remaining_requests_last_refreshed) > 60:
        while True:
            remaining_requests = gh.get_rate_limit().core.remaining
            remaining_requests_last_refreshed = time.time()
            logger.debug("Refreshed remaining github request: %d remaining", remaining_requests)
            if remaining_requests <= min_num_req:
                seconds_to_wait = 300
                logger.warn("Number of remaining Github requests is too low (%d). Waiting %fs until we can continue." % (remaining_requests, seconds_to_wait))
                time.sleep(seconds_to_wait)
            else:
                break

    # To avoid calculating the remaining requests every time, we manually decrease them
    remaining_requests -= 6

    # Make sure the bug exists in bugzilla (if not, we'll stop right here)
    bug = None
    try:
        bug = bzapi.getbug(issue_id)
    except Exception as e:
        print("failed to query for bugzilla %d: %s" % (issue_id, e))
        break

    # Decide if issue will be created or updated
    create_or_update = "create"
    issue = None
    try:
        issue = repo.get_issue(issue_id)
        create_or_update = "update"
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
    # Unfortunately github requires to specify a lock reason from a fixed list.
    # https://developer.github.com/v3/issues/#parameters-6
    lock_reason = "too heated"
    # logic to decide if an issue is supposed to be closed or kept open.
    state = "open"
    if bug.bug_status == "RESOLVED" or bug.status == "CLOSED" or bug.status == "VERIFIED":
        if bug.resolution == "FIXED" or bug.resolution == "INVALID" or bug.resolution == "WONTFIX" or bug.resolution == "DUPLICATE" or bug.resolution == "WORKSFORME":
            state = "closed"

    if issue == None:
        logger.info("Creating github issue https://github.com/%s/issues/%d from BZ %s" % (config.GH_REPO, issue_id, imported_from_url))
        retry_github_action(repo.create_issue, type="create issue", title=title, labels=labels, body=body)
    else:
        current_labels = []
        for l in issue.labels:
            current_labels.append(l.name)
        if title != issue.title or body != issue.body or set(labels) != set(current_labels):
            logger.info("Updating github issue https://github.com/%s/issues/%d from BZ %s" % (config.GH_REPO, issue_id, imported_from_url))
            retry_github_action(issue.edit, type="update issue", title=title, body=body, labels=labels)
        else:
            logger.info("Github issue https://github.com/%s/issues/%d already up to date with BZ from %s" % (config.GH_REPO, issue_id, imported_from_url))

    current_state = "open"
    if create_or_update == "update":
        current_state = issue.state

    # If the issue is new, we need to lock it later and here we're fetching the
    # issue repeatidly from github after we've just created it.
    if create_or_update == "create":
        issue = retry_github_action(repo.get_issue, type="get issue", number=issue_id)

    # Add a state change comment if the previous state was open and now is 
    # closed or if it was closed and now is open.
    if state != current_state:
        state_change_comment = "issue because of bugzilla's bug state (%s) and resolution (%s)." % (bug.bug_status, bug.resolution)
        if state == "closed":
            state_change_comment = "Closing " + state_change_comment
        if state == "open":
            state_change_comment = "Re-opening " + state_change_comment
        retry_github_action(issue.create_comment, type="create state change comment", body=state_change_comment)
        retry_github_action(issue.edit, type="change issue state", state=state)

    # Now lock the issue to prevent anything happening on this issue.
    if create_or_update == "create":
        retry_github_action(issue.lock, type="lock issue", lock_reason=lock_reason)
    else:
        if not issue.locked:
            retry_github_action(issue.lock, type="lock issue", lock_reason=lock_reason)
