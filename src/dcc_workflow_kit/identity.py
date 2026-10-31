# SPDX-License-Identifier: GPL-3.0-or-later
"""The actual extension identity, independent of backend nesting."""


def package_id():
    return __package__


def user_path(relative=''):
    """Extension-owned user data; standalone test installs use their isolated config."""
    import os
    import bpy
    try:
        return bpy.utils.extension_path_user(package_id(), path=relative, create=True)
    except ValueError:
        return bpy.utils.user_resource('CONFIG', path=os.path.join('dcc_workflow_kit', relative), create=True)
