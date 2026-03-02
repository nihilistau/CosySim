import inspect
from engine.mcp.comms_types import InterceptorBase
import engine.agents.interceptors
import engine.agents.dialogue_gate
import engine.characters.memory
import engine.characters.reputation

for cls in InterceptorBase.__subclasses__():
    if not inspect.isabstract(cls) and cls.__name__ != 'InterceptorBase':
        try:
            inst = cls()
            print(f"Success: {cls.__name__}")
        except Exception as e:
            print(f"Failed: {cls.__name__} - {e}")
