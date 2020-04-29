#!/usr/bin/env python3

import bugzilla
import github
import config
import sys
import time
import logging

# Setup logging to file and to stdout/stderr
logger = logging.getLogger("bz2gh")
logger.setLevel(logging.DEBUG)

logFormatter = logging.Formatter("%(asctime)s [%(levelname)-7.7s]  %(message)s")
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
ghFileHandler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)-7.7s]  %(message)s\n"))
ghlogger.addHandler(ghFileHandler)


# Setup APIs to talk to bugzilla and github
bzapi = bugzilla.Bugzilla(config.BZURL)
gh = github.Github(config.GH_ACCESS_TOKEN)
repo = gh.get_repo(config.GH_REPO)

# Get remaining github requests once and later check and update it but work
# with estimated numbers from here on.
remaining_github_api_requests = 0
remaining_github_api_requests = gh.get_rate_limit().core.remaining
remaining_github_api_requests_last_refreshed = time.time()
logger.debug("Remaining github API requests: %d", remaining_github_api_requests)

def ensure_enough_requests(ask_for_num_requests=1):
    global remaining_github_api_requests
    global remaining_github_api_requests_last_refreshed
    if remaining_github_api_requests > ask_for_num_requests or (time.time() - remaining_github_api_requests_last_refreshed) < 60:
        return
    
    while True:
        remaining_github_api_requests = gh.get_rate_limit().core.remaining
        remaining_github_api_requests_last_refreshed = time.time()
        logger.debug("Refreshed remaining github API request: %d remaining", remaining_github_api_requests)
        if remaining_github_api_requests <= ask_for_num_requests:
            seconds_to_wait = 300
            logger.warning("Number of remaining github API requests is too low (%d). Waiting %fs until we can continue." % (remaining_github_api_requests, seconds_to_wait))
            time.sleep(seconds_to_wait)
        else:
            return

def retry_github_action(func, type, max_retries=10, **kwargs):
    global remaining_github_api_requests
    i = 0
    while i < max_retries:
        i += 1
        try:
            ensure_enough_requests(1)
            res = func(**kwargs)
            remaining_github_api_requests -= 1
            return res
        except (github.GithubException, github.UnknownObjectException):
            logger.warning("Retrying github '%s' call for at most %d more time(s)", type, max_tries - i)
            max_retries -= 1
            time.sleep(0.8*(i+1))
            pass
    logger.error("Failed to retry ")
    raise Exception("")

def import_bz(bug):
    global bzapi
    global gh
    global logger
    global repo
    global remaining_github_api_requests

    issue_id = bug.id

    # Decide if issue will be created or updated
    create_or_update = "create"
    issue = None
    ensure_enough_requests(1)
    try:
        issue = repo.get_issue(issue_id)
        create_or_update = "update"
        remaining_github_api_requests -= 1
    except github.UnknownObjectException:
        pass

    github_issue_url = "https://github.com/%s/issues/%d" % (config.GH_REPO, issue_id)
    bugzilla_bug_url = "%s/show_bug.cgi?id=%d" % (config.BZURL, issue_id)

    # Prepare values for github issue
    labels = [bug.product + "/" + bug.component,
            "dummy import from bugzilla",
            "BZ-BUG-STATUS: %s" % bug.bug_status]
    if bug.resolution != "":
        labels.append("BZ-RESOLUTION: %s" % bug.resolution)

    body = "This issue was imported from Bugzilla %s." % bugzilla_bug_url
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
        logger.info("Creating github issue %s from BZ %s" % (github_issue_url, bugzilla_bug_url))
        retry_github_action(repo.create_issue, type="create issue", title=title, labels=labels, body=body)
    else:
        current_labels = []
        for l in issue.labels:
            current_labels.append(l.name)
        if title != issue.title or body != issue.body or set(labels) != set(current_labels):
            logger.info("Updating github issue %s from BZ %s" % (github_issue_url, bugzilla_bug_url))
            retry_github_action(issue.edit, type="update issue", title=title, body=body, labels=labels)
        else:
            logger.info("Github issue %s already up to date with BZ from %s" % (github_issue_url, bugzilla_bug_url))
    
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

if __name__ == "__main__":
    # optionally start at a given id
    start_with = 0
    if len(sys.argv) == 2:
        start_with = int(sys.argv[1])

    # optionally fetch BZs in batches
    batch_size = 100
    if len(sys.argv) == 3:
        batch_size = int(sys.argv[2])
    logger.info("Fetching bugzilla bugs in batches of %d bugs", batch_size)

    while True:
        bz_batch = []
        try:
            bz_batch = bzapi.getbugs(range(start_with, start_with + batch_size), extra_fields=["labels", "short_desc", "bug_status", "resolution", "product", "component"])
        except Exception as e:
            logger.error("Failed to query for bugzillas %d to %d: %s", start_with, start_with + batch_size, e)
            break

        for bz in bz_batch:
            if bz == None:
                logger.info("No more bugzillas to process")
            else:
                # logger.info("Processing Bugzilla %d - %s", bz.id, bz.short_desc)
                import_bz(bz)
        
        start_with += batch_size
