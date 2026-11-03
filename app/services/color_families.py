import colorsys
import math
from app.services.recommendation_service import hex_to_lab

COLORS = {'white':('Белый','#F3F0E8'),'black':('Чёрный','#292929'),'red':('Красный','#B33A3A'),'blue':('Синий','#356A9C'),'green':('Зелёный','#64804B'),'yellow':('Жёлтый','#E6C454'),'orange':('Оранжевый','#D9893C'),'pink':('Розовый','#D58EAA'),'purple':('Фиолетовый','#8D70A6'),'brown':('Коричневый','#7B502A')}
FAMILY_HUES = {'red':0.,'orange':30.,'yellow':57.,'green':115.,'blue':215.,'purple':280.,'pink':335.}

def hex_to_rgb(value):
    if hex_to_lab(value) is None: return None
    return tuple(int(value[i:i+2],16) for i in (1,3,5))

def family_score(color, family):
    rgb = hex_to_rgb(color)
    if rgb is None or family not in COLORS: return 0.
    h,s,v = colorsys.rgb_to_hsv(*(x/255 for x in rgb)); hue=h*360
    lab=hex_to_lab(color); reference=hex_to_lab(COLORS[family][1])
    similarity=max(0.,1-math.dist(lab,reference)/120)
    if family == 'white': return max(0., min(1., (v-.72)/.25))*max(0.,1-s*.8)
    if family == 'black': return max(0., min(1., (.32-v)/.25))*max(0.,1-s*.4)
    if family == 'brown':
        delta=abs((hue-30+180)%360-180)
        return max(0.,1-delta/65)*min(1.,s/.25)*max(0.,min(1.,(0.95-v)/.35))*(.6+.4*similarity)
    delta=abs((hue-FAMILY_HUES[family]+180)%360-180)
    width=65 if family in ('green','blue','pink','red') else 48
    chroma=min(1.,s/.22)*min(1.,v/.25)
    return max(0.,1-delta/width)*chroma*(.65+.35*similarity)

def restaurant_match(colors, family):
    valid=[c for c in (colors or []) if hex_to_rgb(c) is not None]
    if not valid: return {'score':None,'best':None,'count':0,'confidence':0.}
    values=[(family_score(c,family),c) for c in valid]
    best,color=max(values)
    return {'score':best,'best':color,'count':sum(v>=.45 for v,_ in values),'confidence':min(1.,len(valid)/3)}
