# openclaw ai agent

## Miles — Deal Routing & CRM Automation Engine

Miles is the deal-routing and CRM automation backend for REI Professions. It enforces broker-specific Standard Operating Procedures (SOPs) across the deal intake pipeline.

### Architecture

```
src/miles/
├── config/
│   ├── brokers.py      # Broker SOP registry (per-broker gate rules)
│   ├── prompts.py      # AI agent system prompts
│   └── supabase.py     # Supabase project & playbook references
├── deals/
│   ├── models.py       # Deal, BrokerContact, Document data models
│   └── router.py       # Deal intake router with gate enforcement
├── notifications/
│   └── templates.py    # Message templates (doc requests, block notices)
└── workflows/
    └── guards.py       # Workflow gate evaluation logic
```

### Broker SOPs

Broker-specific rules are registered in `src/miles/config/brokers.py`. Each SOP defines gate documents that must be collected before full deal details are released.

**Martin Winter SOP** — Every deal from Martin Winter triggers an urgent request for Proof of Funds (POF) and Letter of Intent (LOI). No full details, packages, or expanded materials are sent until both are received. Wired to Supabase playbook `martin-winter-pof-loi-gate` in project `egpqhzubdeklzstzdmtt`.

### Running Tests

```bash
pip install -e .
pip install pytest
python -m pytest tests/ -v
```
