class PipelineError(Exception):
    """파이프라인 각 단계 공통 에러. 사용자에게 보여줄 stage/message를 포함한다."""

    def __init__(self, stage: str, message: str):
        self.stage = stage
        self.message = message
        super().__init__(f"[{stage}] {message}")
