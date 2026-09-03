from enum import Enum
from dataclasses import dataclass
from datetime import datetime
class ScopeType(Enum):
    SYSTEM= "system"
    USER= "user"
    CASE="case"
    TASK="task"
class MemoryType(Enum):
    FACT="fact"
    EVENT="event"
    DECISION="decision"
    PROCEDURE="procedure"
    SUMMARY="summary"
    RELATIONSHIP="relationship"
class SourceType(Enum):
    PDF="pdf"
    PPTX="pptx"
    TEXT="text"
    USER="user"
    INFOGRAPHIC="infographic"
@dataclass
class Scope:
    scope_type:ScopeType
    scope_id:str
    parent_id:None|str =None
@dataclass
class Memory:
    id:str
    content:str
    scope:Scope
    memory_type:MemoryType
    created_at:datetime
    updated_at:datetime
@dataclass
class  Source:
    source_id:str
    source_type:SourceType
    source_reference:str
user1=Scope(ScopeType.USER,"user123",None)

case1=Scope(ScopeType.CASE,"case456",user1.scope_id)

task1=Scope(ScopeType.TASK,"task789",case1.scope_id)
memory1=Memory("memory001","something",task1,MemoryType.FACT,datetime.now(),datetime.now())
