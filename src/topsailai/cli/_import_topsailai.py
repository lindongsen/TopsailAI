import os
import sys

# Add the project source tree to sys.path so scripts in this directory can
# import the ``topsailai`` package.  This script lives at
# <repo-root>/src/topsailai/cli/_import_topsailai.py, so the source root is
# three levels up from here.
PROJECT_FOLDER_BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_FOLDER_BASE)

# fallback/backstop
if not os.path.exists(sys.path[0]):
    PROJECT_FOLDER = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    sys.path.insert(0, os.path.join(PROJECT_FOLDER, ".."))

