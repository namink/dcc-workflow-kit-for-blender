# SPDX-License-Identifier: GPL-3.0-or-later
# Simplified Chinese localization by namink; additional display integration 2026-10-31.
"""The product's display name (step 125, docs/user_decisions.md 12): every user-visible "Maya Workflow Kit" string
comes from here. Internal identifiers stay ``allset`` (extension id, package, ``allset.`` operators, ``ALLSET_``
classes, ``ALLSET_*`` environment variables, ``allset_*`` properties): users don't see them. No bpy (the marking
menu engine imports it headless)."""
from .i18n import source_message as _dcc_source, display_message as _dcc_display, format_message as _dcc_format
PRODUCT = 'Maya Workflow Kit'
