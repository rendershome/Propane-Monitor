"""Define package errors."""

from typing import Optional

from aiohttp.client_exceptions import ClientError


class PyNeeVoError(Exception):
    """A base error."""


class InvalidCredentialsError(PyNeeVoError):
    """The Nee-Vo API rejected the email or password (HTTP 401)."""


class InvalidResponseFormat(PyNeeVoError):
    """The Nee-Vo API returned a response this library cannot understand."""


class GenericHTTPError(PyNeeVoError):
    """The Nee-Vo API returned an unexpected HTTP status."""

    def __init__(self, message: object = "", status: Optional[int] = None) -> None:
        """Initialize with an optional numeric HTTP status."""
        super().__init__(message)
        self.status = status


class NeeVoConnectionError(PyNeeVoError, ClientError):
    """The Nee-Vo API could not be reached.

    Also a ``ClientError`` so code written against earlier releases, which let
    aiohttp errors through unchanged, keeps working.
    """


class NeeVoTimeoutError(NeeVoConnectionError, TimeoutError):
    """The Nee-Vo API did not answer within the timeout.

    Also a ``TimeoutError`` so code written against earlier releases keeps
    working.
    """
