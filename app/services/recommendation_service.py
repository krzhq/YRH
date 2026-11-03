"""Explainable weighted ranking. Missing data is never a positive match."""
import json
import math
import re
from app.services.opening_hours import open_status

WEIGHTS = {'cuisine':.20,'type':.10,'vibe':.15,'district':.15,'budget':.15,'time':.05,'color':.20}
ALGORITHM_VERSION = 'weighted-lab-v1'
VIBES = {'cozy':('уют','спокой','домашн'), 'romantic':('романтич',), 'modern':('современн','стильн'), 'energetic':('энергич','ярк','танц'), 'premium':('премиум','роскош','элегант'), 'group':('компан','друз','семейн')}

def hex_to_lab(value):
    if not isinstance(value,str) or not re.fullmatch(r'#[a-fA-F0-9]{6}',value): return None
    rgb=[int(value[i:i+2],16)/255 for i in (1,3,5)]
    r,g,b=[x/12.92 if x<=.04045 else ((x+.055)/1.055)**2.4 for x in rgb]
    xyz=[(r*.4124564+g*.3575761+b*.1804375)/.95047,(r*.2126729+g*.7151522+b*.0721750),(r*.0193339+g*.1191920+b*.9503041)/1.08883]
    f=[x**(1/3) if x>216/24389 else (24389/27*x+16)/116 for x in xyz]
    return (116*f[1]-16,500*(f[0]-f[1]),200*(f[1]-f[2]))

def color_similarity(preferred, actual):
    a=[lab for color in preferred or [] if (lab:=hex_to_lab(color)) is not None]
    b=[lab for color in actual or [] if (lab:=hex_to_lab(color)) is not None]
    if not a or not b: return None
    def nearest(x,y):
        return sum(max(0.,1-min(math.dist(c,d) for d in y)/100) for c in x)/len(x)
    return (nearest(a,b)+nearest(b,a))/2

def _json_array(value):
    if isinstance(value,list): return value
    try:
        result=json.loads(value or '[]')
        return result if isinstance(result,list) else []
    except (ValueError,TypeError): return []

def scores(venue, preferences):
    v=dict(venue); p=preferences; result={}; explanations=[]
    cuisine=p.get('cuisine') or []
    menu=(v.get('menu_vibe') or '').lower()
    result['cuisine']=(sum(1 for c in cuisine if c.lower() in menu)/len(cuisine) if menu else None) if cuisine else None
    wanted=p.get('type'); kind=(v.get('restaurant_type') or '').lower()
    result['type']=(float(wanted.lower() in kind) if kind else None) if wanted else None
    vibes=p.get('vibe') or []
    desc=(v.get('description') or '').lower()
    labels={label for label,words in VIBES.items() if any(word in desc for word in words)}
    result['vibe']=(len(labels.intersection(vibes))/len(vibes) if labels else None) if vibes else None
    wanted_district=p.get('district'); district=v.get('district')
    result['district']=(float(wanted_district==district) if district else None) if wanted_district else None
    budget=p.get('budget'); lo=v.get('price_min'); hi=v.get('price_max')
    if budget and lo is not None:
        if hi is None:
            result['budget']=1. if budget>=lo else max(0.,1-(lo-budget)/budget)
        else:
            distance=max(lo-budget, budget-hi, 0)
            result['budget']=max(0.,1-distance/max(budget,1))
    else: result['budget']=None
    status=open_status(v.get('working_hours'),p.get('visit_datetime'))
    result['time']=float(status) if status is not None else None
    preferred=p.get('colors') or []
    result['color']=color_similarity(preferred,_json_array(v.get('color_palette_hex'))) if preferred else None
    requested={'cuisine':bool(cuisine),'type':bool(wanted),'vibe':bool(vibes),'district':bool(wanted_district),'budget':bool(budget),'time':bool(p.get('visit_datetime')),'color':bool(preferred)}
    denominator=sum(WEIGHTS[k] for k in WEIGHTS if requested[k])
    confidence=sum(WEIGHTS[k] for k in WEIGHTS if requested[k] and result[k] is not None)/denominator if denominator else 0.
    total=sum(WEIGHTS[k]*(result[k] or 0.) for k in WEIGHTS if requested[k])/denominator if denominator else 0.
    for k,label in [('cuisine','Кухня соответствует выбранной'),('type','Подходящий тип заведения'),('vibe','Описание соответствует атмосфере'),('district','Указанный район совпадает'),('budget','Цена близка к бюджету'),('color','Близкая цветовая палитра')]:
        if result[k] is not None and result[k]>=.8: explanations.append(label)
    return {'total':total,'confidence':confidence,'criteria':result,'explanations':explanations,'algorithm_version':ALGORITHM_VERSION}

def rank(restaurants,preferences,limit=10):
    ranked=[(scores(row,preferences),dict(row)) for row in restaurants]
    ranked.sort(key=lambda pair:(-pair[0]['total'],-pair[0]['confidence'],pair[1]['id']))
    return ranked[:limit]
