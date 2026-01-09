from . import models
from . import hooks

# Import hooks to make them accessible for __manifest__.py
from .hooks import post_init_update_balances, pre_uninstall_cleanup
