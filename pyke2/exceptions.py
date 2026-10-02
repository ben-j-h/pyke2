"""Exceptions raised by pyke2."""

from __future__ import annotations


class KE2Error(Exception):
    """Base class for all pyke2 errors."""


class KE2ConnectionError(KE2Error):
    """The LDA could not be reached, timed out, or answered with something unusable."""


class KE2AuthError(KE2Error):
    """Login to the LDA failed (wrong username/password or role)."""


class KE2WriteError(KE2Error):
    """The LDA did not confirm a write."""


class KE2ValidationError(KE2Error, ValueError):
    """A value was rejected locally against the controller's limits schema."""


class KE2NotSupportedError(KE2Error):
    """The controller model does not have the requested field or feature."""
