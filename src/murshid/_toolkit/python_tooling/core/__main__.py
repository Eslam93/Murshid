"""`python -m toolkit.python_tooling.core <file>`: exit 1 and one line per problem, or exit 0."""

from .check_tooling import main

raise SystemExit(main())
