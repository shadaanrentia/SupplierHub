"""Normalize saved/API category hierarchies without inventing category identities."""
import json


def category_tree(value):
    if isinstance(value, str):
        try:value=json.loads(value)
        except (ValueError,TypeError):return []
    nodes={}
    def visit(rows,parent=None):
        for _ in range(6):
            if not isinstance(rows,dict):break
            rows=rows.get('categories',rows.get('data',[]))
        for original in rows if isinstance(rows,list) else []:
            if not isinstance(original,dict):continue
            identity=str(original.get('lightspeed_category_id') or original.get('id') or '').strip()
            name=str(original.get('category_name') or original.get('name') or '').strip()
            if not identity or not name:continue
            parent_id=original.get('parent_id') or original.get('parent_category_id') or parent
            if isinstance(parent_id,dict):parent_id=parent_id.get('id')
            row={**original,'lightspeed_category_id':identity,'category_name':name,
                 'parent_id':str(parent_id).strip() if parent_id else None}
            nodes[identity]=row
            visit(original.get('children'),identity)
    visit(value)
    # The API may include ancestors only in category_path. Their returned IDs
    # are evidence; labels alone never manufacture a destination ID.
    for row in list(nodes.values()):
        path=row.get('category_path')
        if not isinstance(path,list):continue
        previous=None
        for item in path:
            if not isinstance(item,dict):continue
            identity=str(item.get('id') or item.get('lightspeed_category_id') or '').strip()
            name=str(item.get('name') or item.get('category_name') or '').strip()
            if not identity or not name:continue
            nodes.setdefault(identity,{'lightspeed_category_id':identity,'category_name':name,'parent_id':previous})
            if identity!=row['lightspeed_category_id']:previous=identity
        if not row['parent_id'] and previous and previous!=row['lightspeed_category_id']:
            row['parent_id']=previous
    parents={r['parent_id'] for r in nodes.values() if r['parent_id']}
    result=[]
    for identity,row in nodes.items():
        chain=[];seen=set();current=identity;valid=True
        while current:
            if current in seen:valid=False;break
            seen.add(current)
            ancestor=nodes.get(current)
            if not ancestor:valid=False;break
            chain.insert(0,{'id':current,'name':ancestor['category_name']})
            current=ancestor['parent_id']
        if not valid:
            # Retain the record for review, but do not offer an incomplete or
            # cyclic path as a valid destination.
            chain=[]
        result.append({**row,'category_path':chain,'path':' > '.join(p['name'] for p in chain),
                       'hierarchy_valid':valid,'leaf_category':identity not in parents})
    return sorted(result,key=lambda row:(row['path'].casefold(),row['lightspeed_category_id']))


def category_choices(rows,products,states):
    """Actual cached leaf IDs, queue counts, and one separate unmapped bucket."""
    tree=category_tree(rows)
    available={r['lightspeed_category_id'] for r in tree if r['hierarchy_valid'] and r['leaf_category']}
    counts={};missing=0
    for product in products:
        state=states[product['id']]
        if state.get('excluded_from_queue'):continue
        identity=str(state.get('mapped_lightspeed_category_id') or '')
        if identity not in available or state.get('category_available') is False:missing+=1
        else:counts[identity]=counts.get(identity,0)+1
    options=[{'category_id':row['lightspeed_category_id'],'category_name':row['path'],
              'product_count':counts.get(row['lightspeed_category_id'],0),'category_available':True}
             for row in tree if row['hierarchy_valid'] and row['leaf_category']]
    if missing:options.append({'category_id':'__unmapped__','category_name':'Needs category mapping',
                               'product_count':missing,'category_available':False})
    return options
