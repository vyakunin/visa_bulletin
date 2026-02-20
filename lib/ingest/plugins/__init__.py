from lib.ingest.registry import PluginRegistry
from .dol_perm import PERMSalaryDataSourcePlugin as DolPermPlugin
from .dol_perm_supply import DolPermSupplyPlugin
from .uscis import UscisInventoryPlugin
from .dos import DosIssuancePlugin

# Register standard Salary plugins
PluginRegistry.register(DolPermPlugin())

# Register VQS Supply plugins
PluginRegistry.register(UscisInventoryPlugin())
PluginRegistry.register(DosIssuancePlugin())
PluginRegistry.register(DolPermSupplyPlugin())