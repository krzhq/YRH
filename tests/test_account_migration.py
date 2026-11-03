import sqlite3
import pytest
from app.database.store import Store
from app.services.security import hasher

@pytest.mark.asyncio
async def test_existing_database_migration_and_multiple_accounts(tmp_path):
    path = tmp_path / 'existing.db'
    store = Store(path)
    await store.initialize('initial-pass')
    assert await store.login('matveikrutoi228', 'initial-pass', 123) == 'ok'
    await store.logout(123)
    async with store.connect() as db:
        await db.execute('CREATE UNIQUE INDEX legacy_unique_telegram ON account_owners(telegram_id)')
        await db.commit()
        before = [tuple(row) for row in await (await db.execute('SELECT * FROM users ORDER BY id')).fetchall()]
    await Store(path).initialize('initial-pass')
    backup = tmp_path / 'existing.db.before-owners-migration.bak'
    assert backup.exists()
    with sqlite3.connect(backup) as db:
        assert db.execute('SELECT count(*) FROM users').fetchone()[0] == 2
    async with store.connect() as db:
        assert before == [tuple(row) for row in await (await db.execute('SELECT * FROM users ORDER BY id')).fetchall()]
    await store.register('Alice', hasher.hash('password1'), 20, 123)
    assert (await Store(path).get_user(123))['username'] == 'Alice'
    await store.logout(123)
    assert await store.login('matveikrutoi228', 'initial-pass', 123) == 'ok'
    await store.logout(123)
    assert await store.login('Alice', 'password1', 999) == 'linked'
    assert await store.login('Alice', 'password1', 123) == 'ok'
    assert (await store.stats())['users'] == 3
