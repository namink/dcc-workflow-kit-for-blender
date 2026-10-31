# SPDX-License-Identifier: GPL-3.0-or-later
# Simplified Chinese localization by namink; additional display integration 2026-10-31.
"""The Maya layout file bundled inside the extension (generator: tools/make_startup.py, layout: docs/steps/step_5.md,
step_49.md).

Step 130 (docs/user_decisions.md #13): the file is no longer copied into the user's
scripts folder as an application template — nothing is written outside the extension's
folders. It is only read from here: ``switch.enter_layout`` appends its layout workspace into the open file, and
"New Scene in Maya Layout" (``first_start``) loads it as an untitled new file with
``wm.read_homefile(filepath=...)``, which keeps the preferences (measured, step 130).
"""
from ..i18n import source_message as _dcc_source, display_message as _dcc_display, format_message as _dcc_format
import os
TEMPLATE_ID = 'Maya_Workflow_Kit'
SOURCE_DIR = os.path.join(os.path.dirname(__file__), TEMPLATE_ID)
STARTUP = os.path.join(SOURCE_DIR, 'startup.blend')
