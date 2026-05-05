from dataclasses import dataclass


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    email: str
    display_name: str
    is_active: bool = True
