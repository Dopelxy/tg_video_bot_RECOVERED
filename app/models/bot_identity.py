from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class BotIdentity:
    name: str
    username: str

    @property
    def username_with_at(self) -> str:
        username = self.username.lstrip("@")

        return f"@{username}"
    