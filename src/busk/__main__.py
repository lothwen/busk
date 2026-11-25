"""Allow ``python -m busk``, equivalent to the ``busk`` console script."""

import sys

from busk.launch import main

sys.exit(main())
