class CommerceError(Exception):
    """Erreur métier affichable proprement à l'appelant."""

    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
