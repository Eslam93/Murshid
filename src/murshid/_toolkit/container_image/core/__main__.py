"""`python -m toolkit.container_image.core <file>`: exit 1 and one line per problem, or exit 0."""

from .check_dockerfile import main

raise SystemExit(main())
