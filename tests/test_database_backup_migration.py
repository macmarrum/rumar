from textwrap import dedent
from time import sleep

from rumar import make_profile_to_settings_from_toml_text, RumarDB


def test_migrate_to_bak_name():
    profile = 'profile'
    toml_text = dedent(f"""\
    version = 2
    db_path = ':memory:'
    backup_base_dir = '/path/to/backup'
    [{profile}]
    source_dir = '/path/to/source'
    """)
    profile_to_settings = make_profile_to_settings_from_toml_text(toml_text)
    rumar_db = RumarDB(profile, profile_to_settings[profile])
    db = rumar_db._db
    cur = db.cursor()
    # Undo creation of the new backup table
    cur.execute('DROP VIEW IF EXISTS v_backup')
    cur.execute('DROP VIEW IF EXISTS v_run')
    cur.execute('DROP INDEX IF EXISTS i_backup_reason')
    cur.execute('DROP TABLE IF EXISTS backup')
    # Create the old backup table and dummy views
    cur.executescript('''
        CREATE TABLE backup (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL REFERENCES run (id),
            reason TEXT NOT NULL,
            bak_dir_id INTEGER NOT NULL REFERENCES backup_base_dir_for_profile (id),
            bak_path TEXT NOT NULL,
            mtime_iso TEXT NOT NULL,
            size INTEGER NOT NULL,
            blake2b TEXT,
            src_id INTEGER NOT NULL REFERENCES source (id),
            CONSTRAINT u_bak_dir_id_bak_path UNIQUE (bak_dir_id, bak_path)
        ) STRICT;
        CREATE VIEW v_backup AS SELECT * FROM backup;
        CREATE VIEW v_run AS SELECT * FROM run;
        CREATE INDEX i_backup_mtime_iso ON backup(mtime_iso);
        CREATE INDEX i_backup_size ON backup(size);
    ''')
    # Insert test data
    cur.executescript('''
        INSERT INTO profile (id, profile) VALUES (1, 'profile');
        INSERT INTO run (id, run_datetime_iso, profile_id) VALUES (1, '2024-01-01T00:00:00Z', 1);
        INSERT INTO backup_base_dir_for_profile (id, bak_dir) VALUES (1, '/path/to/backup/profile');
        INSERT INTO source_dir (id, src_dir) VALUES (1, '/path/to/source');
        INSERT INTO source (id, src_dir_id, src_path) VALUES (1, 1, 'subdir/file.txt');
        INSERT INTO backup (id, run_id, reason, bak_dir_id, bak_path, mtime_iso, size, blake2b, src_id)
        VALUES 
        (1, 1, 'C', 1, 'subdir/file.txt/2024-01-01_11,00,00+00,00~1000.tar.gz', '2024-01-01T11:00:00+00:00', 1000, 'hash1', 1),
        (2, 1, 'U', 1, 'subdir/file.txt/2024-01-01_22,00,00+00,00~2000.tar.gz', '2024-01-01T22,00,00+00,00', 2000, 'hash2', 1)
    ''')
    # Perform migration
    RumarDB._migrate_to_bak_name(db)
    # Verify results
    cur.execute('SELECT id, bak_name FROM backup ORDER BY id')
    results = cur.fetchall()
    expected = [
        (1, '2024-01-01_11,00,00+00,00~1000.tar.gz'),
        (2, '2024-01-01_22,00,00+00,00~2000.tar.gz'),
    ]
    assert results == expected, f"Expected {expected}, but got {results}"
    # Verify new table structure
    cur.execute("PRAGMA table_info(backup)")
    columns = {row[1] for row in cur.fetchall()}
    expected_columns = {'id', 'run_id', 'reason', 'bak_dir_id', 'src_id', 'bak_name', 'blake2b'}
    assert columns == expected_columns, f"Expected columns {expected_columns}, but got {columns}"
    db.close()


def test_init_source_lfc_if_empty():
    profile = 'profile'
    toml_text = dedent(f"""\
    version = 2
    db_path = ':memory:'
    backup_base_dir = '/path/to/backup'
    [{profile}]
    source_dir = '/path/to/source'
    """)
    profile_to_settings = make_profile_to_settings_from_toml_text(toml_text)
    rumar_db = RumarDB(profile, profile_to_settings[profile])
    db = rumar_db._db
    cur = db.cursor()
    # Insert test data
    cur.executescript(f'''
        INSERT INTO profile (id, profile) VALUES (1, 'profile');
        INSERT INTO run (id, run_datetime_iso, profile_id) VALUES (1, '2025-07-23 00:00:01+02:00', 1);
        INSERT INTO backup_base_dir_for_profile (id, bak_dir) VALUES (1, '/path/to/backup/profile');
        INSERT INTO source_dir (id, src_dir) VALUES (1, '/path/to/source');
        INSERT INTO source (id, src_dir_id, src_path) VALUES
        (1, 1, 'subdir/file1.txt'),
        (2, 1, 'subdir/file2.txt');
        INSERT INTO backup (id, run_id, reason, bak_dir_id, src_id, bak_name, blake2b)
        VALUES 
        (1, 1, 'C', 1, 1, '2024-01-01_11,00,00+00,00~1000.tar.gz', 'hash1'),
        (2, 1, 'U', 1, 1, '2024-01-01_22,00,00+00,00~2000.tar.gz', 'hash2')
        ''')
    db.commit()
    rumar_db._load_data_into_memory()
    # Perform alter action
    rumar_db._init_source_lfc_if_empty()
    # Verify results
    actual = cur.execute('SELECT * FROM source_lfc ORDER BY id').fetchall()
    expected = [
        (1, 1, 'I', rumar_db._run_id),
        (2, 2, 'I', rumar_db._run_id),
    ]
    assert actual == expected
    for table in ['profile', 'run', 'backup_base_dir_for_profile', 'backup', 'source_dir', 'source', 'source_lfc']:
        print(f"\n{table}:")
        for row in cur.execute(f"SELECT * FROM {table}"):
            print(row)
