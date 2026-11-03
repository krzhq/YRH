from app.services.recommendation_service import hex_to_lab,color_similarity,rank,scores

def test_color_distance_and_invalid():
    assert hex_to_lab('bad') is None
    assert color_similarity(['#ff0000'],['#ff0000']) == 1
    assert color_similarity(['#ff0000'],['#fe0100']) > color_similarity(['#ff0000'],['#0000ff'])
    assert color_similarity(['#ffffff'],[]) is None

def test_ranking_and_unknown():
    rows=[{'id':1,'restaurant_type':'Кафе','menu_vibe':'итальянская','price_min':5000,'price_max':8000,'color_palette_hex':'["#ff0000"]'}, {'id':2,'restaurant_type':'Кафе','menu_vibe':'японская','price_min':20000,'price_max':20000,'color_palette_hex':'["#0000ff"]'}]
    prefs={'cuisine':['итальянская'],'budget':7000,'colors':['#ff0000']}
    assert rank(rows,prefs)[0][1]['id']==1
    assert scores({'id':3},prefs)['total']==0
    assert scores({'id':3},prefs)['confidence']==0
