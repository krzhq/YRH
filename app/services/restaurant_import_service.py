"""Lossless, transactional import of the supplied restaurant JSON."""
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

def parse_price(value):
    if value is None or not str(value).strip(): return (None, None, None)
    text = str(value).replace('\u00a0',' ').strip().lower()
    nums = [int(re.sub(r'\s','', x)) for x in re.findall(r'\d(?:[\d\s]*\d)?', text)]
    if not nums or len(nums) > 2: return (None,None,None)
    if len(nums) == 2:
        lo, hi = sorted(nums)
        return lo, hi, (lo+hi)//2
    if re.search(r'\bот\s', text): return nums[0], None, None
    if re.search(r'\bдо\s', text): return None, nums[0], None
    return nums[0], nums[0], nums[0]

def valid_url(value):
    try:
        u = urlsplit(value)
        return u.scheme in ('http','https') and bool(u.hostname) and not u.username and not u.password
    except (ValueError, TypeError): return False

def clean_number(value, minimum=None, maximum=None):
    try:
        if value is None or value == '' or isinstance(value,bool): return None
        v = float(value)
        if not __import__('math').isfinite(v) or (minimum is not None and v < minimum) or (maximum is not None and v > maximum): return None
        return v
    except (ValueError, TypeError): return None

def normalized(item):
    if not isinstance(item,dict): raise ValueError('запись не является объектом')
    if not isinstance(item.get('name'),str) or not item['name'].strip(): raise ValueError('отсутствует название')
    site_id, original = item.get('site_id'), item.get('id')
    if site_id is None and original is None: raise ValueError('отсутствуют site_id и id')
    source = str(item.get('source') or '').strip()
    key = json.dumps([source, 'site' if site_id not in (None,'') else 'id', str(site_id if site_id not in (None,'') else original)], ensure_ascii=False, separators=(',',':'))
    categories = item.get('categories') if isinstance(item.get('categories'),list) else []
    photos = item.get('photos') if isinstance(item.get('photos'),list) else []
    palette = item.get('color_palette_hex') if isinstance(item.get('color_palette_hex'),list) else []
    contacts = item.get('contacts') if isinstance(item.get('contacts'),dict) else {}
    price = parse_price(item.get('average_bill'))
    lat = clean_number(item.get('latitude'),-90,90); lon = clean_number(item.get('longitude'),-180,180)
    if lat is None or lon is None: lat = lon = None
    districts = {'Алматинский','Байконурский','Есильский','Нура','Сарайшык','Сарыарка'}
    district = item.get('district') if item.get('district') in districts else None
    def text(v): return v if isinstance(v,str) else (str(v) if v is not None else None)
    return {'external_key':key, 'original_json_id':text(original), 'site_id':text(site_id), 'name':item['name'].strip(), 'restaurant_type':text(item.get('type')) or 'Не указан', 'district':district,
            'average_price':price[2], 'address':text(item.get('address')), 'description':text(item.get('description')), 'source':source, 'categories':json.dumps(categories,ensure_ascii=False),
            'capacity':clean_number(item.get('capacity'),0), 'landmark':text(item.get('landmark')), 'latitude':lat,'longitude':lon,'rating':clean_number(item.get('rating'),0,5),
            'reviews_count':clean_number(item.get('reviews_count'),0),'average_bill':text(item.get('average_bill')), 'price_min':price[0], 'price_max':price[1], 'price_midpoint':price[2],
            'phone':text(contacts.get('phone')), 'instagram':text(contacts.get('instagram')), 'website':text(contacts.get('site')), 'working_hours':text(item.get('working_hours')), 'status_now':text(item.get('status_now')),
            'menu_vibe':text(item.get('menu_vibe')), 'color_palette_hex':json.dumps(palette,ensure_ascii=False), 'photo':text(item.get('photo')), 'photos':json.dumps(photos,ensure_ascii=False),
            'page_url':text(item.get('page_url')), 'raw_json':json.dumps(item,ensure_ascii=False,sort_keys=True,separators=(',',':'))}

def inspect_dataset(data):
    report = {'total':len(data),'invalid_urls':0,'invalid_colors':0,'invalid_coordinates':0,'missing_district':0,'duplicate_source_ids':0,'duplicate_site_ids':0}
    ids, sites = set(), set()
    for item in data:
        if not isinstance(item,dict): continue
        for key, seen, stat in [('id',ids,'duplicate_source_ids'),('site_id',sites,'duplicate_site_ids')]:
            val = item.get(key)
            if val not in (None,''):
                val = str(val)
                if val in seen: report[stat]+=1
                seen.add(val)
        for url in [item.get('photo'),item.get('page_url')] + (item.get('photos') if isinstance(item.get('photos'),list) else []):
            if url and not valid_url(url): report['invalid_urls']+=1
        for color in item.get('color_palette_hex',[]) if isinstance(item.get('color_palette_hex'),list) else []:
            if not isinstance(color,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',color): report['invalid_colors']+=1
        lat,lon=item.get('latitude'),item.get('longitude')
        if (lat not in (None,'') or lon not in (None,'')) and (clean_number(lat,-90,90) is None or clean_number(lon,-180,180) is None): report['invalid_coordinates']+=1
        if not item.get('district'): report['missing_district']+=1
    return report

def import_data(path, db_path):
    path=Path(path)
    data=json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data,list): raise ValueError('JSON должен содержать массив')
    report=inspect_dataset(data)
    report.update(inserted=0,updated=0,unchanged=0,rejected=0,duplicates=0,reasons=[])
    seen={}
    with sqlite3.connect(db_path,timeout=30) as db:
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        for index,item in enumerate(data,1):
            try: record=normalized(item)
            except (ValueError,TypeError) as e:
                report['rejected']+=1; report['reasons'].append(f'Запись {index}: {e}'); continue
            key=record['external_key']
            if key in seen:
                report['duplicates']+=1
                if seen[key] != record['raw_json']:
                    report['rejected']+=1; report['reasons'].append(f'Запись {index}: конфликтующий дубликат {key}')
                continue
            seen[key]=record['raw_json']
            existing=db.execute('SELECT id,raw_json FROM restaurants WHERE external_key=?',(key,)).fetchone()
            stamp=datetime.now(timezone.utc).isoformat()
            if existing and existing['raw_json']==record['raw_json']:
                report['unchanged']+=1; continue
            if existing:
                fields=[k for k in record if k!='external_key']
                # A missing source district must not erase a later verified correction.
                if record['district'] is None:
                    fields.remove('district')
                db.execute('UPDATE restaurants SET '+','.join(k+'=?' for k in fields)+',updated_at=? WHERE id=?', tuple(record[k] for k in fields)+(stamp,existing['id']))
                report['updated']+=1
            else:
                fields=list(record)+['created_at','updated_at']
                db.execute('INSERT INTO restaurants ('+','.join(fields)+') VALUES ('+','.join('?' for _ in fields)+')',tuple(record.values())+(stamp,stamp))
                report['inserted']+=1
        report['database_total']=db.execute('SELECT COUNT(*) FROM restaurants').fetchone()[0]
        if report['inserted'] or report['updated'] or report['rejected']:
            event=uuid.uuid4().hex; stamp=datetime.now(timezone.utc).isoformat()
            payload=json.dumps({k:report[k] for k in ('inserted','updated','unchanged','rejected','database_total')},ensure_ascii=False)
            db.execute("INSERT INTO notification_outbox(event_id,admin_id,table_name,payload,created_at) SELECT ?,id,'restaurant_import',?,? FROM users WHERE role='admin'",(event,payload,stamp))
        db.commit()
    return report
