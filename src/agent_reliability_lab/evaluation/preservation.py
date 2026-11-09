"""Read-only historical fingerprints; explicit migration-metadata exceptions only."""

import hashlib
import json
from pathlib import Path

import sqlalchemy as sa


def fingerprint(engine):
    inspector = sa.inspect(engine)
    quote = engine.dialect.identifier_preparer.quote
    tables = {}
    for schema in sorted(s for s in inspector.get_schema_names() if s.startswith("opsdesk_")):
        for name in sorted(inspector.get_table_names(schema=schema)):
            keys = inspector.get_pk_constraint(name, schema=schema)["constrained_columns"]
            identity = (
                "jsonb_build_array(" + ",".join("t." + quote(k) for k in keys) + ")::text"
                if keys
                else "md5(to_jsonb(t)::text)"
            )
            query = f"SELECT {identity}, to_jsonb(t)::text FROM {quote(schema)}.{quote(name)} AS t"
            with engine.connect().execution_options(
                stream_results=True, postgresql_readonly=True
            ) as c:
                rows = {
                    key: hashlib.sha256(data.encode()).hexdigest()
                    for key, data in c.execute(sa.text(query))
                }
            tables[schema + "." + name] = dict(primary=keys, rows=rows)
    return tables


def compare(before, current, *, migration_heads=None):
    changes = []
    preserved = 0
    migrations = []
    for name, table in before.items():
        if name not in current:
            changes.append(dict(table=name, reason="missing_table"))
            continue
        expected = (migration_heads or {}).get(name)
        if expected is not None:
            if table["primary"] != ["version_num"] or current[name]["primary"] != ["version_num"]:
                raise ValueError("migration allowance only supports Alembic revision rows")
            if list(current[name]["rows"]) != [json.dumps([expected])]:
                changes.append(dict(table=name, reason="unexpected_migration_head"))
            else:
                migrations.append(
                    dict(table=name, from_keys=sorted(table["rows"]), to_revision=expected)
                )
            continue
        for key, value in table["rows"].items():
            if current[name]["rows"].get(key) != value:
                changes.append(dict(table=name, key=key, reason="missing_or_changed_record"))
            else:
                preserved += 1
    return dict(
        verified=not changes,
        preserved_rows=preserved,
        changes=changes,
        migrations=migrations,
        added_tables=sorted(set(current) - set(before)),
    )


def verify_sources(root: Path, manifest: dict):
    root = root.resolve()
    out = {}
    for name, expected in manifest.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root):
            raise ValueError("source outside repository")
        canonical = path.read_text(encoding="utf-8").replace("\r\n", "\n").encode()
        out[name] = hashlib.sha256(canonical).hexdigest() == expected
    return out
