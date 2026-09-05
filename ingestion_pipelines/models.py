from dataclasses import dataclass
from datetime import datetime, timezone
import uuid

@dataclass
class IngestedDocument:
    id: str
    source_path: str
    raw_text: str
    doc_type: str
    ingested_at: str
    user_id: str = None
    case_id: str = None
    task_id: str = None

    @staticmethod
    def create(source_path, raw_text, doc_type="text",
               user_id=None, case_id=None, task_id=None):
        return IngestedDocument(
            id=str(uuid.uuid4()),
            source_path=source_path,
            raw_text=raw_text,
            doc_type=doc_type,
            ingested_at=datetime.now(timezone.utc).isoformat(),
            user_id=user_id,
            case_id=case_id,
            task_id=task_id,
        )