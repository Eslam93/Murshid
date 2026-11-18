"""`python -m toolkit.ci_workflow.core [workflow...]`: exit 1 and a line per problem, or 0."""

from .check_workflow import main

raise SystemExit(main())
