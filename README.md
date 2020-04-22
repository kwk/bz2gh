
# Background 

I've written this code in order to help with the migration from bugzilla bugs to
github issues for the LLVM project
(see http://lists.llvm.org/pipermail/llvm-dev/2020-April/141096.html).

My idea was this:

1. Stop creation of new bugzilla entries and only allow edits of existing ones.
2. Have a fresh github repo with no issues AND no pull requests inside it so
   that we can assure an easy mapping between bugzilla bug numbers and github
   issues. NOTE: github shares one number pool for pull requests and issues
3. Delete all labels in your github import repository: `delete-all-gh-labels.sh`
4. Create labels as a combination of `<BZPRODUCT>/<BZCOMPONENT>` in your github
   repository: `create-gh-labels-from-bz-components.py`. While you not
   necessarily have to create the labels upfront before importing issues into
   github, I suggest to create them upfront, so can group them by color.
5. Import bugzilla bugs as placeholder issues into your github repository using
   `create-gh-placeholder-issues-from-bz-bugs.py`. This will do a few things:

   1. Beginning with bugzilla bug #1 it will check if there's a github issue
      with the same number. If there is none, it will

      1. create a github issue with the title being the short description of
         the bugzilla. The description is a text that points you to the original
         bugzilla.
      2. add label "dummy import from bugzilla" and "<BZPRODUCT>/<BZCOMPONENT>".
      3. lock the issue to avoid anything happening on the github issue
         (afterall the issue is a placeholder issue until more import work is
         happening).
      3. Do the same with bugzilla #2 and so on.
   
   If `create-gh-placeholder-issues-from-bz-bugs.py` for some reasons fails,
   you can run it again to pull in new bugzillas from where it left of.
   It skips existing github issues.


## Example

If you want to see the result of my LLVM bugzilla import, you can find it here:

https://github.com/kwk/test-llvm-bz-import-4

### Imported labels:

All the labels that have been created, can be found here:

https://github.com/kwk/test-llvm-bz-import-4/labels

### Imported bugzillas

You can find all imported bugzillas by their special label
`dummy import from bugzilla` here:

https://github.com/kwk/test-llvm-bz-import-4/labels/dummy%20import%20from%20bugzilla


# Installation

## Prerequisites

You have to have two python libraries installed, one for github and one for
bugzilla access. On Fedora 31 you can install them using the following command: 

```bash
sudo dnf -y install python3-bugzilla python3-pygithub
```

## Get the code

Get the code and execute the helper scripts from within the folder:

```bash
git clone https://github.com/kwk/bz2gh.git
```

## Configuration

The scripts assume that you have configured a `config.py` file. This file
specifies to which bugzilla instance to connect and to which github repo.
We will do that once we've setup everything we need.

### Create import repository

I encourage you to try out the repository first by going to
https://github.com/new and creating a new repository there. Let's give it the
name `<YOURUSERNAME>/test-bz-import-1`.

### Create a Personal access token

Go to https://github.com/settings/tokens/new in order to create a new Personal
access token. and check these boxes it these permissions:

- [x] repo
- [x] write:discussion

### Create `config.py`

To avoid accidental versioning of personal access tokens, I haven't put the file
`config.py` under version control. I suggest you do this in order to have your
own file to modify:

```bash
cp config.py.orig config.py
```

Then fill out the details in `config.py`.

# Usage

After you've completed the configuration you can mostly guess what each script
does by it's name. I suggest you start fiddling with those scripts that
evidently only get things but do not modify them (e.g. `list-...py`,
`show-...py`).

