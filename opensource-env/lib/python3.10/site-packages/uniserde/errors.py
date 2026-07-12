class SerdeError(Exception):
    """
    Signals a problem during serialization or deserialization.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)

    @property
    def message(self) -> str:
        return self.args[0]
