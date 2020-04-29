#!/usr/bin/env python3

import bugzilla
import github
import signal
import time
import sys
import logging


class GithubImporterFromBugzilla:
    """
    The GithubImporterFromBugzilla class let's you import Bugzilla bugs into
    a github repository.

    Bugs are fetched in batches from Bugzilla and then imported one by one into
    github. An import either creates a new issue in github or updates and
    existing issue.

    In Github you have much less fields to store values in. Essentially you only
    have a title, a description, comments, and labels.

    NOTE: Below we use the word "issue" and mean a github issue. "Bug" is the
          word we exclusively use for Bugzilla entries.

    For now a Bugzilla bug is mapped to a Github issue in the following way
    using the above mentioned fields:

    "bug_status":
    "resolution":
        The bug status and resolution are stored unmodified as lables in a
        github issue. These lables look like this "BZ-BUG-STATUS: RESOLVED"
        and "BZ-RESOLUTION: FIXED". At least you have one label for the
        "bug_status" field per github issue. At most you get two labels, one for
        "bug_status" and another for "resolution", but not always is a
        resolution available.

        If the "bug_status" is "RESOLVED", "CLOSED", or "VERIFIED" AND the
        resolution is "FIXED", "INVALID", "WONTFIX", "DUPLICATE", or
        "WORKSFORME", then an issue is closed.

        The state (closed/open) of a github issue depends on the the bugzilla
        "bug_status" and "resolution" fields. See also the documentation for the
        class variables "close_if_bug_status" and "close_if_resolution".

        If the calculated state (closed/open) of a github issue is different to
        what it was before, we will create a comment that indicates the
        state change and list the "bug_status" and "resolution" fields in that
        comment.

    "short_desc":
        The short description becomes the title of the new or updated issue in
        github.

    "product":
    "component":
        The product and component will be assigned as a "<product>/<component>"
        label.

    Every new or updated github issue will also get the labels assigned that
    you can find in the "additional_lables" class variable.

    For now we fill the "description" field of a new or updated github issue
    with this text:

    "This issue was imported from Bugzilla http://<BZURL>/show_bug.cgi?id=<ID>"

    After an issue is created or updated we make sure that is in a locked stated,
    if that's requested (see "lock_issues" class variable). The reason for the
    lock can also be specified (see "lock_reason" class variable).
    """

    # The state (closed/open) of a github issue depends on the the bugzilla
    # "bug_status" and "resolution" fields. A github issue is only closed if
    # the "bug_status" has one of these values AND one the resolution is one
    # of the below ones.
    close_if_bug_status = ["RESOLVED", "CLOSED", "VERIFIED"]
    close_if_resolution = ["FIXED", "INVALID",
                           "WONTFIX", "DUPLICATE", "WORKSFORME"]

    # Additional labels we will add to each new or updated github issue.
    additional_labels = ["dummy import from bugzilla"]

    # Set this to whatever logging level you prefer.
    log_level = logging.DEBUG

    # Set to "" if you prefer to not log output to a file
    log_file = "bz2gh.log"

    # Set to "" if you prefer to not log github requests to a file
    log_file_github_requests = "github-requests.log"

    # Set to False if you don't want issues to be locked.
    lock_issues = True

    # If "lock_issues" is True then we will lock all issues this reason.
    # Valid values are: "off-topic", "too heated", "resolved", "spam".
    # See also https://developer.github.com/v3/issues/#parameters-6.
    lock_reason = "too heated"

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
                             start_with, start_with+batch_size-1, batch_size)
            try:
                bugs = self.bzapi.getbugs(range(start_with, start_with + batch_size), extra_fields=[
                    "short_desc", "bug_status", "resolution", "product", "component"])
            except Exception as e:
                raise Exception("Failed to query for bugzillas %d to %d: %s",
                                start_with, start_with + batch_size-1, e)

            for bug in bugs:
                if bug == None:
                    self.logger.info("No more bugzillas to process")
                else:
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
                  "BZ-BUG-STATUS: %s" % bug.bug_status]
        if bug.resolution != "":
            labels.append("BZ-RESOLUTION: %s" % bug.resolution)
        labels.extend(self.additional_labels)

        body = "This issue was imported from Bugzilla %s." % bugzilla_bug_url
        title = bug.short_desc
        # Unfortunately github requires to specify a lock reason from a fixed list.
        # https://developer.github.com/v3/issues/#parameters-6
        # logic to decide if an issue is supposed to be closed or kept open.
        state = "open"
        if bug.bug_status in self.close_if_bug_status and bug.resolution in self.close_if_resolution:
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
        if self.lock_issues:
            if create_or_update == "create":
                self._retry_github_action(issue.lock, description="lock issue",
                                        lock_reason=self.lock_reason)
            else:
                if not issue.locked:
                    self._retry_github_action(issue.lock, description="lock issue",
                                            lock_reason=self.lock_reason)

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
