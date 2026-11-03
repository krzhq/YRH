import sqlite3
import pytest
import pytest_asyncio
from app.database.store import Store
from app.services.security import hasher, valid_username, valid_age, valid_password, verify
from app.services.notifications import NotificationDispatcher

@pytest_asyncio.fixture
async def store(tmp_path):
    db = Store(tmp_path / 'test.db')
    await db.initialize('initial-pass')
    return db

@pytest.mark.asyncio
async def test_schema_seed_persistence(store):
    await store.initialize('different-pass')
    assert await store.stats() == {'users':2,'admins':2,'restaurants':0,'logs':0}
    async with store.connect() as db:
        rows = await (await db.execute('SELECT * FROM users ORDER BY id')).fetchall()
        assert len(rows) == 2 and rows[0]['password_hash'] != rows[1]['password_hash']
        assert all(verify(row['password_hash'],'initial-pass') and row['password_hash'].startswith('$argon2id$') for row in rows)
        assert (await (await db.execute('PRAGMA foreign_keys')).fetchone())[0] == 1
    assert (await Store(store.path).stats())['users'] == 2

@pytest.mark.asyncio
async def test_registration_login_logout_and_ownership(store):
    encoded = hasher.hash('same-password')
    await store.register('Alice', encoded, 18, 11)
    await store.register('Bobby', hasher.hash('same-password'), 19, 12)
    with pytest.raises(sqlite3.IntegrityError): await store.register('alice', encoded, 18, 13)
    assert await store.username_exists('ALICE')
    await store.logout(11)
    assert not await store.get_user(11)
    assert await store.login('alice','wrong-password',11) == 'invalid'
    assert await store.login('ALICE','same-password',99) == 'linked'
    assert await store.login('ALICE','same-password',11) == 'ok'
    assert (await store.get_user(11))['role'] == 'user'
    assert (await Store(store.path).get_user(11))['username'] == 'Alice'

@pytest.mark.asyncio
async def test_admin_and_rate_limit(store):
    assert await store.login('matveikrutoi228','initial-pass',22) == 'ok'
    assert (await store.get_user(22))['role'] == 'admin'
    await store.change_password(22,'new-password')
    await store.logout(22)
    assert await store.login('matveikrutoi228','new-password',22) == 'ok'
    for _ in range(4): assert await store.login('missing','bad',33) == 'invalid'
    assert await store.login('missing','bad',33) == 'locked'

def test_validation():
    assert valid_username('Name_123') and not valid_username('123') and not valid_username('matveikrutoi228')
    assert valid_age('13') and valid_age('100') and not valid_age('13.5') and not valid_age('-3')
    assert valid_password('a! 23456') and not valid_password('short')

class Bot:
    def __init__(self): self.messages = []; self.fail = False
    async def send_message(self, chat_id, text):
        if self.fail: raise RuntimeError('failed')
        self.messages.append((chat_id,text))

@pytest.mark.asyncio
async def test_outbox_and_retry(store):
    await store.register('Alice',hasher.hash('password1'),18,11)
    bot = Bot(); dispatcher = NotificationDispatcher(store,bot)
    await dispatcher.dispatch(); assert not bot.messages
    await store.login('matveikrutoi228','initial-pass',22)
    bot.fail = True; await dispatcher.dispatch()
    async with store.connect() as db:
        rows = await (await db.execute('SELECT * FROM notification_outbox')).fetchall()
        assert len(rows)==2 and sum(r['attempts'] for r in rows)==1
        await db.execute('UPDATE notification_outbox SET next_attempt_at=NULL'); await db.commit()
    bot.fail = False; await dispatcher.dispatch(); await dispatcher.dispatch()
    assert len(bot.messages)==1 and 'password' not in bot.messages[0][1]
    await store.login('aruzhan9mice','initial-pass',23); await dispatcher.dispatch()
    assert len(bot.messages)==2
    await store.insert_restaurant('Test','District','Cafe',5000)
    await store.insert_log(3,'test',selected_budget=5000)
    await dispatcher.dispatch(); assert len(bot.messages)==6

@pytest.mark.asyncio
async def test_deletion_restricts_history(store):
    uid = await store.register('Alice',hasher.hash('password1'),18,11)
    await store.insert_log(uid,'example')
    assert not await store.delete_account(11)
    assert await store.get_user(11)

