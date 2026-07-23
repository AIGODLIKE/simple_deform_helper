from . import panel,header
def register():
    panel.register()
    header.register()


def unregister():
    header.unregister()
    panel.unregister()
