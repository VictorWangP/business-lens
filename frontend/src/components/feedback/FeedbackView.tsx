import React, {useEffect,useState} from 'react';
import {CircleAlert,Search,UserRound,ChevronLeft,ChevronRight} from 'lucide-react';
import {apiRequest} from '../../services/api';
import {FeedbackPage,statusLabels,feedbackTime,errorMessage} from '../../types/feedback';
import {Button} from '../ui/button';
import {Input} from '../ui/input';
import {Card} from '../ui/card';
import {Skeleton} from '../ui/skeleton';
import {Table,TableBody,TableCell,TableHead,TableHeader,TableRow} from '../ui/table';
import {FeedbackBadge,FeedbackSelect} from './FeedbackShared';
import {FeedbackProcessDialog} from './FeedbackProcessDialog';

export function FeedbackView() {
  const [question,setQuestion]=useState(''),[user,setUser]=useState(''),[status,setStatus]=useState('all');
  const [filter,setFilter]=useState({question:'',user:'',status:'all'}),[page,setPage]=useState(1),[pageSize,setPageSize]=useState(10),[reload,setReload]=useState(0);
  const [data,setData]=useState<FeedbackPage|null>(null),[loading,setLoading]=useState(true),[error,setError]=useState(''),[selected,setSelected]=useState<string|null>(null);
  const apply=()=>{setFilter(previous=>previous.question===question.trim() && previous.user===user.trim() && previous.status===status ? previous : {question:question.trim(),user:user.trim(),status});setPage(1);};
  useEffect(()=>{const timer=setTimeout(apply,300);return()=>clearTimeout(timer);},[question,user,status]);
  useEffect(()=>{
    const controller=new AbortController();setLoading(true);setData(null);setError('');
    const params=new URLSearchParams({question:filter.question,user:filter.user,page:String(page),page_size:String(pageSize)});
    if(filter.status!=='all')params.set('status',filter.status);
    apiRequest<FeedbackPage>(`/feedback?${params}`,{signal:controller.signal}).then(value=>{
      if(controller.signal.aborted)return;
      const last=Math.max(1,Math.ceil(value.total/pageSize));
      if(page>last){setPage(last);return;}setData(value);
    }).catch(error=>{if(controller.signal.aborted)return;setError(errorMessage(error));}).finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return()=>controller.abort();
  },[filter,page,pageSize,reload]);
  const clear=()=>{setQuestion('');setUser('');setStatus('all');setFilter({question:'',user:'',status:'all'});setPage(1);};
  return <div className="p-4 md:p-6"><Card className="overflow-hidden">
    <div className="space-y-4 p-6 border-b"><div className="flex flex-wrap items-center gap-2"><CircleAlert className="h-5 w-5 text-primary"/><h1 className="font-semibold">回复校对</h1><p className="text-sm text-muted-foreground">此列表为用户标注 AI 回复有误的信息数据</p></div>
      <form className="flex flex-wrap items-center gap-3" onSubmit={event=>{event.preventDefault();apply();}}>
        <div className="relative w-full sm:w-64"><Search className="absolute left-3 top-3 h-4 w-4 text-muted-foreground"/><Input aria-label="搜索问题" maxLength={200} placeholder="搜索问题…" value={question} onChange={event=>setQuestion(event.target.value)} className="pl-9 bg-muted/50"/></div>
        <div className="relative w-full sm:w-64"><UserRound className="absolute left-3 top-3 h-4 w-4 text-muted-foreground"/><Input aria-label="搜索用户" maxLength={100} placeholder="搜索用户…" value={user} onChange={event=>setUser(event.target.value)} className="pl-9 bg-muted/50"/></div>
        <div className="w-36"><FeedbackSelect label="筛选状态" value={status} onChange={value=>{setStatus(value);setFilter({question:question.trim(),user:user.trim(),status:value});setPage(1);}} options={{all:'全部状态',...statusLabels}}/></div>
        {(question || user || status!=='all') && <Button type="button" variant="ghost" onClick={clear}>清空筛选</Button>}
        <span className="ml-auto text-sm text-muted-foreground" aria-live="polite">{loading ? '加载中…' : data ? `共 ${data.total} 条` : ''}</span>
      </form>
    </div>
    <div className="p-4 md:p-6" aria-busy={loading}>
      {error ? <div role="alert" className="py-10 text-center space-y-3"><p className="text-destructive">{error}</p><Button variant="outline" onClick={()=>setReload(value=>value+1)}>重试</Button></div> : <div className="rounded-lg border overflow-x-auto"><Table>
        <TableHeader><TableRow className="bg-muted/60"><TableHead>序号</TableHead><TableHead>用户</TableHead><TableHead className="min-w-64">问题</TableHead><TableHead className="min-w-44">反馈时间</TableHead><TableHead>状态</TableHead><TableHead>操作</TableHead></TableRow></TableHeader>
        <TableBody>{loading ? Array.from({length:5},(_,row)=><TableRow key={row}>{Array.from({length:6},(_,col)=><TableCell key={col}><Skeleton className="h-5 w-full min-w-12"/></TableCell>)}</TableRow>) : data?.items.length ? data.items.map((item,index)=><TableRow key={item.id} className="even:bg-muted/25">
          <TableCell>{(page-1)*pageSize+index+1}</TableCell><TableCell><span className="block max-w-36 truncate" title={item.user.name}>{item.user.name}</span></TableCell><TableCell><span className="block max-w-xs 2xl:max-w-xl truncate" title={item.question}>{item.question}</span></TableCell><TableCell className="whitespace-nowrap text-muted-foreground">{feedbackTime(item.created_at)}</TableCell><TableCell><FeedbackBadge status={item.status}/></TableCell><TableCell><Button variant="link" onClick={()=>setSelected(item.id)} aria-label={`处理反馈：${item.question}`}>处理</Button></TableCell>
        </TableRow>) : <TableRow><TableCell colSpan={6} className="h-40 text-center text-muted-foreground">{filter.question || filter.user || filter.status!=='all' ? '未找到匹配反馈' : '暂无反馈'}</TableCell></TableRow>}</TableBody>
      </Table></div>}
      <div className="mt-4 flex flex-wrap justify-end items-center gap-3 text-sm text-muted-foreground"><span>共 {data?.total ?? 0} 条，每页</span><div className="w-20"><FeedbackSelect label="每页条数" value={String(pageSize)} options={{10:'10',20:'20',50:'50'}} onChange={value=>{setPageSize(Number(value));setPage(1);}} disabled={loading}/></div><span>条</span><Button variant="outline" size="icon" aria-label="上一页" onClick={()=>setPage(value=>value-1)} disabled={loading || page<=1}><ChevronLeft/></Button><span aria-label="当前页">{page} / {Math.max(1,Math.ceil((data?.total || 0)/pageSize))}</span><Button variant="outline" size="icon" aria-label="下一页" onClick={()=>setPage(value=>value+1)} disabled={loading || !data || page*pageSize>=data.total}><ChevronRight/></Button></div>
    </div>
  </Card>{selected && <FeedbackProcessDialog key={selected} id={selected} onClose={()=>setSelected(null)} onSaved={()=>{setSelected(null);setReload(value=>value+1);}}/>}</div>;
}
