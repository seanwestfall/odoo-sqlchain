{
    'name': 'ChainSQL Transfer Boundary',
    'version': '19.0.2.1.0',
    'author': 'ChainSQL',
    'license': 'LGPL-3',
    'depends': ['chainsql_account'],
    'data': ['views/operation.xml'],
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'installable': True,
}
