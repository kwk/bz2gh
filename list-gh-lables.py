#!/usr/bin/env python3

from github import Github
import config

g = Github(config.GH_ACCESS_TOKEN)
repo = g.get_repo(config.GH_REPO)

for label in repo.get_labels():
    print(label)