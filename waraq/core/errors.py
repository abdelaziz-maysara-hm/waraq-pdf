class WaraqError(Exception):
    """User-facing error. ``code`` is a key into the GUI translation table."""

    def __init__(self, message: str, code: str = "error", **info):
        super().__init__(message)
        self.code = code
        self.info = info


class NeedsPasswordError(WaraqError):
    def __init__(self, path: str):
        super().__init__(f"{path} is password protected", "needs_password", path=path)


class WrongPasswordError(WaraqError):
    def __init__(self, path: str):
        super().__init__(f"Wrong password for {path}", "wrong_password", path=path)
