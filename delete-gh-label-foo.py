#!/usr/bin/env python3

from github import Github
import config

g = Github(config.GH_ACCESS_TOKEN)
repo = g.get_repo(config.GH_REPO)

print("Deleting label foo")
repo.get_label("foo").delete()
