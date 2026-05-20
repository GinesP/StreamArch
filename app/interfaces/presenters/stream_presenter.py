"""StreamPresenter — formats stream data for API and WebSocket responses."""

from app.application.dto.streams import StreamTargetDTO, ForecastDTO


class StreamPresenter:
    @staticmethod
    def present_stream_list(items: list[StreamTargetDTO]) -> dict:
        return {"items": [StreamPresenter._stream_item(s) for s in items]}

    @staticmethod
    def _stream_item(dto: StreamTargetDTO) -> dict:
        return {
            "id": dto.id,
            "platform": dto.platform,
            "handle": dto.handle,
            "display_name": dto.display_name,
            "enabled": dto.enabled,
            "favorite": dto.favorite,
            "state": dto.state,
            "queue_band": dto.queue_band,
            "current_likelihood": dto.current_likelihood,
            "current_confidence": dto.current_confidence,
            "next_check_at": dto.next_check_at,
            "last_live_at": dto.last_live_at,
        }

    @staticmethod
    def present_forecast(dto: ForecastDTO) -> dict:
        return {
            "stream_id": dto.stream_id,
            "likelihood": dto.likelihood,
            "confidence": dto.confidence,
            "ui_state": dto.ui_state,
            "predicted_window": dto.predicted_window,
            "next_slot_at": dto.next_slot_at,
            "reasons": dto.reasons,
            "current_queue_band": dto.current_queue_band,
            "target_interval_seconds": dto.target_interval_seconds,
            "jittered_interval_seconds": dto.jittered_interval_seconds,
        }
