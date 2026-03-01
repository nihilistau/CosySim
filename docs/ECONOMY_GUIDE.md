# CosySim Economy Guide

> Cross-scene credit economy — EconomyManager, betting, consequences.
> Added in v0.68 "Dark Renaissance".

## Overview

Every scene shares a single economy. Credits earned in the Casino can be spent
in the Heist. Debts from the Tavern follow characters to the Lounge.

## EconomyManager (`engine/economy/economy.py`)

```python
from engine.economy.economy import get_economy_manager, TransactionType
eco = get_economy_manager()
eco.earn("lola", 100, TransactionType.GAMBLING_WIN, note="Blackjack 21")
eco.spend("lola", 50, TransactionType.HEIST_ENTRY, note="Crew cut")
balance = eco.get_balance("lola")    # 50
history = eco.get_history("lola")    # List[Transaction]
```

## ConsequenceStore (`engine/mechanics/consequences.py`)

Schedule delayed consequences (e.g. loan shark calls 24h later).
```python
from engine.mechanics.consequences import get_consequence_store, ConsequenceType
store = get_consequence_store()
store.schedule(
    consequence_type=ConsequenceType.DEBT_COLLECTION,
    target="lola",
    delay_hours=24,
    payload={"creditor": "frankie", "amount": 200}
)
```

## Cross-Scene Economy Flow

Casino loss > $100 → debt scheduled → 24h later phone contact "Mira" calls
Arena bet win → credits added → NeonCity faction economy updated via EventBus
