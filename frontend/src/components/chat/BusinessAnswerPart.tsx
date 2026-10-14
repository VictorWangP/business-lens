import {Table,TableCaption,TableHeader,TableRow,TableHead,TableBody,TableCell} from '../ui/table';
import React from 'react';
import type {DataMessagePartProps} from '@assistant-ui/react';
import {ChartViewer} from './ChartViewer';
import {MetricCards} from './MetricCards';
import type {FinalAnswer,ChartConfig,MetricCard} from '../../types/chat';

export function BusinessAnswerPart({data}:DataMessagePartProps) {
  const presentation=data as unknown as {answer:FinalAnswer; queries:any[]};
  if (!presentation?.answer || !Array.isArray(presentation.queries)) return null;
  const tables=new Set(presentation.answer.sections.filter(section=>section.show_table).map(section=>section.query_id));
  return <div className="space-y-4 mt-4">{presentation.queries.map(query=><React.Fragment key={query.query_id}>
    {query.metrics?.length>0 && <MetricCards metrics={query.metrics as MetricCard[]}/>}
    {tables.has(query.citation_id) && <div className="overflow-x-auto rounded-xl border"><Table className="w-full text-sm">
      <TableCaption className="p-2 text-left text-muted-foreground">查询 {query.citation_id} · {query.source_name}{query.truncated ? '（结果已截断）':''}</TableCaption>
      <TableHeader><TableRow>{Object.keys(query.rows[0] || {}).map(column=><TableHead className="border-b bg-muted p-2 text-left" key={column}>{column}</TableHead>)}</TableRow></TableHeader>
      <TableBody>{query.rows.map((row:any,index:number)=><TableRow key={index}>{Object.keys(query.rows[0] || {}).map(column=><TableCell className="border-b p-2" key={column}>{String(row[column]??'')}</TableCell>)}</TableRow>)}</TableBody>
    </Table>{query.rows.length===0 && <p className="p-3">查询结果为空。</p>}</div>}
    {query.chart && <ChartViewer chart={query.chart as ChartConfig}/>}
  </React.Fragment>)}</div>;
}
