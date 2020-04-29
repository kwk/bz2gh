#!/usr/bin/env python3

import bugzilla
import github
import signal
import time
import sys
import logging


class GithubImporterFromBugzilla:

    # Set this to whatever logging level you prefer.
    log_level = logging.DEBUG

    # Set to "" if you prefer to not log output to a file
    log_file = "bz2gh.log"

    # Set to "" if you prefer to not log github requests to a file
    log_file_github_requests = "github-requests.log"

    # All logs will use this format
    log_format = "%(asctime)s [%(levelname)-7.7s]  %(message)s"

    # If you're using this class in a non-interactive setting, you should set
    # this to False.
    with_graceful_exithandler = True

    # The number of seconds to wait when all github API requests expired before
    # we check again if enough requests are available.
    #
    # NOTE: Github limits API requests per hour, aka 3600 seconds but you don't
    # have to wait that long before you're allowed to issue more requests.
    expire_wait_time = 300

    def __init__(self, bugzilla_url, github_access_token, github_repo):
        """
        Prepares the API to bugzilla and github and sets up logging.
        """
        self._setup_logging()

        if self.with_graceful_exithandler:
            self._original_sigint = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT, self._exit_gracefully)

        self.logger.info("Setting up bugzilla API %s", bugzilla_url)
        self.bugzilla_url = bugzilla_url
        self.bzapi = bugzilla.Bugzilla(bugzilla_url)

        self.logger.info("Setting up github API")
        self.github_access_token = github_access_token
        self.gh = github.Github(self.github_access_token)

        self.logger.info("Setting up github repo")
        self.github_repo = github_repo
        self.repo = self.gh.get_repo(self.github_repo)

        # Get remaining github API requests
        self.remaining_requests = 0
        self.remaining_requests = self.gh.get_rate_limit().core.remaining
        self.remaining_requests_last_refreshed = time.time()
        self.logger.debug("Remaining github API requests: %d",
                          self.remaining_requests)

    def _setup_logging(self):
        """
        Setup console logger and optionally file loggers for github request log.
        """
        self.logger = logging.getLogger("bz2gh")
        self.logger.setLevel(self.log_level)

        logFormatter = logging.Formatter(self.log_format)

        consoleHandler = logging.StreamHandler()
        consoleHandler.setFormatter(logFormatter)
        self.logger.addHandler(consoleHandler)

        if self.log_file != "":
            self.logger.info(
                "Log output will be appended to this file: %s", self.log_file)
            fileHandler = logging.FileHandler(self.log_file)
            fileHandler.setFormatter(logFormatter)
            self.logger.addHandler(fileHandler)

        if self.log_file_github_requests != "":
            self.logger.info(
                "Github requests will be appended to this file: %s", self.log_file_github_requests)
            ghlogger = logging.getLogger("github")
            ghlogger.setLevel(logging.DEBUG)
            ghFileHandler = logging.FileHandler(self.log_file_github_requests)
            ghFileHandler.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)-7.7s]  %(message)s\n"))
            ghlogger.addHandler(ghFileHandler)

    def import_from_bugzilla(self, start_with=0, batch_size=500):
        """
        Imports Bugzilla bugs in batches beginning with the one given by
        "start_with".
        """
        while True:
            bugs = []
            self.logger.info("Fetching bugzillas %d - %d (batch-size: %d)",
                             start_with, start_with+batch_size, batch_size)
            try:
                bugs = self.bzapi.getbugs(range(start_with, start_with + batch_size), extra_fields=[
                    "labels", "short_desc", "bug_status", "resolution", "product", "component"])
            except Exception as e:
                self.logger.error("Failed to query for bugzillas %d to %d: %s",
                                  start_with, start_with + batch_size, e)
                break

            for bug in bugs:
                if bug == None:
                    self.logger.info("No more bugzillas to process")
                else:
                    # logger.info("Processing Bugzilla %d - %s", bz.id, bz.short_desc)
                    self._import_bz(bug)

            start_with += batch_size

    def _exit_gracefully(self, signum, frame):
        """
        This is a CTRL+C (SIGINT) exit handler that will require confirmation
        before it exits the program.
        """
        # restore the original signal handler as otherwise evil things will happen
        # in input when CTRL+C is pressed, and our signal handler is not re-entrant
        signal.signal(signal.SIGINT, self._original_sigint)

        try:
            if input("\nReally quit? (y/n)> ").lower().startswith('y'):
                sys.exit(1)

        except KeyboardInterrupt:
            print("Ok ok, quitting")
            sys.exit(1)

        # restore the exit gracefully handler here
        signal.signal(signal.SIGINT, self._exit_gracefully)

    def _import_bz(self, bug):
        """
        Takes a given bugzilla bug creates a github issue or updates an already
        existing github issue with the same ID as the Bugzilla bug.
        """
        issue_id = bug.id

        # Decide if issue will be created or updated
        create_or_update = "create"
        issue = None
        self._ensure_enough_requests(1)
        try:
            issue = self.repo.get_issue(issue_id)
            create_or_update = "update"
            self.remaining_requests -= 1
        except github.UnknownObjectException:
            pass

        github_issue_url = "https://github.com/%s/issues/%d" % (
            config.GH_REPO, issue_id)
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
            self.logger.info("Creating github issue %s from BZ %s" %
                             (github_issue_url, bugzilla_bug_url))
            self._retry_github_action(self.repo.create_issue, description="create issue",
                                      title=title, labels=labels, body=body)
        else:
            current_labels = []
            for l in issue.labels:
                current_labels.append(l.name)
            if title != issue.title or body != issue.body or set(labels) != set(current_labels):
                self.logger.info("Updating github issue %s from BZ %s" %
                                 (github_issue_url, bugzilla_bug_url))
                self._retry_github_action(issue.edit, description="update issue",
                                          title=title, body=body, labels=labels)
            else:
                self.logger.info("Github issue %s already up to date with BZ from %s" % (
                    github_issue_url, bugzilla_bug_url))

        current_state = "open"
        if create_or_update == "update":
            current_state = issue.state

        # If the issue is new, we need to lock it later and here we're fetching the
        # issue repeatidly from github after we've just created it.
        if create_or_update == "create":
            issue = self._retry_github_action(
                self.repo.get_issue, description="get issue", number=issue_id)

        # Add a state change comment if the previous state was open and now is
        # closed or if it was closed and now is open.
        if state != current_state:
            state_change_comment = "issue because of bugzilla's bug state (%s) and resolution (%s)." % (
                bug.bug_status, bug.resolution)
            if state == "closed":
                state_change_comment = "Closing " + state_change_comment
            if state == "open":
                state_change_comment = "Re-opening " + state_change_comment
            self._retry_github_action(
                issue.create_comment, description="create state change comment", body=state_change_comment)
            self._retry_github_action(
                issue.edit, description="change issue state", state=state)

        # Now lock the issue to prevent anything happening on this issue.
        if create_or_update == "create":
            self._retry_github_action(issue.lock, description="lock issue",
                                      lock_reason=lock_reason)
        else:
            if not issue.locked:
                self._retry_github_action(issue.lock, description="lock issue",
                                          lock_reason=lock_reason)

    def _retry_github_action(self, func, description, max_retries=10, **kwargs):
        """
        Will run func() and retry for "max_retries" times if it fails. We wait
        for 0.8xi seconds, where is the number of retry.
        """
        start = time.time()
        i = 0
        while i < max_retries:
            i += 1
            try:
                self._ensure_enough_requests(1)
                res = func(**kwargs)
                self.remaining_requests -= 1
                end = time.time()
                self.logger.debug(
                    "github API request '%s' took %fs", description, end-start)
                return res
            except (github.GithubException, github.UnknownObjectException):
                self.logger.warning(
                    "Retrying github API request '%s' for at most %d more time(s)", description, max_retries - i)
                max_retries -= 1
                time.sleep(0.8*(i+1))
                pass
        self.logger.error(
            "Failed to retry github API request '%s'", description)
        raise Exception("Failed to retry github API request '%s'", description)

    def _ensure_enough_requests(self, num_requests=1):
        """
        If enough (>= num_requests) github API requests are remaining,
        this function will immediately return.

        After about every 1 minute, this function will refresh the information
        about how many github API requests are available. In between these true
        refreshes, we keep decreasing a counter for how many API requests are
        remaining. This is more than an estimate and not 100% correct.

        If the true number of remaining API requests is too low we will keep
        waiting for 300 
        """
        if self.remaining_requests > num_requests or (time.time() - self.remaining_requests_last_refreshed) < 60:
            return

        while self.remaining_requests <= num_requests:
            self.remaining_requests = self.gh.get_rate_limit().core.remaining
            self.remaining_requests_last_refreshed = time.time()
            self.logger.debug("Refreshed remaining github API request: %d remaining",
                              self.remaining_requests)
            if self.remaining_requests <= num_requests:
                self.logger.warning("Number of remaining github API requests is too low (%d). Waiting %fs until we can continue." % (
                    self.remaining_requests, self.expire_wait_time))
                time.sleep(self.expire_wait_time)


if __name__ == "__main__":
    # optionally start with Bug at a given ID
    start_with = 0
    if len(sys.argv) == 2:
        start_with = int(sys.argv[1])

    import config
    GithubImporterFromBugzilla.log_level = logging.DEBUG
    importer = GithubImporterFromBugzilla(
        bugzilla_url=config.BZURL, github_access_token=config.GH_ACCESS_TOKEN, github_repo=config.GH_REPO)
    importer.import_from_bugzilla(start_with=start_with, batch_size=500)
