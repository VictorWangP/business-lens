import React from 'react';
import type { QueryEvidence } from '../../types/chat';

export const QueryCitationContext = React.createContext<QueryEvidence[]>([]);
