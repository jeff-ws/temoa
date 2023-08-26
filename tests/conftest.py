import logging
import os

from definitions import PROJECT_ROOT

# set up logger in conftest.py so that it is properly anchored in the test folder.

# set the target folder for output from testing
output_path = os.path.join(PROJECT_ROOT, "tests", "test_log")
if not os.path.exists(output_path):
    os.mkdir(output_path)

logging.getLogger("pyomo").setLevel(logging.INFO)
filename = "testing.log"
logging.basicConfig(
    filename=os.path.join(output_path, filename),
    filemode="w",
    format="%(asctime)s | %(module)s | %(levelname)s | %(message)s",
    datefmt="%d-%b-%y %H:%M:%S",
    level=logging.DEBUG,  # <-- global change for testing activities is here
)