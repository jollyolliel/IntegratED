"""The one exception type whose message is shown to the person who made the request.

An op refuses a request with `Refusal("Enter a duration greater than zero.")`; a route turns
any exception into response text only through `refusal_message`, so the text of an exception
nobody wrote for a reader (a driver error, `int("x")`, a bug) stays in the server log.
"""

GENERIC_REFUSAL = "That couldn't be saved. Check the values and try again."


class Refusal(ValueError):
    """A request the app declined, with a message written for the person who sent it.

    A `ValueError` subclass, so code that catches `ValueError` keeps working.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def refusal_message(exc: BaseException) -> str:
    """The text a response may carry for `exc`: its own message for a `Refusal`, else a generic one.

    Args:
        exc (BaseException): The exception a route or the assistant caught.

    Returns:
        str: Text that is safe to send to the client.
    """
    if isinstance(exc, Refusal):
        return exc.message
    return GENERIC_REFUSAL
