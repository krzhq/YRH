from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
import pytest_asyncio
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from app.handlers.bot import Flow, account_command, callback, finish_command, input_step, menu_text
from app.database.store import Store
from app.services.security import hasher, verify
from main import configure_menu

@pytest.fixture
def state():
    return FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=55, user_id=55))

@pytest.fixture
def message():
    return SimpleNamespace(chat=SimpleNamespace(type='private'), from_user=SimpleNamespace(id=55), text=None, answer=AsyncMock(), delete=AsyncMock())

@pytest_asyncio.fixture
async def store(tmp_path):
    db = Store(tmp_path / 'existing.db')
    await db.initialize('initial-pass')
    return db

@pytest.mark.asyncio
async def test_account_and_finish(store, state, message):
    await account_command(message,state,store)
    assert 'необходимо войти' in message.answer.await_args.args[0]
    await store.register('Alice',hasher.hash('password1'),18,55)
    before = await store.get_user(55)
    await account_command(message,state,store)
    assert 'Alice' in message.answer.await_args.args[0] and '18' in message.answer.await_args.args[0]
    await state.set_state(Flow.password)
    await finish_command(message,state,store)
    assert await state.get_state() is None and await store.get_user(55) is None
    assert 'Welcome to Your Restaurant Here' in message.answer.await_args.args[0]
    await finish_command(message,state,store)
    assert await store.login('Alice','password1',55) == 'ok'
    after = await store.get_user(55)
    assert before['password_hash'] == after['password_hash'] and before['role'] == after['role']

@pytest.mark.asyncio
async def test_password_change_and_wrong_password(store, state, message):
    await store.register('Alice',hasher.hash('password1'),18,55)
    await state.set_state(Flow.current_password)
    message.text = 'wrong'
    await input_step(message,state,store,None)
    assert await state.get_state() == Flow.current_password.state
    message.text = 'password1'
    await input_step(message,state,store,None)
    message.text = 'new-password'
    await input_step(message,state,store,None)
    message.text = 'mismatch'
    await input_step(message,state,store,None)
    assert await state.get_state() == Flow.new_password.state
    message.text = 'new-password'
    await input_step(message,state,store,None)
    await input_step(message,state,store,None)
    assert await state.get_state() is None
    assert verify((await store.get_user(55))['password_hash'],'new-password')
    assert message.delete.await_count == 6

@pytest.mark.asyncio
async def test_command_menu():
    bot = SimpleNamespace(set_my_commands=AsyncMock(), set_chat_menu_button=AsyncMock())
    await configure_menu(bot)
    assert [c.command for c in bot.set_my_commands.await_args.args[0]] == ['account','finish','help','start']
    assert bot.set_chat_menu_button.await_args.kwargs['menu_button'].type == 'commands'

@pytest.mark.asyncio
async def test_admin_access_is_checked(store, state):
    await store.register('Alice',hasher.hash('password1'),18,55)
    q = SimpleNamespace(message=SimpleNamespace(chat=SimpleNamespace(type='private')), from_user=SimpleNamespace(id=55), data='admin:stats', answer=AsyncMock())
    await callback(q,state,store,None)
    assert q.answer.await_args.kwargs['show_alert'] is True

@pytest.mark.asyncio
async def test_legacy_admin_flag_is_ignored(store):
    async with store.connect() as db:
        await db.execute("UPDATE users SET must_change_password=1 WHERE username='matveikrutoi228'")
        before = (await (await db.execute("SELECT password_hash FROM users WHERE username='matveikrutoi228'")).fetchone())[0]
        await db.commit()
    await store.initialize('different-pass')
    assert await store.login('matveikrutoi228','initial-pass',55) == 'ok'
    admin = await store.get_user(55)
    assert admin['password_hash'] == before and admin['role'] == 'admin'
    assert 'Панель администратора' in (await menu_text(admin))[0]
