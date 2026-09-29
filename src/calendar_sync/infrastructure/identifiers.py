import uuid


class UuidIdGenerator:
    def new(self) -> str:
        return str(uuid.uuid4())


class UuidRunIdGenerator:
    def new_run_id(self) -> str:
        return uuid.uuid4().hex
