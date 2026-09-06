"""SSE streaming for the FastAPI backend."""

import asyncio
import json
from typing import AsyncGenerator

from pipelines.orchestrator.progress import ProgressEvent
from integrations.deepseek_harness.application import get_application


async def event_generator(run_id: str, timeout: int = 3600) -> AsyncGenerator[str, None]:
    """Yield SSE-formatted progress events for a given run."""
    
    app = get_application()
    last_event_count = 0
    start_time = asyncio.get_event_loop().time()
    
    # Yield initial connection heartbeat
    yield "event: heartbeat\ndata: {}\n\n"

    while True:
        # Check timeout
        if asyncio.get_event_loop().time() - start_time > timeout:
            yield f"event: error\ndata: {json.dumps({'error': 'Stream timeout'})}\n\n"
            break
            
        # Get new events
        all_events = app.events(run_id)
        if len(all_events) > last_event_count:
            for event in all_events[last_event_count:]:
                # Format as SSE
                yield f"event: progress\ndata: {json.dumps(event)}\n\n"
                
                # Only the parent terminal stages close the stream. A
                # pipeline_result event is not terminal for a fan-out run and
                # a pending provider job must remain observable.
                if event.get("stage") in ("completed", "failed", "cancellation", "cancelled"):
                    return
                    
            last_event_count = len(all_events)
            
        # Poll interval + heartbeat
        await asyncio.sleep(0.5)
        if int(asyncio.get_event_loop().time() - start_time) % 15 == 0:
            yield "event: heartbeat\ndata: {}\n\n"
