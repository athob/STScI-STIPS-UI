"""
JWST CGI scene generator shared variables.

:Author: Pey Lian Lim

:Organization: Space Telescope Science Institute

:History:
    * 2010/12/02 PLL created this module.
    * 2011/02/15 PLL updated variables.
    * 2011/06/13 PLL applied v0.4 updates.
    * 2011/08/23 PLL applied v0.5 updates.
    * 2011/12/05 PLL applied v0.6 updates.
    * 2014/12/03 BAQ moved instrument-specific components to instrument-specific class files.
    
"""
import os

_VERSION = '0.6.3'
_COL_PER_ROW = 5

telescope = 'JWST-WFIRST'
internal_only = "0"
check_group = "0"
allowed_groups = []
check_users = "0"
user_db = "users.db"
parallel = False

SECRET_KEY = '\x98\x14"t\x11\xe63\xd1S\xc28\xd6\x19b\x12*\n\x14\x1f\xbf\xf6\xbbxQ'

if "REDIS_PORT_6379_TCP_ADDR" in os.environ:
    CELERY_BROKER_URL='redis://' + os.environ['REDIS_PORT_6379_TCP_ADDR'] + ':' + os.environ['REDIS_PORT_6379_TCP_PORT'] + '/0'
    BROKER_URL = CELERY_BROKER_URL
    CELERY_RESULT_BACKEND='redis://' + os.environ['REDIS_PORT_6379_TCP_ADDR'] + ':' + os.environ['REDIS_PORT_6379_TCP_PORT'] + '/0'
    RESULT_BACKEND = CELERY_RESULT_BACKEND
    CELERYD_CONCURRENCY = 3
else:
    CELERY_BROKER_URL='redis://localhost:6379/0'
    BROKER_URL = CELERY_BROKER_URL
    CELERY_RESULT_BACKEND='redis://localhost:6379/0'
    RESULT_BACKEND = CELERY_RESULT_BACKEND
    CELERYD_CONCURRENCY = 2
CELERY_REDIRECT_STDOUT_LEVEL='DEBUG'
CELERY_IGNORE_RESULT = False

CELERY_UPDATER =    {
                        'BROKER_URL': BROKER_URL,
                        'CELERY_BROKER_URL': CELERY_BROKER_URL,
                        'RESULT_BACKEND' : CELERY_RESULT_BACKEND,
                        'CELERY_RESULT_BACKEND': CELERY_RESULT_BACKEND,
                        'CELERY_REDIRECT_STDOUT_LEVEL': CELERY_REDIRECT_STDOUT_LEVEL,
                        'CELERYD_CONCURRENCY': CELERYD_CONCURRENCY,
                        'CELERY_IGNORE_RESULT': CELERY_IGNORE_RESULT,
                        'CELERYD_PREFETCH_MULTIPLIER': 1
                    }

_INP_PATH = 'sim_input/'
_OUT_PATH = 'static/sim_temp/'
_CACHE_PATH = 'static/cached/'
_SIJ_PATH = 'static/sijax'

excludes = []
