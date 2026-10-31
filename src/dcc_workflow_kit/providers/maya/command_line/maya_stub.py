# SPDX-License-Identifier: GPL-3.0-or-later
# Simplified Chinese localization by namink; additional display integration 2026-10-31.
"""What ``import maya`` / ``import maya.cmds`` / ``from maya import cmds`` import in a Command Line, Script Editor or
shelf entry: ``runner.prepare`` rewrites those lines to import this module by its package path (no import hook)."""
from ..i18n import source_message as _dcc_source, display_message as _dcc_display, format_message as _dcc_format
from . import cmds_shim
cmds = cmds_shim
