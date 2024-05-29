"""
this is a placeholder that shows that something (IamDataFrame) inside of
make_excel is causing a logging issue where stuff isn't making it to log due to some
kooky failure with that module in pyam

"""

# TODO:  Restore this after getting the pyam import squared away.

# from temoa.data_processing.DB_to_Excel import make_excel
#
# # Written by:  J. F. Hyink
# # jeff@westernspark.us
# # https://westernspark.us
# # Created on:  11/26/23
#
# logger = logging.getLogger(__name__)
#
# me = make_excel
#
#
# def test_log_entry(caplog):
#     # will NOT show up in logfile...  :(
#     logger.warning('Effective Logging!')
#     assert 'Effective Logging!' in caplog.messages
