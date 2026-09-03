from memory.model import Memory
class MemoryStore:
    def __init__(self):
        self.memory:dict[str,Memory]={}
    def create_memory(self,single_memory:Memory):
        "It is used to create a memory in dict using Memory object"
        self.memory[single_memory.id]=single_memory
    def get_memory(self,memory_id:str)->Memory|None:
        return self.memory.get(memory_id)
    def update_memory(self,new_memory:Memory):
        self.memory[new_memory.id]=new_memory
    def delete_memory(self,memory_id:str):
        self.memory.pop(memory_id,None)
    def list(self)->list[Memory]:
        return list(self.memory.values())