import uuid


class UuidIdGenerator:
    def new(self) -> str:
        return str(uuid.uuid4())
