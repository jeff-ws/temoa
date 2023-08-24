This file location is only to support the current setup for temoa_myopic runs which use this file location
to store the run statements needed.

Running the myopic tests is currently hard-coded to use this folder name, so it (currently) should not be changed and
the config file herein is dynamically generated/updated by running the test suite.

This folder includes the necessary sqlite databases to run the tests, which are currently (unfortunately) part of the
git repo as a convenience.  Eventually, they should be removed from VCS to prevent bloat.