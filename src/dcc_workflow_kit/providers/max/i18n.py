# SPDX-License-Identifier: GPL-3.0-or-later
# Adapted for DCC Workflow Kit.
"""Only marked source messages are translated; runtime user strings pass through."""
from ...localization import tr, is_chinese

class Message(str):

    def format(self, *values, **kwargs):
        result = Message(str(self).format(*values, **kwargs))
        result.formatted = (str(self), values, kwargs)
        return result

    def __mod__(self, values):
        result = Message(str(self) % values)
        result.percent_format = (str(self), values)
        return result

    def __add__(self, other):
        result = Message(super().__add__(other))
        result.parts = (self, other)
        return result

    def __radd__(self, other):
        result = Message(other + str(self))
        result.parts = (other, self)
        return result

def msg(text):
    return Message(text)

def display(value):
    if not isinstance(value, Message):
        return str(value)
    if not is_chinese():
        return str(value)
    parts = getattr(value, 'parts', None)
    formatted = getattr(value, 'formatted', None)
    percent = getattr(value, 'percent_format', None)
    if parts:
        return ''.join(display(p) for p in parts)
    if formatted:
        template, values, *options = formatted
        kwargs = options[0] if options else {}
        return tr(template, domain='max').format(*(display(v) if isinstance(v, Message) else v for v in values),
                                                  **{k: display(v) if isinstance(v, Message) else v for k, v in kwargs.items()})
    if percent:
        return tr(percent[0], domain='max') % percent[1]
    return tr(str(value), domain='max')


def format_message(template, *values):
    result = Message(template.format(*values))
    result.formatted = (template, values)
    return result


def error_text(error):
    value = error.args[0] if len(getattr(error, 'args', ())) == 1 else str(error)
    return display(value)
