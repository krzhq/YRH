import asyncio
import json
from datetime import datetime, timezone
from app.database.store import now
from app.services.color_families import restaurant_match
from app.services.recommendation_service import scores

def base_candidates(rows, preferences):
    """Strictly exclude known type/cuisine conflicts and large price mismatches."""
    result=[]
    for row in rows:
        row=dict(row); match=scores(row,preferences); c=match['criteria']
        if preferences.get('type') and c['type'] == 0: continue
        if preferences.get('cuisine') and c['cuisine'] == 0: continue
        if preferences.get('budget') and c['budget'] is not None and c['budget'] < .5: continue
        if preferences.get('district') and c['district'] == 0: continue
        result.append((row,match))
    result.sort(key=lambda item:(-item[1]['total'],-item[1]['confidence'],item[0]['id']))
    return result[:300]

def refine_color(candidates, family):
    out=[]
    for venue,match in candidates:
        try: palette=json.loads(venue.get('color_palette_hex') or '[]')
        except (TypeError,ValueError): palette=[]
        color=restaurant_match(palette,family) if family else {'score':None,'best':None,'count':0,'confidence':0}
        if family and (color['score'] is None or color['score']<.45): continue
        combined=match['total'] if not family else .8*match['total']+.2*color['score']
        out.append((venue,match,color,combined))
    out.sort(key=lambda item:(-item[3],-item[1]['confidence'],item[0]['id']))
    return out

async def log_event(db,user_id,action,restaurant_id=None,details=None):
    await db.execute('INSERT INTO logs(user_id,action,recommended_restaurant_id,details,created_at) VALUES(?,?,?,?,?)',(user_id,action,restaurant_id,json.dumps(details,ensure_ascii=False) if details else None,now()))

async def start_search(store,user_id):
    async with store.connect() as db:
        cur=await db.execute("INSERT INTO recommendation_sessions(user_id,preferences,status,created_at) VALUES(?,'{}','started',?)",(user_id,now()))
        await log_event(db,user_id,'questionnaire_started',details={'session_id':cur.lastrowid}); await db.commit(); return cur.lastrowid

async def save_step(store,user_id,session_id,action,preferences):
    async with store.connect() as db:
        cur=await db.execute("UPDATE recommendation_sessions SET preferences=? WHERE id=? AND user_id=? AND status='started'",(json.dumps(preferences,ensure_ascii=False),session_id,user_id))
        if not cur.rowcount: return False
        await log_event(db,user_id,action,details={'session_id':session_id}); await db.commit(); return True

async def restaurants(store):
    async with store.connect() as db:
        return await (await db.execute('SELECT * FROM restaurants WHERE is_active=1 ORDER BY id')).fetchall()

async def save_results(store,user_id,session_id,prefs,results):
    async with store.connect() as db:
        await db.execute('BEGIN IMMEDIATE')
        cur=await db.execute("UPDATE recommendation_sessions SET preferences=?,status='completed',completed_at=? WHERE id=? AND user_id=? AND status='started'",(json.dumps(prefs,ensure_ascii=False),now(),session_id,user_id))
        if not cur.rowcount: await db.rollback(); return False
        await log_event(db,user_id,'questionnaire_completed',details={'session_id':session_id})
        for index,(venue,match,color,total) in enumerate(results[:20],1):
            await db.execute('INSERT INTO recommendation_results(session_id,restaurant_id,rank_position,score,confidence,criteria,color_score,color_hex,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(session_id,venue['id'],index,total,match['confidence'],json.dumps(match,ensure_ascii=False),color['score'],color['best'],now()))
            await log_event(db,user_id,'recommendation_generated',venue['id'],{'session_id':session_id})
        await db.commit(); return True

async def get_result(store,user_id,session_id,rank):
    async with store.connect() as db:
        return await (await db.execute('SELECT r.*,x.id AS result_id,x.rank_position,x.score,x.criteria,x.color_hex,s.preferences AS session_preferences FROM recommendation_results x JOIN recommendation_sessions s ON s.id=x.session_id JOIN restaurants r ON r.id=x.restaurant_id WHERE s.user_id=? AND s.id=? AND x.rank_position=?',(user_id,session_id,rank))).fetchone()

async def favorite(store,user_id,restaurant_id,add=True):
    async with store.connect() as db:
        if add: cur=await db.execute('INSERT OR IGNORE INTO favorites(user_id,restaurant_id,created_at) SELECT ?,id,? FROM restaurants WHERE id=?',(user_id,now(),restaurant_id))
        else: cur=await db.execute('DELETE FROM favorites WHERE user_id=? AND restaurant_id=?',(user_id,restaurant_id))
        if cur.rowcount: await log_event(db,user_id,'favorite_added' if add else 'favorite_removed',restaurant_id)
        await db.commit(); return bool(cur.rowcount)

async def feedback(store,user_id,result_id,rating):
    if rating not in range(1,6): return False
    async with store.connect() as db:
        await db.execute('BEGIN IMMEDIATE')
        owner=await (await db.execute("SELECT x.restaurant_id,x.session_id FROM recommendation_results x JOIN recommendation_sessions s ON s.id=x.session_id WHERE x.id=? AND s.user_id=? AND s.status='completed'",(result_id,user_id))).fetchone()
        if not owner: return False
        previous=await (await db.execute('SELECT id,stars FROM statistics WHERE user_id=? AND recommendation_result_id=?',(user_id,result_id))).fetchone()
        if previous and previous['stars']==rating:
            await db.rollback(); return True
        stamp=now()
        await db.execute('INSERT INTO statistics(user_id,restaurant_id,recommendation_session_id,recommendation_result_id,stars,created_at,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id,recommendation_result_id) DO UPDATE SET feedback_reason=NULL,stars=excluded.stars,updated_at=excluded.updated_at',(user_id,owner['restaurant_id'],owner['session_id'],result_id,rating,stamp,stamp))
        await log_event(db,user_id,'recommendation_rated',owner['restaurant_id'],{'result_id':result_id,'rating':rating}); await db.commit(); return True

async def feedback_reason(store,user_id,result_id,reason):
    async with store.connect() as db:
        cur=await db.execute('UPDATE statistics SET feedback_reason=?,updated_at=? WHERE user_id=? AND recommendation_result_id=? AND stars<=3',(reason,now(),user_id,result_id))
        await db.commit(); return bool(cur.rowcount)

async def begin_tinder(store,user_id):
    async with store.connect() as db:
        await db.execute("UPDATE tinder_sessions SET status='ended',ended_at=? WHERE user_id=? AND status='active'",(now(),user_id))
        cur=await db.execute("INSERT INTO tinder_sessions(user_id,status,created_at) VALUES(?,'active',?)",(user_id,now()))
        await log_event(db,user_id,'tinder_started',details={'session_id':cur.lastrowid}); await db.commit(); return cur.lastrowid

async def next_tinder(store,user_id,session_id):
    async with store.connect() as db:
        await db.execute('BEGIN IMMEDIATE')
        session=await (await db.execute("SELECT * FROM tinder_sessions WHERE id=? AND user_id=? AND status='active'",(session_id,user_id))).fetchone()
        if not session: await db.rollback(); return None
        if session['current_restaurant_id']:
            row=await (await db.execute('SELECT * FROM restaurants WHERE id=?',(session['current_restaurant_id'],))).fetchone()
        else:
            row=await (await db.execute('SELECT * FROM restaurants WHERE is_active=1 AND id NOT IN (SELECT restaurant_id FROM tinder_actions WHERE session_id=?) ORDER BY RANDOM() LIMIT 1',(session_id,))).fetchone()
            if row:
                await db.execute('UPDATE tinder_sessions SET current_restaurant_id=? WHERE id=?',(row['id'],session_id))
                await log_event(db,user_id,'tinder_card_viewed',row['id'],{'session_id':session_id})
            else: await db.execute("UPDATE tinder_sessions SET status='ended',ended_at=? WHERE id=?",(now(),session_id))
        await db.commit(); return row

async def tinder_action(store,user_id,session_id,restaurant_id,action):
    if action not in ('like','dislike'): return False
    async with store.connect() as db:
        await db.execute('BEGIN IMMEDIATE')
        cur=await db.execute("UPDATE tinder_sessions SET current_restaurant_id=NULL WHERE id=? AND user_id=? AND status='active' AND current_restaurant_id=?",(session_id,user_id,restaurant_id))
        if not cur.rowcount: await db.rollback(); return False
        await db.execute('INSERT INTO tinder_actions(session_id,user_id,restaurant_id,action,created_at) VALUES(?,?,?,?,?)',(session_id,user_id,restaurant_id,action,now()))
        await log_event(db,user_id,'tinder_'+('liked' if action=='like' else 'disliked'),restaurant_id,{'session_id':session_id})
        if action=='like':
            cur=await db.execute('INSERT OR IGNORE INTO favorites(user_id,restaurant_id,created_at) VALUES(?,?,?)',(user_id,restaurant_id,now()))
            if cur.rowcount: await log_event(db,user_id,'favorite_added',restaurant_id)
        await db.commit(); return True
