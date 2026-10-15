import {Table,TableHeader,TableRow,TableHead,TableBody,TableCell} from '../ui/table';
import React from 'react';
import type {DataMessagePartProps} from '@assistant-ui/react';
import {ChartViewer} from './ChartViewer';
import {MetricCards} from './MetricCards';
import type {BusinessPresentation} from '../../types/chat';

export function BusinessAnswerContent({presentation}:{presentation:unknown}) {
  const presentationData = presentation as BusinessPresentation;
  if (!presentationData?.answer || !Array.isArray(presentationData.queries)) return null;

  const tables = new Set(presentationData.answer.sections.filter(section => section.show_table).map(section => section.query_id));
  const tableQueries = presentationData.queries.filter(
    query => tables.has(query.citation_id) || Boolean(query.query_id && tables.has(query.query_id))
  );
  const metricQueries = presentationData.queries.filter(query => Boolean(query.metrics?.length));
  const chartQueries = presentationData.queries.filter(query => Boolean(query.chart));

  if (!tableQueries.length && !metricQueries.length && !chartQueries.length) return null;

  let currentIndex = (presentationData.answer?.sections?.length || 0) + 1;
  const tableIndex = tableQueries.length > 0 ? currentIndex++ : null;
  const metricIndex = metricQueries.length > 0 ? currentIndex++ : null;
  const chartIndex = chartQueries.length > 0 ? currentIndex++ : null;

  return (
    <div className="space-y-4 mt-4">
      {tableIndex !== null && (
        <section>
          <h2 className="text-lg font-bold mt-6 mb-3 border-l-4 border-primary pl-3 py-1 text-foreground bg-primary/5 rounded-r-md">
            {tableIndex}. 数据表格
          </h2>
          {tableQueries.map(query => (
            <div key={query.query_id || query.citation_id} className="overflow-x-auto rounded-xl border">
              <Table className="w-full text-sm">
                <TableHeader>
                  <TableRow>
                    {Object.keys(query.rows[0] || {}).map(column => (
                      <TableHead className="border-b bg-muted p-2 text-left" key={column}>{column}</TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {query.rows.map((row, index) => (
                    <TableRow key={index}>
                      {Object.keys(query.rows[0] || {}).map(column => (
                        <TableCell className="border-b p-2" key={column}>{String(row[column] ?? '')}</TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {query.rows.length === 0 && <p className="p-3">查询结果为空。</p>}
            </div>
          ))}
        </section>
      )}

      {metricIndex !== null && (
        <section>
          <h2 className="text-lg font-bold mt-6 mb-3 border-l-4 border-primary pl-3 py-1 text-foreground bg-primary/5 rounded-r-md">
            {metricIndex}. 数据统计
          </h2>
          {metricQueries.map(query => (
            <MetricCards key={query.query_id || query.citation_id} metrics={query.metrics} />
          ))}
        </section>
      )}

      {chartIndex !== null && (
        <section>
          <h2 className="text-lg font-bold mt-6 mb-3 border-l-4 border-primary pl-3 py-1 text-foreground bg-primary/5 rounded-r-md">
            {chartIndex}. 数据可视化
          </h2>
          {chartQueries.map(query => (
            query.chart ? <ChartViewer key={query.query_id || query.citation_id} chart={query.chart} /> : null
          ))}
        </section>
      )}
    </div>
  );
}

export function BusinessAnswerPart({data}:DataMessagePartProps) {
  return <BusinessAnswerContent presentation={data}/>;
}

