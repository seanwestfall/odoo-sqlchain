from . import models
from odoo.tools import file_open

def post_init_hook(env):
    with file_open('chainsql_resource_account/sql/invalidation.sql') as f:
        env.cr.execute(f.read())
