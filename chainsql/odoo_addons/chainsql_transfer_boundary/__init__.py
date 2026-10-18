from . import models
from odoo.tools import file_open
from odoo.exceptions import UserError


def post_init_hook(env):
    env.cr.execute("SELECT extversion FROM pg_extension WHERE extname='chainsql'")
    if env.cr.fetchone() not in [('0.2.1',), ('0.3.0',), ('0.4.0',)]:
        raise UserError('Install native ChainSQL extension 0.2.1 before this addon.')
    with file_open('chainsql_transfer_boundary/sql/invalidation.sql') as source:
        env.cr.execute(source.read())


def uninstall_hook(env):
    env.cr.execute('''DROP TRIGGER IF EXISTS chainsql_boundary_bill_changed ON account_move;
        DROP TRIGGER IF EXISTS chainsql_boundary_wallet_changed ON chainsql_wallet_approval;
        DROP FUNCTION IF EXISTS public.chainsql_boundary_bill_changed();
        DROP FUNCTION IF EXISTS public.chainsql_boundary_wallet_changed();''')
