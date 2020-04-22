#!/usr/bin/env python3

import bugzilla
import config

bzapi=bugzilla.Bugzilla(config.BZURL)

# Uncomment to print what fields are available in the BZ installation
# print(bzapi.getbugfields())

bug = bzapi.getbug(1)

print("bug.short_desc: " + bug.short_desc)
print("bug.product: " + bug.product)
print("bug.component: " + bug.component)
