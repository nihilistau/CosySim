"""
CosySim - Entry point

Delegates to launcher.py for all mode dispatch.
Usage:
    python launcher.py --mode [hub|phone|bedroom|admin|all|test]

Running `python main.py` is an alias for the default launcher behaviour.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

if __name__ == "__main__":
    from launcher import main  # noqa: E402
    main()
