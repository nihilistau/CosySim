from pydantic import BaseModel, Field

class Entry(BaseModel):
    title: str
    
    def get(self, key, default=None):
        return getattr(self, key, default)

e = Entry(title="Hello")
print(e.title)
print(e.get("title"))
print(e.model_dump())
