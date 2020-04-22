#!/usr/bin/env python3

import bugzilla
from github import Github
import random
import config

g = Github(config.GH_ACCESS_TOKEN)
bzapi = bugzilla.Bugzilla(config.BZURL)
repo = g.get_repo(config.GH_REPO)

for product in bzapi.products:
    print(product['name'] + " - " + product['description'])
    # random color code (without # prefix) to be assigned to product labels and
    # all their components
    color = ''.join([random.choice('0123456789ABCDEF') for j in range(6)])
    repo.create_label(name=product['name'], description=product['description'], color=color)
    for component in product['components']:
        print(" - " + product['name'] + "/" + component['name'])
        repo.create_label(name=product['name']+"/"+component['name'], color=color)


# This should print something like this where each line corresponds to a label.
# The onese indented with - share the same color as their parent label for
# visual grouping of labels.
#
#   $ time ./create-gh-labels-from-bz-components.py 
#   Bugzilla Admin - Things we want to do to enhance our Bugzilla experience.
#   - Bugzilla Admin/Mail
#   - Bugzilla Admin/Products
#   - Bugzilla Admin/UI
#   Build scripts - CMake, Makefiles and autoconf
#   - Build scripts/autoconf
#   - Build scripts/cmake
#   - Build scripts/Makefiles
#   DSA - The Data Structure Analysis project.
#   - DSA/New Bugs
#   Documentation - The documentation for the LLVM system.
#   - Documentation/Doxygen
#   - Documentation/General docs
#   LNT - The LLVM performance tracking software.
#   - LNT/LNT
#   MLIR - https://mlir.llvm.org/
#   - MLIR/Affine Dialect
#   - MLIR/Core
#
#   ...
#
#   - tools/lto
#   - tools/opt
#   - tools/opt-viewer
#   - tools/support scripts
#   - tools/TableGen
#
#   real    1m28.478s
#   user    0m2.425s
#   sys     0m0.115s