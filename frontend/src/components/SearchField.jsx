import React,{useEffect,useState} from 'react';
export default React.forwardRef(function SearchField({value='',onChange,onKeyDown,className='',disabled,...props},ref){
 const [draft,setDraft]=useState(value);
 useEffect(()=>setDraft(value??''),[value]);
 const submit=()=>{if(!disabled)onChange?.({target:{value:draft},currentTarget:{value:draft}});};
 return <span className="submitted-search"><input ref={ref} {...props} value={draft} disabled={disabled} className={className} onChange={e=>setDraft(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.nativeEvent.isComposing){e.preventDefault();submit();}else onKeyDown?.(e);}}/><button type="button" disabled={disabled} onClick={submit} className="rounded border border-zinc-700 px-3 py-2 text-sm text-zinc-200 disabled:opacity-40">Search</button></span>;
});
