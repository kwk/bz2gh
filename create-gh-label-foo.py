#!/usr/bin/env python3

from github import Github
import config

g = Github(config.GH_ACCESS_TOKEN)
repo = g.get_repo(config.GH_REPO)

print("Creating label \"foo\"")
repo.create_label(name="foo", description="bar", color="efefef")
