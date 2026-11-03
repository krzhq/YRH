from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import json
import pytest
import pytest_asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import SimpleEventIsolation
from aiogram.types import Message, Update
from app.database.store import Store
from app.database.discovery_migration import migrate
from app.database.mvp_migration import migrate_mvp
from app.database.release_migration import migrate_release
from app.database.statistics_migration import migrate_statistics
from app.services.quiz_storage import QuizStorage
from app.services.restaurant_import_service import import_data
from app.handlers.discovery import router as discovery_router
from app.handlers.analytics import router as analytics_router
from app.handlers.bot import router as bot_router

class MockSession(BaseSession):
    def __init__(self): super().__init__(); self.calls=[]
    async def close(self): pass
    async def stream_content(self,*args,**kwargs):
        if False: yield b''
    async def make_request(self,bot,method,timeout=None):
        self.calls.append(method)
        if method.__class__.__name__ in ('SendMessage','EditMessageText','SendPhoto','SendDocument'):
            return Message.model_validate({'message_id':1000+len(self.calls),'date':int(datetime.now(timezone.utc).timestamp()),'chat':{'id':getattr(method,'chat_id',1),'type':'private'},'text':'ok'},context={'bot':bot})
        return True

@pytest.mark.asyncio
async def test_dispatcher_conversations_and_restart(tmp_path):
    store=Store(tmp_path/'test.db'); await store.initialize('initial-pass'); migrate(store.path); migrate_mvp(store.path); migrate_release(store.path); migrate_statistics(store.path)
    source=tmp_path/'places.json'; source.write_text(json.dumps([{'id':1,'site_id':'1','name':'Red Cafe','type':'кафе','source':'test','menu_vibe':'итальянская','average_bill':'5000–8000 ₸','color_palette_hex':['#8B0000'],'photo':'https://example.org/1.jpg','photos':[]}],ensure_ascii=False),encoding='utf8'); import_data(source,store.path)
    session=MockSession(); bot=Bot('123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi',session=session)
    storage=QuizStorage(store); dp=Dispatcher(storage=storage,events_isolation=SimpleEventIsolation())
    dp.include_router(discovery_router); dp.include_router(analytics_router); dp.include_router(bot_router)
    notify=SimpleNamespace(dispatch=AsyncMock()); counter=0
    async def send(uid,text):
        nonlocal counter; counter+=1
        body={'message_id':counter,'date':1700000000,'chat':{'id':uid,'type':'private'},'from':{'id':uid,'is_bot':False,'first_name':'Test'},'text':text}
        if text.startswith('/'): body['entities']=[{'type':'bot_command','offset':0,'length':len(text)}]
        await dp.feed_update(bot,Update.model_validate({'update_id':counter,'message':body},context={'bot':bot}),store=store,notifications=notify)
    async def click(uid,data):
        nonlocal counter; counter+=1
        msg={'message_id':900,'date':1700000000,'chat':{'id':uid,'type':'private'},'from':{'id':123456,'is_bot':True,'first_name':'Bot'},'text':'screen'}
        query={'id':str(counter),'from':{'id':uid,'is_bot':False,'first_name':'Test'},'chat_instance':'chat','message':msg,'data':data}
        await dp.feed_update(bot,Update.model_validate({'update_id':counter,'callback_query':query},context={'bot':bot}),store=store,notifications=notify)
    try:
        await send(111,'/start'); await click(111,'register'); await send(111,'testuser'); await send(111,'password1'); await send(111,'20'); await click(111,'reg:confirm')
        assert await store.get_user(111)
        await click(111,'logout'); await click(111,'login'); await send(111,'testuser'); await send(111,'password1')
        await click(111,'discover')
        for value in ['итальянская','кафе','any','any','7000','any','red']: await click(111,'dq:v:'+value)
        async with store.connect() as db:
            result=await (await db.execute('SELECT id FROM recommendation_results')).fetchone()
        assert result
        await click(111,f'rate:{result[0]}:2'); await click(111,f'reason:{result[0]}:price')
        await click(111,'tinder')
        async with store.connect() as db:
            tinder=await (await db.execute("SELECT id,current_restaurant_id FROM tinder_sessions WHERE status='active'")).fetchone()
        await click(111,f'sw:{tinder[0]}:{tinder[1]}:like'); await click(111,'favorites')
        await click(111,'discover'); await click(111,'dq:v:any')
        # A fresh storage instance simulates a process restart.
        dp.fsm.storage=QuizStorage(store)
        await send(111,'/start'); await click(111,'quiz:resume')
        await send(111,'/finish'); assert not await store.get_user(111)
        await click(222,'login'); await send(222,'matveikrutoi228'); await send(222,'initial-pass'); await click(222,'analytics:all'); await click(222,'analytics:all:csv')
        assert any(call.__class__.__name__=='SendDocument' for call in session.calls)
        async with store.connect() as db:
            assert (await (await db.execute('SELECT count(*) FROM favorites')).fetchone())[0]==1
            assert (await (await db.execute('SELECT feedback_reason FROM statistics')).fetchone())[0]=='Цена'
    finally:
        await dp.storage.close(); await bot.session.close()
