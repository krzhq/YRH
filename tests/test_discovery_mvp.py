import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
import pytest_asyncio
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from app.database.store import Store
from app.database.discovery_migration import migrate
from app.database.mvp_migration import migrate_mvp
from app.database.release_migration import migrate_release
from app.database.statistics_migration import migrate_statistics
from app.services.restaurant_import_service import import_data
from app.services.security import hasher
from app.services.color_families import family_score,hex_to_rgb
from app.services.discovery import base_candidates,refine_color,begin_tinder,next_tinder,tinder_action,feedback,favorite,restaurants
from app.services.analytics import metrics,csv_bytes
from app.handlers.discovery import start_quiz,quiz_callback,Quiz,palette_image,card,show_tinder
from app.handlers.analytics import analytics

@pytest_asyncio.fixture
async def db(tmp_path):
    path=tmp_path/'test.db'; store=Store(path); await store.initialize('initial-pass'); migrate(path); migrate_mvp(path); migrate_release(path); migrate_statistics(path)
    items=[{'id':1,'site_id':'1','source':'test','name':'Красное кафе','type':'кафе','menu_vibe':'итальянская','average_bill':'5000–8000 ₸','color_palette_hex':['#8B0000','#B22222'],'photo':'https://example.com/a.jpg','photos':['https://example.com/b.jpg']}, {'id':2,'site_id':'2','source':'test','name':'Синий ресторан','type':'ресторан','menu_vibe':'японская','average_bill':'20000 ₸','color_palette_hex':['#003366'] }]
    file=tmp_path/'data.json'; file.write_text(json.dumps(items,ensure_ascii=False),encoding='utf8'); import_data(file,path)
    uid=await store.register('tester',hasher.hash('password1'),20,111)
    return store,uid

def test_color_families():
    assert hex_to_rgb('#8B0000')==(139,0,0)
    assert family_score('#8B0000','red')>family_score('#003366','red')
    assert family_score('#003366','blue')>.45
    assert family_score('#556B2F','green')>.3
    assert family_score('#6B3E26','brown')>.45
    assert family_score('#F5F5F0','white')>.7
    assert family_score('#1B1B1B','black')>.7
    assert palette_image('["#ff0000","#aaaaaa"]')[:8]==b'\x89PNG\r\n\x1a\n'

@pytest.mark.asyncio
async def test_filter_before_color(db):
    store,_=db; rows=await restaurants(store)
    pool=base_candidates(rows,{'type':'кафе','cuisine':['итальянская'],'budget':7000})
    assert len(pool)==1 and pool[0][0]['name']=='Красное кафе'
    assert not refine_color(pool,'blue')
    assert refine_color(pool,'red')[0][0]['id']==pool[0][0]['id']

@pytest.mark.asyncio
async def test_tinder_and_favorites(db):
    store,uid=db; session=await begin_tinder(store,uid)
    first=await next_tinder(store,uid,session)
    assert await tinder_action(store,uid,session,first['id'],'like')
    assert not await tinder_action(store,uid,session,first['id'],'like')
    second=await next_tinder(store,uid,session)
    assert second['id']!=first['id']
    assert await tinder_action(store,uid,session,second['id'],'dislike')
    assert await next_tinder(store,uid,session) is None
    async with store.connect() as conn:
        assert (await (await conn.execute('SELECT count(*) FROM favorites WHERE user_id=?',(uid,))).fetchone())[0]==1
    assert await favorite(store,uid,first['id'],False)
    assert not await favorite(store,uid,first['id'],False)

@pytest.mark.asyncio
async def test_quiz_results_feedback_analytics(db):
    store,uid=db; state=FSMContext(MemoryStorage(),StorageKey(bot_id=1,chat_id=111,user_id=111))
    msg=SimpleNamespace(chat=SimpleNamespace(type='private'),edit_text=AsyncMock(),answer=AsyncMock(),answer_photo=AsyncMock())
    q=SimpleNamespace(from_user=SimpleNamespace(id=111),message=msg,answer=AsyncMock(),data='discover')
    await start_quiz(q,state,store)
    for value in ['итальянская','кафе','any','any','7000','any','red']:
        q.data='dq:v:'+value; await quiz_callback(q,state,store)
    assert await state.get_state() is None
    async with store.connect() as conn:
        row=await (await conn.execute('SELECT * FROM recommendation_results')).fetchone()
        assert row and row['color_score']>=.45
        assert (await (await conn.execute("SELECT count(*) FROM logs WHERE action='questionnaire_completed'")).fetchone())[0]==1
    assert not await feedback(store,uid,row['id'],6)
    assert not await feedback(store,uid+100,row['id'],5)
    assert await feedback(store,uid,row['id'],4)
    assert await feedback(store,uid,row['id'],5)
    m=await metrics(store,'all'); assert m['feedback']==1 and m['average']==5
    assert b'metric,value' in csv_bytes(m)

@pytest.mark.asyncio
async def test_photo_fallback(db):
    store,_=db; row=(await restaurants(store))[0]
    msg=SimpleNamespace(answer_photo=AsyncMock(side_effect=[Exception('bad'),None,None]),answer=AsyncMock())
    await card(msg,row,None)
    assert msg.answer_photo.await_count==3

@pytest.mark.asyncio
async def test_tinder_palette_has_no_preference_caption(db):
    store,uid=db; session=await begin_tinder(store,uid)
    msg=SimpleNamespace(answer_photo=AsyncMock(),answer=AsyncMock())
    await show_tinder(msg,store,uid,session)
    palette=msg.answer_photo.await_args_list[-1]
    assert palette.kwargs['caption']=='Палитра заведения'
    assert palette.args[0].data.startswith(b'\x89PNG\r\n\x1a\n')

@pytest.mark.asyncio
async def test_find_palette_captions_are_unchanged(db):
    store,_=db; row=(await restaurants(store))[0]
    msg=SimpleNamespace(answer_photo=AsyncMock(),answer=AsyncMock())
    await card(msg,row,None,highlight='#8B0000',family='red')
    palette=msg.answer_photo.await_args_list[-1]
    assert palette.kwargs['caption']=='Палитра заведения · выбранный цвет: Красный'
    assert palette.args[0].data.startswith(b'\x89PNG\r\n\x1a\n')
    msg.answer_photo.reset_mock()
    await card(msg,row,None)
    assert msg.answer_photo.await_args_list[-1].kwargs['caption']=='Палитра заведения · выбранный цвет: не выбран'

@pytest.mark.asyncio
async def test_tinder_missing_palette_sends_only_venue(db):
    store,_=db; row=dict((await restaurants(store))[0]); row['color_palette_hex']='[]'
    msg=SimpleNamespace(answer_photo=AsyncMock(),answer=AsyncMock())
    await card(msg,row,None,show_preference=False)
    assert msg.answer_photo.await_count==1

@pytest.mark.asyncio
async def test_back_cancel_and_admin_authorization(db):
    store,uid=db; state=FSMContext(MemoryStorage(),StorageKey(bot_id=1,chat_id=111,user_id=111))
    msg=SimpleNamespace(chat=SimpleNamespace(type='private'),edit_text=AsyncMock(),answer=AsyncMock())
    q=SimpleNamespace(from_user=SimpleNamespace(id=111),message=msg,answer=AsyncMock(),data='discover')
    await start_quiz(q,state,store)
    q.data='dq:v:any'; await quiz_callback(q,state,store)
    assert (await state.get_data())['step']==1
    q.data='dq:back'; await quiz_callback(q,state,store)
    assert (await state.get_data())['step']==0
    q.data='dq:cancel'; await quiz_callback(q,state,store)
    assert await state.get_state() is None
    q.data='analytics:all'; await analytics(q,store)
    assert q.answer.await_args.kwargs['show_alert']
    q.data='analytics:all:ratings'; await analytics(q,store)
    assert q.answer.await_args.kwargs['show_alert']

@pytest.mark.asyncio
async def test_migration_preserves_data_and_logout_ends_tinder(db):
    store,uid=db
    assert migrate_mvp(store.path) is None
    session=await begin_tinder(store,uid); card_row=await next_tinder(store,uid,session)
    await store.logout(111)
    assert not await tinder_action(store,uid,session,card_row['id'],'like')
    assert await store.login('tester','password1',111)=='ok'
    assert (await store.stats())['restaurants']==2
