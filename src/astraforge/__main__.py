"""Allow ``python -m astraforge`` as well as the ``astraforge`` script.

Useful when the package is installed but its console script is not on PATH,
which is the common case inside a non-activated virtualenv or a container.
"""

from astraforge.cli.main import main

if __name__ == "__main__":
    main()
