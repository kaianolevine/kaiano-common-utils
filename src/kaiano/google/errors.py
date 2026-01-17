class GoogleAPIError(RuntimeError):
    """Base error for kaiano_common_utils.google."""


class NotFoundError(GoogleAPIError):
    """Requested resource was not found."""
