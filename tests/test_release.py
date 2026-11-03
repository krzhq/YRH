import pytest
import pytest_asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from app.database.store import Store
from app.database.discovery_migration import migrate
from app.database.mvp_migration import migrate_mvp
from app.database.release_migration import migrate_release
from app.services.quiz_storage import QuizStorage
from app.services.opening_hours import open_status
from app.handlers.discovery import Quiz,safe_photo_url
from app.handlers.discovery import card
from types import SimpleNamespace
from unittest.mock import AsyncMock
import asyncio

@pytest_asyncio.fixture
async def store(tmp_path):
    s=Store(tmp_path/'test.db'); await s.initialize('initial-pass'); migrate(s.path); migrate_mvp(s.path); migrate_release(s.path); return s

@pytest.mark.asyncio
async def test_quiz_resume_and_auth_is_not_persisted(store):
    key=StorageKey(bot_id=1,chat_id=5,user_id=5)
    one=FSMContext(QuizStorage(store),key); await one.set_state(Quiz.active); await one.update_data(step=3,prefs={'budget':5000},session=9)
    two=FSMContext(QuizStorage(store),key); assert await two.get_state()==Quiz.active.state
    assert (await two.get_data())['step']==3
    await two.clear()
    assert await FSMContext(QuizStorage(store),key).get_state() is None
    await one.set_state('Flow:password'); await one.update_data(password='secret')
    async with store.connect() as db:
        assert not await (await db.execute('SELECT * FROM quiz_state')).fetchall()

def test_hours_and_urls():
    local=ZoneInfo('Asia/Almaty')
    assert open_status('ежедневно 09:00–01:00',datetime(2026,11,3,0,30,tzinfo=local)) is True
    assert open_status('ежедневно 09:00–01:00',datetime(2026,11,3,3,30,tzinfo=local)) is False
    assert open_status('09:00–01:00,',datetime(2026,11,3,12,tzinfo=local)) is None
    assert not safe_photo_url('http://127.0.0.1/test')
    assert not safe_photo_url('file:///secret')
    assert safe_photo_url('https://example.com/photo')

@pytest.mark.asyncio
async def test_multiple_quizzes_and_text_fallback(store):
    s=QuizStorage(store)
    a=FSMContext(s,StorageKey(bot_id=1,chat_id=1,user_id=1)); b=FSMContext(s,StorageKey(bot_id=1,chat_id=2,user_id=2))
    async def progress(state,step):
        await state.set_state(Quiz.active); await state.update_data(step=step,prefs={},session=step)
    await asyncio.gather(progress(a,2),progress(b,5))
    other=QuizStorage(store)
    assert (await FSMContext(other,StorageKey(bot_id=1,chat_id=1,user_id=1)).get_data())['step']==2
    assert (await FSMContext(other,StorageKey(bot_id=1,chat_id=2,user_id=2)).get_data())['step']==5
    row={'name':'<venue>','restaurant_type':'cafe','menu_vibe':None,'address':'addr','average_bill':None,'rating':None,'reviews_count':None,'description':None,'photo':'https://example.com/a','photos':'["https://example.com/b"]','color_palette_hex':'[]'}
    message=SimpleNamespace(answer_photo=AsyncMock(side_effect=RuntimeError('Telegram error')),answer=AsyncMock())
    await card(message,row,None)
    assert message.answer.await_count==1 and '&lt;venue&gt;' in message.answer.await_args.args[0]
