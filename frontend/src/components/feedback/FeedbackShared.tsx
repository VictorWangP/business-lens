import React from 'react';
import {Badge} from '../ui/badge';
import {Select, SelectContent, SelectItem, SelectTrigger, SelectValue} from '../ui/select';
import {AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle} from '../ui/alert-dialog';
import {FeedbackStatus,statusLabels} from '../../types/feedback';
export function FeedbackBadge({status}:{status:FeedbackStatus}) {
  return <Badge variant="secondary" className={status==='pending' ? 'bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-300' : 'bg-teal-50 text-teal-700 dark:bg-teal-950 dark:text-teal-300'}>{statusLabels[status]}</Badge>;
}
export function FeedbackSelect({value,onChange,options,label,disabled=false}:{value:string;onChange:(value:string)=>void;options:Record<string,string>;label:string;disabled?:boolean}) {
  return <Select value={value} onValueChange={onChange} disabled={disabled}><SelectTrigger aria-label={label}><SelectValue /></SelectTrigger><SelectContent>{Object.entries(options).map(([value,text])=><SelectItem key={value} value={value}>{text}</SelectItem>)}</SelectContent></Select>;
}
export function DiscardDialog({open,onOpenChange,onDiscard}:{open:boolean;onOpenChange:(open:boolean)=>void;onDiscard:()=>void}) {
  return <AlertDialog open={open} onOpenChange={onOpenChange}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>放弃未保存的修改？</AlertDialogTitle><AlertDialogDescription>关闭后，当前填写的内容将不会保存。</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>继续编辑</AlertDialogCancel><AlertDialogAction onClick={onDiscard}>放弃修改</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>;
}
