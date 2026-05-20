"""WorkerPool — manages adaptive workers per queue band."""


class WorkerPool:
    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def adjust_workers(self, band: str, count: int) -> None:
        raise NotImplementedError
