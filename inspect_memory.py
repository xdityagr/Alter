import sys
from pathlib import Path

# Add src to path
sys.path.append(str(Path("src").resolve()))

try:
    from alter.core.memory.store import MemoryStore
except ImportError:
    try:
        from src.alter.core.memory.store import MemoryStore
    except ImportError:
        print("Could not import MemoryStore. Check paths.")
        sys.exit(1)

# Adjust path if needed, assuming user is in project root
db_path = Path("data/memory.sqlite3")
if not db_path.exists():
    print(f"DB not found at {db_path}")
else:
    try:
        m = MemoryStore(path=db_path)
        cur = m._conn.execute("SELECT owner, COUNT(*) FROM memory_events GROUP BY owner")
        print("Identities found:")
        for row in cur:
            print(f" - Owner: '{row[0]}' (Count: {row[1]})")
        
        # Delete duplicate 'local' if present
        m._conn.execute("DELETE FROM memory_events WHERE owner='local'")
        m._conn.commit()
        print("Deleted 'local' owner (cleanup).")
        
    except Exception as e:
        print(f"Error accessing DB: {e}")
