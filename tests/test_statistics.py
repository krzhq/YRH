import csv
import io
import json
import sqlite3
import pytest
import pytest_asyncio
from app.database.store import Store,now
from app.database.discovery_migration import migrate
from app.database.mvp_migration import migrate_mvp
from app.database.release_migration import migrate_release
from app.database.statistics_migration import migrate_statistics
from app.services.discovery import feedback,feedback_reason,begin_tinder,next_tinder,tinder_action
from app.services.analytics import metrics,statistics_csv
from app.services.security import hasher

@pytest_asyncio.fixture
async def setup_db(tmp_path):
    s=Store(tmp_path/'test.db'); await s.initialize('initial-pass'); migrate(s.path); migrate_mvp(s.path); migrate_release(s.path)
    uid=await s.register('customer',hasher.hash('password1'),20,11)
    rid=await s.insert_restaurant('Venue','District','Cafe',5000)
    stamp=now()
    async with s.connect() as db:
        cur=await db.execute("INSERT INTO recommendation_sessions(user_id,preferences,status,created_at,completed_at) VALUES(?,?,'completed',?,?)",(uid,json.dumps({'cuisine':['Italian'],'budget':7000,'color':'red'}),stamp,stamp)); sid=cur.lastrowid
        cur=await db.execute('INSERT INTO recommendation_results(session_id,restaurant_id,rank_position,score,confidence,criteria,created_at) VALUES(?,?,1,1,1,?,?)',(sid,rid,'{}',stamp)); result=cur.lastrowid
        await db.execute('INSERT INTO recommendation_feedback(user_id,result_id,rating,reason,created_at,updated_at) VALUES(?,?,?,?,?,?)',(uid,result,2,'Price',stamp,stamp)); await db.commit()
    return s,uid,rid,sid,result,stamp

@pytest.mark.asyncio
async def test_migrate_preserves_legacy_and_idempotency(setup_db):
    store,uid,rid,sid,result,stamp=setup_db
    migration=migrate_statistics(store.path); assert migration['migrated']==1 and migration['total']==1 and migration['backup']
    assert migrate_statistics(store.path)['migrated']==0
    async with store.connect() as db:
        row=await (await db.execute('SELECT * FROM statistics')).fetchone()
        assert (row['user_id'],row['restaurant_id'],row['recommendation_session_id'],row['recommendation_result_id'],row['stars'],row['feedback_reason'],row['created_at'],row['updated_at'])==(uid,rid,sid,result,2,'Price',stamp,stamp)
        assert (await (await db.execute('PRAGMA foreign_key_check')).fetchall())==[]
        with pytest.raises(sqlite3.IntegrityError): await db.execute('UPDATE recommendation_feedback SET rating=3')
        with pytest.raises(sqlite3.IntegrityError): await db.execute('UPDATE statistics SET stars=6')
        with pytest.raises(sqlite3.IntegrityError): await db.execute('UPDATE statistics SET user_id=1')

@pytest.mark.asyncio
async def test_rating_update_dedup_reasons_and_tinder(setup_db):
    store,uid,rid,sid,result,stamp=setup_db; migrate_statistics(store.path)
    assert await feedback(store,uid,result,2)
    async with store.connect() as db:
        assert (await (await db.execute("SELECT count(*) FROM logs WHERE action='recommendation_rated'")).fetchone())[0]==0
    assert not await feedback(store,1,result,5)
    assert not await feedback(store,uid,result,0)
    assert await feedback(store,uid,result,3)
    assert await feedback_reason(store,uid,result,'Atmosphere')
    async with store.connect() as db:
        r=await (await db.execute('SELECT * FROM statistics')).fetchone(); assert (r['stars'],r['feedback_reason'],r['created_at'])==(3,'Atmosphere',stamp)
        cur=await db.execute("INSERT INTO recommendation_sessions(user_id,preferences,status,created_at,completed_at) VALUES(?,'{}','completed',?,?)",(uid,now(),now())); new_sid=cur.lastrowid
        cur=await db.execute("INSERT INTO recommendation_results(session_id,restaurant_id,rank_position,score,confidence,criteria,created_at) VALUES(?,?,1,1,1,'{}',?)",(new_sid,rid,now())); new_result=cur.lastrowid; await db.commit()
    assert await feedback(store,uid,new_result,5)
    session=await begin_tinder(store,uid); venue=await next_tinder(store,uid,session)
    assert await tinder_action(store,uid,session,venue['id'],'like')
    assert await next_tinder(store,uid,session) is None
    session=await begin_tinder(store,uid); venue=await next_tinder(store,uid,session)
    assert await tinder_action(store,uid,session,venue['id'],'dislike')
    async with store.connect() as db:
        assert (await (await db.execute('SELECT count(*) FROM statistics')).fetchone())[0]==2
        assert (await (await db.execute('SELECT count(*) FROM favorites')).fetchone())[0]==1
        assert (await (await db.execute("SELECT count(*) FROM logs WHERE action='recommendation_rated'")).fetchone())[0]==2
    m=await metrics(store,'all')
    assert m['feedback']==2 and m['average']==4 and m['median']==4 and m['positive']==1 and m['likes']==1 and m['dislikes']==1
    rows=list(csv.DictReader(io.StringIO((await statistics_csv(store,'all')).decode('utf-8-sig'))))
    assert len(rows)==2 and rows[0]['feedback_reason']=='Atmosphere' and rows[1]['recommendation_session_id']==str(new_sid)
