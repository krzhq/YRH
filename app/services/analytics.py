import csv
import io
import json
import statistics as stats_math
from collections import defaultdict, Counter
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

def period_start(period):
    local=datetime.now(ZoneInfo('Asia/Almaty'))
    if period=='all': return '0001-01-01T00:00:00+00:00'
    if period=='today': start=datetime.combine(local.date(),time.min,tzinfo=local.tzinfo)
    elif period=='7': start=local-timedelta(days=7)
    elif period=='30': start=local-timedelta(days=30)
    else: raise ValueError('Invalid period')
    return start.astimezone(timezone.utc).isoformat()

async def metrics(store,period):
    start=period_start(period)
    async with store.connect() as db:
        async def scalar(query,params=()): return (await (await db.execute(query,params)).fetchone())[0]
        m={}
        m['users']=await scalar('SELECT COUNT(*) FROM users')
        m['restaurants']=await scalar('SELECT COUNT(*) FROM restaurants')
        m['started']=await scalar('SELECT COUNT(*) FROM recommendation_sessions WHERE created_at>=?',(start,))
        m['completed']=await scalar("SELECT COUNT(*) FROM recommendation_sessions WHERE status='completed' AND created_at>=?",(start,))
        m['search_users']=await scalar('SELECT COUNT(DISTINCT user_id) FROM recommendation_sessions WHERE created_at>=?',(start,))
        m['results']=await scalar('SELECT COUNT(*) FROM recommendation_results WHERE created_at>=?',(start,))
        m['views']=await scalar("SELECT COUNT(*) FROM logs WHERE action='recommendation_viewed' AND created_at>=?",(start,))
        m['feedback']=await scalar('SELECT COUNT(*) FROM statistics WHERE updated_at>=?',(start,))
        m['rated_results']=await scalar('SELECT COUNT(DISTINCT f.recommendation_result_id) FROM statistics f JOIN recommendation_results r ON r.id=f.recommendation_result_id WHERE r.created_at>=?',(start,))
        m['average']=await scalar('SELECT AVG(stars) FROM statistics WHERE updated_at>=?',(start,))
        m['positive']=await scalar('SELECT COUNT(*) FROM statistics WHERE stars>=4 AND updated_at>=?',(start,))
        m['negative']=await scalar('SELECT COUNT(*) FROM statistics WHERE stars<=2 AND updated_at>=?',(start,))
        m['rating_users']=await scalar('SELECT COUNT(DISTINCT user_id) FROM statistics WHERE updated_at>=?',(start,))
        rows=await (await db.execute('''SELECT t.stars,t.feedback_reason,t.updated_at,r.name,s.preferences
            FROM statistics t JOIN restaurants r ON r.id=t.restaurant_id
            JOIN recommendation_sessions s ON s.id=t.recommendation_session_id WHERE t.updated_at>=?''',(start,))).fetchall()
        stars=[r['stars'] for r in rows]; m['median']=stats_math.median(stars) if stars else None
        m['star_distribution']={str(i):stars.count(i) for i in range(1,6)}
        m['negative_reasons']=Counter(r['feedback_reason'] for r in rows if r['stars']<=2 and r['feedback_reason']).most_common(5)
        groups={name:defaultdict(list) for name in ('date','restaurant','cuisine','budget','color')}
        for row in rows:
            try: prefs=json.loads(row['preferences'])
            except (ValueError,TypeError): prefs={}
            try: local_date=datetime.fromisoformat(row['updated_at']).astimezone(ZoneInfo('Asia/Almaty')).date().isoformat()
            except (ValueError,TypeError): local_date='неизвестно'
            for key,values in [('date',[local_date]),('restaurant',[row['name']]),('cuisine',prefs.get('cuisine') or []),('budget',[prefs.get('budget')]),('color',[prefs.get('color')])]:
                if not isinstance(values,list): values=[values]
                for value in values:
                    if value is not None and value!='': groups[key][str(value)].append(row['stars'])
        for key,values in groups.items():
            m['average_by_'+key]=[(label,round(sum(scores)/len(scores),2),len(scores)) for label,scores in sorted(values.items(),key=lambda item:(-len(item[1]),item[0]))[:5]]
        m['likes']=await scalar("SELECT COUNT(*) FROM tinder_actions WHERE action='like' AND created_at>=?",(start,))
        m['dislikes']=await scalar("SELECT COUNT(*) FROM tinder_actions WHERE action='dislike' AND created_at>=?",(start,))
        m['favorites']=await scalar('SELECT COUNT(*) FROM favorites')
        m['favorite_users']=await scalar('SELECT COUNT(DISTINCT user_id) FROM favorites')
        m['active']=await scalar('SELECT COUNT(DISTINCT user_id) FROM logs WHERE created_at>=?',(start,))
        m['returning']=await scalar("SELECT COUNT(*) FROM (SELECT user_id FROM logs WHERE created_at>=? GROUP BY user_id HAVING COUNT(DISTINCT date(datetime(created_at,'+5 hours')))>1)",(start,))
        m['most_liked']=await (await db.execute("SELECT r.name,COUNT(*) AS n FROM tinder_actions a JOIN restaurants r ON r.id=a.restaurant_id WHERE a.action='like' AND a.created_at>=? GROUP BY r.id ORDER BY n DESC,r.id LIMIT 5",(start,))).fetchall()
        m['most_recommended']=await (await db.execute('SELECT r.name,COUNT(*) AS n FROM recommendation_results x JOIN restaurants r ON r.id=x.restaurant_id WHERE x.created_at>=? GROUP BY r.id ORDER BY n DESC,r.id LIMIT 5',(start,))).fetchall()
        prefs=await (await db.execute("SELECT preferences FROM recommendation_sessions WHERE status='completed' AND completed_at>=?",(start,))).fetchall()
        import collections
        for key in ('cuisine','district','budget','color'):
            counter=collections.Counter()
            for row in prefs:
                v=json.loads(row[0]).get(key)
                if isinstance(v,list): counter.update(str(x) for x in v)
                elif v is not None: counter[str(v)]+=1
            m['popular_'+key]=counter.most_common(3)
        return m

def csv_bytes(m):
    out=io.StringIO(newline=''); writer=csv.writer(out); writer.writerow(['metric','value'])
    for key,value in m.items():
        if isinstance(value,list):
            for row in value:
                label=str(row[0]); label="'"+label if label.startswith(('=','+','-','@','\t','\r')) else label
                writer.writerow([key, ': '.join([label]+[str(v) for v in row[1:]])])
        elif isinstance(value,dict):
            for label,count in value.items(): writer.writerow([key+'_'+str(label),count])
        else: writer.writerow([key,value])
    return ('\ufeff'+out.getvalue()).encode('utf-8')

async def event_csv(store,period):
    start=period_start(period)
    async with store.connect() as db:
        rows=await (await db.execute('SELECT created_at,action,recommended_restaurant_id FROM logs WHERE created_at>=? ORDER BY id LIMIT 50000',(start,))).fetchall()
    out=io.StringIO(newline=''); writer=csv.writer(out); writer.writerow(['created_at_utc','action','restaurant_id'])
    writer.writerows(tuple(row) for row in rows)
    return ('\ufeff'+out.getvalue()).encode('utf-8')

def safe_csv_cell(value):
    if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@','\t','\r')): return "'"+value
    return value

async def statistics_csv(store,period):
    async with store.connect() as db:
        rows=await (await db.execute('SELECT id,user_id,restaurant_id,recommendation_session_id,recommendation_result_id,stars,feedback_reason,created_at,updated_at FROM statistics WHERE updated_at>=? ORDER BY id',(period_start(period),))).fetchall()
    out=io.StringIO(newline=''); writer=csv.writer(out)
    writer.writerow(['statistics_id','user_id','restaurant_id','recommendation_session_id','recommendation_result_id','stars','feedback_reason','created_at','updated_at'])
    for row in rows: writer.writerow([safe_csv_cell(value) for value in row])
    return ('\ufeff'+out.getvalue()).encode('utf-8')

async def tinder_csv(store,period):
    async with store.connect() as db:
        rows=await (await db.execute('SELECT session_id,restaurant_id,action,created_at FROM tinder_actions WHERE created_at>=? ORDER BY id',(period_start(period),))).fetchall()
    out=io.StringIO(newline=''); writer=csv.writer(out); writer.writerow(['session_id','restaurant_id','action','created_at'])
    writer.writerows(tuple(row) for row in rows)
    return ('\ufeff'+out.getvalue()).encode('utf-8')
