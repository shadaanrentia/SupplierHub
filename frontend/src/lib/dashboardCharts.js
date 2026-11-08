export const graphColours=['#60a5fa','#2dd4bf','#a78bfa','#fbbf24','#fb7185','#38bdf8'];
export function distributionRows(rows,field,total,limit=5,parameter=field){
 const source=(rows||[]).filter(row=>Number(row.count)>0).map(row=>({name:String(row[field]||'Unspecified'),count:Number(row.count),value:row.value??row[field]})).sort((a,b)=>b.count-a.count||a.name.localeCompare(b.name));
 const shown=source.slice(0,limit);const rest=Math.max(0,Number(total||0)-shown.reduce((n,row)=>n+row.count,0));
 const result=shown.map((row,index)=>({...row,colour:graphColours[index%graphColours.length],href:'/products?'+new URLSearchParams({[parameter]:row.name==='Uncategorized'?'__uncategorized__':row.name==='Unbranded'?'__unbranded__':row.value})}));
 if(rest)result.push({name:'Other',count:rest,colour:'#52525b',href:'/products',other:true});
 return result;
}
export function categoryOptions(rows=[]){
 const unique=new Map();for(const raw of rows){const name=String(raw||'').trim();if(!name||name.toLowerCase()==='uncategorized')continue;const key=name.toLowerCase();if(!unique.has(key))unique.set(key,name);}
 return [{value:'__uncategorized__',label:'Uncategorized'},...[...unique.values()].sort((a,b)=>a.localeCompare(b,undefined,{numeric:true,sensitivity:'base'})).map(name=>({value:name,label:name}))];
}
const sorts={product:{asc:'name_asc',desc:'name_desc'},brand:{asc:'brand_asc',desc:'brand_desc'},inventory:{asc:'inventory_asc',desc:'inventory_desc'},price:{asc:'price_asc',desc:'price_desc'},added:{asc:'oldest',desc:'newest'},updated:{asc:'updated_asc',desc:'updated'},variants:{asc:'variants_asc',desc:'variants_desc'}};
export function sortingSelection(value){for(const [field,directions]of Object.entries(sorts))for(const [direction,key]of Object.entries(directions))if(value===key)return {field,direction};return {field:'added',direction:'desc'};}
export function sortingValue(field,direction){return sorts[field]?.[direction]||'newest';}
