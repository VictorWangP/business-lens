import React, { useContext } from 'react';
import { QueryCitationContext } from './QueryCitationContext';

interface QueryCitationBadgeProps {
  citationId?: string;
  sourceName?: string;
}

export const QueryCitationBadge: React.FC<QueryCitationBadgeProps> = ({ citationId, sourceName: directSourceName }) => {
  const queries = useContext(QueryCitationContext);

  const query = citationId ? queries.find(q => q.citation_id === citationId || q.query_id === citationId) : undefined;
  const sourceName = directSourceName || query?.source_name || (citationId && citationId.startsWith('Q') && citationId.length > 10 ? '业务数据' : citationId ? `查询 ${citationId}` : '业务数据');

  return <span>{sourceName}</span>;
};
