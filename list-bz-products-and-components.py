#!/usr/bin/env python3

import bugzilla
import config

bzapi=bugzilla.Bugzilla(config.BZURL)

for product in bzapi.products:
    print(product['name'] + " - " + product['description'])
    for component in product['components']:
        print(" - " + product['name'] + "/" + component['name'])

