#!/usr/bin/env python3
"""
Script to verify memory content consistency across multiple databases.

Checks that memories sharing the same ID have identical content,
content_hash, embedding, and other fields.

Usage:
    python scripts/verify_db_consistency.py
"""

import sqlite3
import hashlib
from pathlib import Path
from typing import Dict, List, Tuple, Set

# Project root path
ROOT_DIR = Path(__file__).parent.parent

# Databases to verify
DATABASES = [
    ROOT_DIR / "data" / "memories.db",
    ROOT_DIR / "data_macmini" / "memories.db",
    ROOT_DIR / "data_macbook" / "memories.db",
]


def get_memory_data(db_path: Path) -> Dict[str, Dict]:
    """Fetch all memory data from a database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, content, content_hash, project_id, category,
               source, embedding, tags, created_at, updated_at
        FROM memories
    """)

    memories = {}
    for row in cursor.fetchall():
        memory_id = row['id']
        memories[memory_id] = {
            'content': row['content'],
            'content_hash': row['content_hash'],
            'project_id': row['project_id'],
            'category': row['category'],
            'source': row['source'],
            'embedding': row['embedding'],
            'tags': row['tags'],
            'created_at': row['created_at'],
            'updated_at': row['updated_at'],
        }

    conn.close()
    return memories


def compare_memories(db_memories: List[Tuple[str, Dict[str, Dict]]]) -> Dict:
    """Compare memories across multiple databases."""

    # Find IDs common to all databases
    all_ids = [set(memories.keys()) for _, memories in db_memories]
    common_ids = set.intersection(*all_ids)

    print(f"📊 Memory ID Analysis:")
    for db_name, memories in db_memories:
        print(f"   {db_name}: {len(memories):,} memories")
    print(f"   Common IDs: {len(common_ids):,} memories")

    # IDs unique to each database
    for i, (db_name, memories) in enumerate(db_memories):
        unique_ids = set(memories.keys())
        for j, (other_name, other_memories) in enumerate(db_memories):
            if i != j:
                unique_ids -= set(other_memories.keys())

        if unique_ids:
            print(f"   Only in {db_name}: {len(unique_ids):,} memories")

    print()

    # Compare content for common IDs
    inconsistencies = {
        'content_mismatch': [],
        'content_hash_mismatch': [],
        'embedding_mismatch': [],
        'metadata_mismatch': [],
    }

    print(f"🔍 Verifying content consistency... (sample: first 1000)")

    # Sample: only verify first 1000 (full verification takes a long time)
    sample_ids = list(common_ids)[:1000]

    for idx, memory_id in enumerate(sample_ids):
        if (idx + 1) % 100 == 0:
            print(f"   Progress: {idx + 1}/{len(sample_ids)}")

        # Use the first DB as baseline
        base_db_name, base_memories = db_memories[0]
        base_memory = base_memories[memory_id]

        # Compare against other DBs
        for db_name, memories in db_memories[1:]:
            memory = memories[memory_id]

            # Content comparison
            if base_memory['content'] != memory['content']:
                inconsistencies['content_mismatch'].append({
                    'id': memory_id,
                    'base_db': base_db_name,
                    'compare_db': db_name,
                    'base_content_len': len(base_memory['content']),
                    'compare_content_len': len(memory['content']),
                })

            # Content hash comparison
            if base_memory['content_hash'] != memory['content_hash']:
                inconsistencies['content_hash_mismatch'].append({
                    'id': memory_id,
                    'base_db': base_db_name,
                    'compare_db': db_name,
                    'base_hash': base_memory['content_hash'],
                    'compare_hash': memory['content_hash'],
                })

            # Embedding comparison (None check)
            base_emb = base_memory['embedding']
            comp_emb = memory['embedding']

            if (base_emb is None) != (comp_emb is None):
                inconsistencies['embedding_mismatch'].append({
                    'id': memory_id,
                    'base_db': base_db_name,
                    'compare_db': db_name,
                    'issue': 'one_is_null',
                })
            elif base_emb is not None and comp_emb is not None:
                if base_emb != comp_emb:
                    inconsistencies['embedding_mismatch'].append({
                        'id': memory_id,
                        'base_db': base_db_name,
                        'compare_db': db_name,
                        'issue': 'different_values',
                    })

            # Metadata comparison (project_id, category, source, tags)
            metadata_fields = ['project_id', 'category', 'source', 'tags']
            for field in metadata_fields:
                if base_memory[field] != memory[field]:
                    inconsistencies['metadata_mismatch'].append({
                        'id': memory_id,
                        'base_db': base_db_name,
                        'compare_db': db_name,
                        'field': field,
                        'base_value': base_memory[field],
                        'compare_value': memory[field],
                    })

    return inconsistencies


def print_inconsistencies(inconsistencies: Dict):
    """Print inconsistency details."""
    print(f"\n📋 Verification Results:\n")

    total_issues = sum(len(issues) for issues in inconsistencies.values())

    if total_issues == 0:
        print("✅ All memories are consistently synchronized!")
        return

    print(f"⚠️  Total {total_issues} inconsistencies found\n")

    # Content mismatches
    if inconsistencies['content_mismatch']:
        print(f"❌ Content mismatches: {len(inconsistencies['content_mismatch'])}")
        for issue in inconsistencies['content_mismatch'][:5]:
            print(f"   ID: {issue['id']}")
            print(f"   {issue['base_db']}: {issue['base_content_len']} chars")
            print(f"   {issue['compare_db']}: {issue['compare_content_len']} chars")
            print()

        if len(inconsistencies['content_mismatch']) > 5:
            print(f"   ... and {len(inconsistencies['content_mismatch']) - 5} more\n")

    # Content hash mismatches
    if inconsistencies['content_hash_mismatch']:
        print(f"❌ Content Hash mismatches: {len(inconsistencies['content_hash_mismatch'])}")
        for issue in inconsistencies['content_hash_mismatch'][:5]:
            print(f"   ID: {issue['id']}")
            print(f"   {issue['base_db']}: {issue['base_hash']}")
            print(f"   {issue['compare_db']}: {issue['compare_hash']}")
            print()

        if len(inconsistencies['content_hash_mismatch']) > 5:
            print(f"   ... and {len(inconsistencies['content_hash_mismatch']) - 5} more\n")

    # Embedding mismatches
    if inconsistencies['embedding_mismatch']:
        print(f"❌ Embedding mismatches: {len(inconsistencies['embedding_mismatch'])}")
        for issue in inconsistencies['embedding_mismatch'][:5]:
            print(f"   ID: {issue['id']}")
            print(f"   {issue['base_db']} vs {issue['compare_db']}")
            print(f"   Issue: {issue['issue']}")
            print()

        if len(inconsistencies['embedding_mismatch']) > 5:
            print(f"   ... and {len(inconsistencies['embedding_mismatch']) - 5} more\n")

    # Metadata mismatches
    if inconsistencies['metadata_mismatch']:
        print(f"❌ Metadata mismatches: {len(inconsistencies['metadata_mismatch'])}")
        for issue in inconsistencies['metadata_mismatch'][:5]:
            print(f"   ID: {issue['id']}")
            print(f"   Field: {issue['field']}")
            print(f"   {issue['base_db']}: {issue['base_value']}")
            print(f"   {issue['compare_db']}: {issue['compare_value']}")
            print()

        if len(inconsistencies['metadata_mismatch']) > 5:
            print(f"   ... and {len(inconsistencies['metadata_mismatch']) - 5} more\n")


def main():
    print("🔍 Starting database consistency verification\n")

    # Check databases exist
    for db_path in DATABASES:
        if not db_path.exists():
            print(f"❌ Database not found: {db_path}")
            return 1

    print(f"Databases to verify:")
    for db_path in DATABASES:
        print(f"   - {db_path}")
    print()

    # Load memory data from each database
    db_memories = []
    for db_path in DATABASES:
        print(f"📥 Loading {db_path.name}...")
        memories = get_memory_data(db_path)
        db_memories.append((db_path.name, memories))

    print()

    # Compare memories
    inconsistencies = compare_memories(db_memories)

    # Print results
    print_inconsistencies(inconsistencies)

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
