"""Module docstring.

Second line of module docstring.
"""
import os


class Foo:
    """Class docstring, single line."""

    def bar(self):
        """Function docstring; code on the same physical line."""; x = 1
        return x

    def baz(self):
        # a real comment-only line
        y = 1  # trailing comment on a code line
        s = """
# this looks like a comment but it is inside a plain string, not a docstring
"""
        return y, s


def not_a_docstring():
    f"""this is an f-string, not a docstring"""
    return 1


# module-level trailing comment
