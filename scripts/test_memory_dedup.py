from friday.tools.memory import remember, _get_db_path
import sqlite3
from contextlib import closing

# dry_run doesn't write to DB, so deduplication can only detect already-stored entries
# Test: dry_run=False writes first, then same content detected as duplicate
r1 = remember("my favorite color is blue", dry_run=False)
print("write result:", r1)
r2 = remember("my favorite color is blue", dry_run=False)
print("duplicate result:", r2)
r3 = remember("My Favorite Color Is Blue", dry_run=False)
print("case variant result:", r3)
r4 = remember("  my favorite color is blue  ", dry_run=False)
print("whitespace variant result:", r4)

with closing(sqlite3.connect(_get_db_path())) as c:
    rows = c.execute("SELECT content FROM memories WHERE content LIKE ?", ("%color%",)).fetchall()
    print("DB rows:", rows)
    # Cleanup
    c.execute("DELETE FROM memories WHERE content LIKE ?", ("%color%",))
    c.commit()
