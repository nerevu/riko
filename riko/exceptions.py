# vim: sw=4:ts=4:expandtab
"""
Provides riko specific exceptions
"""


class UnsupportedModuleError(ImportError):
    def __init__(self, module_name: str):
        super().__init__(f"Unsupported riko module: {module_name}")
        self.module_name = module_name
