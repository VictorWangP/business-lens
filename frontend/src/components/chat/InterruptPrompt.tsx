import React,{useState} from 'react';
import {useAgUiInterrupts,useAgUiSubmitInterruptResponses} from '@assistant-ui/react-ag-ui';
import {Button} from '../ui/button';
import {Input} from '../ui/input';

export function InterruptPrompt(){
  const interrupts=useAgUiInterrupts();
  const submit=useAgUiSubmitInterruptResponses();
  const [values,setValues]=useState<Record<string,string>>({});
  const [busy,setBusy]=useState(false);
  if (!interrupts.length) return null;
  return <form className="m-4 rounded-xl border bg-card p-4 space-y-3" onSubmit={async event=>{
    event.preventDefault();setBusy(true);
    try {await submit(interrupts.map(item=>({interruptId:item.id,status:'resolved',payload:values[item.id]?.trim()})));}
    finally {setBusy(false);}
  }}>{interrupts.map(item=><label className="block space-y-2" key={item.id}><span>{item.message || '请补充业务条件后继续'}</span>
    <Input required maxLength={2000} value={values[item.id] || ''} onChange={event=>setValues({...values,[item.id]:event.target.value})}/></label>)}
    <Button type="submit" disabled={busy}>{busy?'正在继续…':'确认并继续'}</Button>
  </form>;
}
