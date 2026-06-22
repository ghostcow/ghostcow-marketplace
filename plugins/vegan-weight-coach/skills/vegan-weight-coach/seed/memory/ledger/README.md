# Ledger schemas (append-only; one JSON line per entry; never edit or delete)
logs.jsonl      {"ts","type":"meal|weight|activity","detail":...}
sessions.jsonl  {"ts","stage","agreed","landed","next_checkpoint"}
lapses.jsonl    {"ts","trigger","context","emotion","coping","reframe_used","learned","self_efficacy_after"}
rulers.jsonl    {"ts","importance":0-10,"confidence":0-10,"behavior"}
checkins.jsonl  {"ts","ie_signal","self_vs_logged":...}
safety.jsonl    {"ts","flag","severity","action"}
# Files are created on first append.
