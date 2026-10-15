import { createContext } from 'react';

// A resumed stream creates a new runtime message, but the run started earlier.
export const RunTimingContext = createContext<string | null>(null);
