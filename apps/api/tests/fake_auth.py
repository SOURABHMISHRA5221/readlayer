"""Fake Firebase token verification for tests. Imports nothing heavy (used in subprocess
import checks too)."""


class FakeAuthAdmin:
    """Accepts tokens shaped "test:<provider>:<uid>"; anything else is invalid."""

    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.users: set[str] = set()

    async def verify(self, token: str) -> dict:
        from app.auth import InvalidToken

        parts = token.split(":", 2)
        if len(parts) != 3 or parts[0] != "test":
            raise InvalidToken("InvalidIdTokenError")
        _, provider, uid = parts
        if uid in self.deleted:
            raise InvalidToken("UserNotFoundError")
        self.users.add(uid)
        return {
            "uid": uid,
            "email": f"{uid}@example.com",
            "firebase": {"sign_in_provider": provider},
        }

    async def delete_user(self, uid: str) -> None:
        self.deleted.append(uid)
        self.users.discard(uid)


def token(uid: str = "u1", anonymous: bool = False) -> str:
    return f"test:{'anonymous' if anonymous else 'google.com'}:{uid}"


def auth(uid: str = "u1", anonymous: bool = False) -> dict[str, str]:
    return {"Authorization": f"Bearer {token(uid, anonymous)}"}
